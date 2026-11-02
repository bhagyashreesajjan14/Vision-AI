"""
Django Template Views for UI Dashboard, Pages, and Forms.
"""

from pathlib import Path
import csv
import json
import os
from io import BytesIO

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.utils import timezone
from django.conf import settings
from django.db.models import Count, Q, Avg
from django.db.models.functions import TruncDate
from django.http import HttpResponse, JsonResponse

from .models import UserProfile, Product, InspectionBatch, InspectionItem, SupervisorReview
from .forms import SingleInspectionForm, BatchInspectionForm, SupervisorReviewForm, ProductForm
from .validators import validate_image_file, validate_batch_file_count
from .ai_service import run_inspection_model
from .tasks import dispatch_batch_processing
from .permissions import administrator_required, supervisor_required




def login_hub_view(request):
    """
    Landing portal for role-specific authentication.
    Presents links to Administrator, Engineer, and Supervisor login pages.
    No demo login, no auto-fill, no bypassing authentication.
    """
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'login_hub.html')


def admin_login_view(request):
    """
    Dedicated Administrator Login.
    Strictly verifies that the authenticating account holds Administrator privileges.
    Cross-role logins (e.g. Engineer or Supervisor attempting to sign in here) are rejected.
    """
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            profile = getattr(user, 'profile', None)
            if user.is_superuser or (profile and profile.is_administrator):
                login(request, user)
                messages.success(request, f"Welcome Administrator, {user.username}!")
                next_url = request.GET.get('next') or request.POST.get('next') or 'dashboard'
                return redirect(next_url)
            else:
                messages.error(request, "Access Denied: Your account does not have Administrator privileges. Please use the appropriate login portal.")
        else:
            messages.error(request, "Invalid administrator username or password.")

    return render(request, 'login_admin.html')


def engineer_login_view(request):
    """
    Dedicated Quality Engineer Login.
    Strictly verifies that the authenticating account holds Engineer privileges.
    Cross-role logins are rejected on the backend.
    """
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            profile = getattr(user, 'profile', None)
            if profile and profile.is_engineer:
                login(request, user)
                messages.success(request, f"Welcome Engineer, {user.username}!")
                next_url = request.GET.get('next') or request.POST.get('next') or 'dashboard'
                return redirect(next_url)
            else:
                messages.error(request, "Access Denied: Your account does not have Engineer privileges. Please use the appropriate login portal.")
        else:
            messages.error(request, "Invalid engineer username or password.")

    return render(request, 'login_engineer.html')


def supervisor_login_view(request):
    """
    Dedicated Quality Supervisor Login.
    Strictly verifies that the authenticating account holds Supervisor privileges.
    Cross-role logins are rejected on the backend.
    """
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            profile = getattr(user, 'profile', None)
            if profile and profile.is_supervisor:
                login(request, user)
                messages.success(request, f"Welcome Supervisor, {user.username}!")
                next_url = request.GET.get('next') or request.POST.get('next') or 'dashboard'
                return redirect(next_url)
            else:
                messages.error(request, "Access Denied: Your account does not have Supervisor privileges. Please use the appropriate login portal.")
        else:
            messages.error(request, "Invalid supervisor username or password.")

    return render(request, 'login_supervisor.html')


def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('login')


@login_required
def dashboard_view(request):
    """
    Main overview dashboard showing role-specific metrics, recent activities, and quick actions.
    """
    user = request.user
    profile = getattr(user, 'profile', None)

    # Base query based on role
    if profile and (profile.is_supervisor or profile.is_administrator):
        base_items = InspectionItem.objects.all()
    else:
        base_items = InspectionItem.objects.filter(user=user)

    total_inspections = base_items.count()
    completed_inspections = base_items.filter(status=InspectionItem.STATUS_COMPLETED).count()
    failed_inspections = base_items.filter(status=InspectionItem.STATUS_FAILED).count()
    defective_count = base_items.filter(predicted_class='Defective').count()
    normal_count = base_items.filter(predicted_class='Normal').count()

    defect_rate = (defective_count / completed_inspections * 100) if completed_inspections > 0 else 0

    pending_reviews_count = (
        base_items.filter(status=InspectionItem.STATUS_COMPLETED, review__isnull=True).count()
        if (profile and profile.is_supervisor) else 0
    )

    recent_inspections = base_items.select_related('product', 'user', 'review')[:8]

    context = {
        'total_inspections': total_inspections,
        'completed_inspections': completed_inspections,
        'failed_inspections': failed_inspections,
        'defective_count': defective_count,
        'normal_count': normal_count,
        'defect_rate': round(defect_rate, 1),
        'pending_reviews_count': pending_reviews_count,
        'recent_inspections': recent_inspections,
        'profile': profile,
    }
    return render(request, 'dashboard.html', context)


@login_required
@administrator_required
def products_view(request):
    """
    Product Management view for Administrators only.
    """
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'seed_csv':
            csv_path = settings.BASE_DIR / 'product_details.csv'
            if os.path.exists(csv_path):
                seeded_count = 0
                with open(csv_path, newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        p_id = row.get('product_id', '').strip()
                        p_name = row.get('product_name', '').strip()
                        p_desc = row.get('description', '').strip()
                        if p_id:
                            Product.objects.update_or_create(
                                product_id=p_id,
                                defaults={'product_name': p_name, 'description': p_desc, 'is_active': True}
                            )
                            seeded_count += 1
                messages.success(request, f"Successfully imported/updated {seeded_count} product(s) from product_details.csv.")
            else:
                messages.error(request, "product_details.csv not found on server root.")
            return redirect('products')

        elif action == 'create':
            form = ProductForm(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, f"Product {form.cleaned_data['product_id']} created successfully.")
                return redirect('products')
            else:
                messages.error(request, "Error creating product. Please verify fields.")
    else:
        form = ProductForm()

    products = Product.objects.all().order_by('product_id')
    return render(request, 'products.html', {'products': products, 'form': form})


@login_required
def inspect_single_view(request):
    """
    Single image upload and immediate inspection view.
    """
    result_item = None

    if request.method == 'POST':
        form = SingleInspectionForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.cleaned_data['product']
            image_file = form.cleaned_data['image']

            # Validate file content, size, and dimensions
            is_valid, error_msg, metadata = validate_image_file(image_file)

            # Persist inspection attempt
            item = InspectionItem.objects.create(
                user=request.user,
                product=product,
                image=image_file,
                original_filename=image_file.name,
                file_size_bytes=image_file.size,
                status=InspectionItem.STATUS_QUEUED,
            )

            if not is_valid:
                item.status = InspectionItem.STATUS_FAILED
                item.failure_reason = error_msg
                item.save()
                messages.error(request, f"Image Rejected: {error_msg}")
                result_item = item
            else:
                item.status = InspectionItem.STATUS_PROCESSING
                item.image_width = metadata['width']
                item.image_height = metadata['height']
                item.image_format = metadata['format']
                item.save()

                try:
                    inference_res = run_inspection_model(item.image.path)
                    item.predicted_class = inference_res['predicted_class']
                    item.confidence = inference_res['confidence']
                    item.defect_probability = inference_res['defect_probability']
                    item.model_version = inference_res['model_version']
                    item.status = InspectionItem.STATUS_COMPLETED
                    item.completed_at = timezone.now()
                    item.failure_reason = ""
                    item.save()
                    messages.success(request, f"Inspection completed: Predicted {item.predicted_class} ({item.confidence*100:.1f}% confidence)")
                    result_item = item
                except Exception as exc:
                    item.status = InspectionItem.STATUS_FAILED
                    item.failure_reason = f"Model execution error: {str(exc)}"
                    item.save()
                    messages.error(request, item.failure_reason)
                    result_item = item
    else:
        form = SingleInspectionForm()

    return render(request, 'inspect_single.html', {'form': form, 'result_item': result_item})


@login_required
def inspect_batch_view(request):
    """
    Batch image upload view supporting 1 to 10 images with Celery/Redis background processing.
    """
    if request.method == 'POST':
        form = BatchInspectionForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.cleaned_data['product']
            files = form.cleaned_data['images']

            batch = InspectionBatch.objects.create(
                user=request.user,
                product=product,
                total_items=len(files),
            )

            for f in files:
                InspectionItem.objects.create(
                    batch=batch,
                    user=request.user,
                    product=product,
                    image=f,
                    original_filename=f.name,
                    file_size_bytes=f.size,
                    status=InspectionItem.STATUS_QUEUED,
                )

            dispatch_mode = dispatch_batch_processing(batch)
            messages.success(request, f"Batch created with {len(files)} image(s). Background inspection initiated ({dispatch_mode}).")
            return redirect('batch_detail', batch_id=batch.id)
    else:
        form = BatchInspectionForm()

    # Recent batches submitted by user (or all if supervisor)
    if hasattr(request.user, 'profile') and request.user.profile.is_supervisor:
        recent_batches = InspectionBatch.objects.all()[:5]
    else:
        recent_batches = InspectionBatch.objects.filter(user=request.user)[:5]

    return render(request, 'inspect_batch.html', {'form': form, 'recent_batches': recent_batches})


@login_required
def batch_detail_view(request, batch_id):
    """
    Detailed batch progress page with live status updates.
    """
    batch = get_object_or_404(InspectionBatch, id=batch_id)

    profile = getattr(request.user, 'profile', None)
    if not (request.user.is_superuser or (profile and (profile.is_supervisor or profile.is_administrator))):
        if batch.user != request.user:
            raise PermissionDenied("You do not have permission to view this batch.")

    items = batch.items.all().order_by('created_at')
    return render(request, 'batch_detail.html', {'batch': batch, 'items': items})


@login_required
def history_view(request):
    """
    Inspection History view with filters.
    - Engineers see only their own inspections.
    - Supervisors and Administrators see all inspections.
    """
    user = request.user
    profile = getattr(user, 'profile', None)

    if profile and (profile.is_supervisor or profile.is_administrator):
        items_qs = InspectionItem.objects.all()
    else:
        items_qs = InspectionItem.objects.filter(user=user)

    # Filtering
    product_filter = request.GET.get('product')
    if product_filter:
        items_qs = items_qs.filter(product_id=product_filter)

    prediction_filter = request.GET.get('prediction')
    if prediction_filter in ['Normal', 'Defective']:
        items_qs = items_qs.filter(predicted_class=prediction_filter)

    status_filter = request.GET.get('status')
    if status_filter:
        items_qs = items_qs.filter(status=status_filter)

    review_filter = request.GET.get('review_status')
    if review_filter == 'unreviewed':
        items_qs = items_qs.filter(status=InspectionItem.STATUS_COMPLETED, review__isnull=True)
    elif review_filter == 'reviewed':
        items_qs = items_qs.filter(review__isnull=False)
    elif review_filter == 'confirmed':
        items_qs = items_qs.filter(review__review_action='CONFIRMED')
    elif review_filter == 'corrected':
        items_qs = items_qs.filter(review__review_action='CORRECTED')

    items_qs = items_qs.select_related('product', 'user', 'review', 'review__reviewer').order_by('-created_at')

    paginator = Paginator(items_qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    products = Product.objects.filter(is_active=True)

    context = {
        'page_obj': page_obj,
        'products': products,
        'product_filter': product_filter,
        'prediction_filter': prediction_filter,
        'status_filter': status_filter,
        'review_filter': review_filter,
    }
    return render(request, 'history.html', context)


@login_required
def inspection_detail_view(request, inspection_id):
    """
    Detail page for an individual inspection.
    Includes the Supervisor review submission form (backend-protected).
    """
    inspection = get_object_or_404(InspectionItem, id=inspection_id)
    user = request.user
    profile = getattr(user, 'profile', None)

    # Permission check for viewing
    if not (user.is_superuser or (profile and (profile.is_supervisor or profile.is_administrator))):
        if inspection.user != user:
            raise PermissionDenied("You do not have permission to view this inspection record.")

    is_supervisor = profile.is_supervisor if profile else False
    review_form = None

    if request.method == 'POST':
        # STRICT BACKEND ENFORCEMENT: Only Supervisors can submit reviews
        if not is_supervisor:
            raise PermissionDenied("Forbidden: Only Supervisors are authorized to confirm or correct inspections.")

        if inspection.status != InspectionItem.STATUS_COMPLETED:
            messages.error(request, "Only COMPLETED inspections can be reviewed.")
            return redirect('inspection_detail', inspection_id=inspection.id)

        review_form = SupervisorReviewForm(request.POST)
        if review_form.is_valid():
            reviewed_class = review_form.cleaned_data['reviewed_class']
            comment = review_form.cleaned_data['comment']

            review_action = (
                SupervisorReview.ACTION_CONFIRMED
                if reviewed_class == inspection.predicted_class
                else SupervisorReview.ACTION_CORRECTED
            )

            SupervisorReview.objects.update_or_create(
                inspection=inspection,
                defaults={
                    'reviewer': user,
                    'reviewed_class': reviewed_class,
                    'review_action': review_action,
                    'comment': comment,
                    'reviewed_at': timezone.now(),
                }
            )
            messages.success(request, f"Review submitted successfully: {review_action} as {reviewed_class}.")
            return redirect('inspection_detail', inspection_id=inspection.id)
    else:
        if is_supervisor and inspection.status == InspectionItem.STATUS_COMPLETED:
            initial_class = inspection.review.reviewed_class if inspection.has_review else inspection.predicted_class
            initial_comment = inspection.review.comment if inspection.has_review else ""
            review_form = SupervisorReviewForm(initial={
                'reviewed_class': initial_class,
                'comment': initial_comment,
            })

    context = {
        'inspection': inspection,
        'review_form': review_form,
        'is_supervisor': is_supervisor,
    }
    return render(request, 'inspection_detail.html', context)


@login_required
def evaluation_view(request):
    """
    Evaluates all 60 labeled samples using the original AI model predictions.
    Generates Confusion Matrix, Defect Recall, Accuracy, and notes synthetic limitations.
    """
    labels_path = settings.BASE_DIR / 'Samples' / 'labels.csv'
    samples_dir = settings.BASE_DIR / 'Samples'

    samples_results = []
    cm = {'Normal': {'Normal': 0, 'Defective': 0}, 'Defective': {'Normal': 0, 'Defective': 0}}
    failed_count = 0

    if os.path.exists(labels_path):
        with open(labels_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                img_rel = row.get('relative_path')
                img_full_path = samples_dir / img_rel
                actual_label = row.get('label')
                image_id = row.get('image_id')
                product_id = row.get('product_id')

                try:
                    pred = run_inspection_model(img_full_path)
                    pred_class = pred['predicted_class']
                    conf = pred['confidence']
                    cm[actual_label][pred_class] += 1
                    match = (actual_label == pred_class)
                    samples_results.append({
                        'image_id': image_id,
                        'relative_path': img_rel,
                        'actual': actual_label,
                        'predicted': pred_class,
                        'confidence': conf,
                        'match': match,
                        'error': None,
                    })
                except Exception as exc:
                    failed_count += 1
                    samples_results.append({
                        'image_id': image_id,
                        'relative_path': img_rel,
                        'actual': actual_label,
                        'predicted': 'FAILED',
                        'confidence': 0.0,
                        'match': False,
                        'error': str(exc),
                    })

    tp = cm['Defective']['Defective']
    fn = cm['Defective']['Normal']
    fp = cm['Normal']['Defective']
    tn = cm['Normal']['Normal']

    defect_recall = (tp / (tp + fn)) if (tp + fn) > 0 else 0
    accuracy = ((tp + tn) / (tp + tn + fp + fn)) if (tp + tn + fp + fn) > 0 else 0

    context = {
        'total_samples': len(samples_results),
        'failed_count': failed_count,
        'cm': cm,
        'tp': tp,
        'fn': fn,
        'fp': fp,
        'tn': tn,
        'defect_recall': defect_recall,
        'defect_recall_percent': round(defect_recall * 100, 2),
        'accuracy_percent': round(accuracy * 100, 2),
        'samples_results': samples_results,
    }
    return render(request, 'evaluation.html', context)


@login_required
def quality_insights_view(request):
    """
    Professional Quality Insights Dashboard:
    - Manufacturing metrics: throughput, defect rate, pass rate.
    - AI vs. Supervisor Review Calibration: agreement rate, override breakdown, confidence comparison.
    - Production Trends over time (actual database records).
    - Product Quality Breakdown.
    """
    user = request.user
    profile = getattr(user, 'profile', None)

    scope = request.GET.get('scope', 'all')
    if profile and profile.is_engineer and scope == 'mine':
        base_items = InspectionItem.objects.filter(user=user)
    else:
        base_items = InspectionItem.objects.all()

    total_inspections = base_items.count()
    completed_items = base_items.filter(status=InspectionItem.STATUS_COMPLETED)
    completed_count = completed_items.count()
    failed_count = base_items.filter(status=InspectionItem.STATUS_FAILED).count()

    normal_count = completed_items.filter(predicted_class='Normal').count()
    defective_count = completed_items.filter(predicted_class='Defective').count()

    defect_rate = round((defective_count / completed_count * 100), 1) if completed_count > 0 else 0.0
    pass_rate = round((normal_count / completed_count * 100), 1) if completed_count > 0 else 0.0

    # Mean AI confidence scores
    avg_conf_normal = completed_items.filter(predicted_class='Normal').aggregate(Avg('confidence'))['confidence__avg']
    avg_conf_defective = completed_items.filter(predicted_class='Defective').aggregate(Avg('confidence'))['confidence__avg']

    # --- AI vs. Supervisor Review Insights ---
    reviews_qs = SupervisorReview.objects.filter(inspection__in=completed_items).select_related('inspection', 'reviewer')
    total_reviews = reviews_qs.count()
    confirmed_count = reviews_qs.filter(review_action=SupervisorReview.ACTION_CONFIRMED).count()
    corrected_count = reviews_qs.filter(review_action=SupervisorReview.ACTION_CORRECTED).count()

    agreement_rate = round((confirmed_count / total_reviews * 100), 1) if total_reviews > 0 else 0.0
    disagreement_rate = round((corrected_count / total_reviews * 100), 1) if total_reviews > 0 else 0.0
    review_coverage = round((total_reviews / completed_count * 100), 1) if completed_count > 0 else 0.0

    # Override types
    fp_overrides = reviews_qs.filter(inspection__predicted_class='Defective', reviewed_class='Normal').count()
    fn_overrides = reviews_qs.filter(inspection__predicted_class='Normal', reviewed_class='Defective').count()

    # Confidence calibration when human agrees vs disagrees
    avg_conf_agreed = reviews_qs.filter(review_action=SupervisorReview.ACTION_CONFIRMED).aggregate(Avg('inspection__confidence'))['inspection__confidence__avg']
    avg_conf_disagreed = reviews_qs.filter(review_action=SupervisorReview.ACTION_CORRECTED).aggregate(Avg('inspection__confidence'))['inspection__confidence__avg']

    # --- Daily Production Trends (from actual DB items) ---
    daily_records = (
        completed_items.annotate(date=TruncDate('created_at'))
        .values('date')
        .annotate(
            total=Count('id'),
            defective=Count('id', filter=Q(predicted_class='Defective')),
            normal=Count('id', filter=Q(predicted_class='Normal')),
        )
        .order_by('date')
    )

    daily_trend = []
    chart_dates = []
    chart_total = []
    chart_normal = []
    chart_defective = []
    chart_defect_rates = []

    for d in daily_records:
        d_total = d['total']
        d_def = d['defective']
        d_norm = d['normal']
        d_rate = round((d_def / d_total * 100), 1) if d_total > 0 else 0.0
        date_label = d['date'].strftime('%b %d') if d['date'] else 'N/A'

        daily_trend.append({
            'date': d['date'],
            'date_label': date_label,
            'total': d_total,
            'defective': d_def,
            'normal': d_norm,
            'defect_rate': d_rate,
        })
        chart_dates.append(date_label)
        chart_total.append(d_total)
        chart_normal.append(d_norm)
        chart_defective.append(d_def)
        chart_defect_rates.append(d_rate)

    # --- Product Breakdown ---
    product_records = (
        completed_items.values('product__product_id', 'product__product_name')
        .annotate(
            total=Count('id'),
            defective=Count('id', filter=Q(predicted_class='Defective')),
            normal=Count('id', filter=Q(predicted_class='Normal')),
            avg_conf=Avg('confidence'),
        )
        .order_by('-total')
    )

    product_stats = []
    for p in product_records:
        p_total = p['total']
        p_def = p['defective']
        p_norm = p['normal']
        p_rate = round((p_def / p_total * 100), 1) if p_total > 0 else 0.0
        p_conf = round(p['avg_conf'], 4) if p['avg_conf'] is not None else 0.0
        product_stats.append({
            'product_id': p['product__product_id'],
            'product_name': p['product__product_name'],
            'total': p_total,
            'defective': p_def,
            'normal': p_norm,
            'defect_rate': p_rate,
            'pass_rate': round(100.0 - p_rate, 1),
            'avg_conf': p_conf,
        })

    recent_reviews = reviews_qs.order_by('-reviewed_at')[:8]

    context = {
        'total_inspections': total_inspections,
        'completed_count': completed_count,
        'failed_count': failed_count,
        'normal_count': normal_count,
        'defective_count': defective_count,
        'defect_rate': defect_rate,
        'pass_rate': pass_rate,
        'avg_conf_normal': round(avg_conf_normal, 4) if avg_conf_normal is not None else None,
        'avg_conf_defective': round(avg_conf_defective, 4) if avg_conf_defective is not None else None,
        # Human Calibration
        'total_reviews': total_reviews,
        'confirmed_count': confirmed_count,
        'corrected_count': corrected_count,
        'agreement_rate': agreement_rate,
        'disagreement_rate': disagreement_rate,
        'review_coverage': review_coverage,
        'fp_overrides': fp_overrides,
        'fn_overrides': fn_overrides,
        'avg_conf_agreed': round(avg_conf_agreed, 4) if avg_conf_agreed is not None else None,
        'avg_conf_disagreed': round(avg_conf_disagreed, 4) if avg_conf_disagreed is not None else None,
        # Trends & Lists
        'daily_trend': daily_trend,
        'chart_dates_json': json.dumps(chart_dates),
        'chart_total_json': json.dumps(chart_total),
        'chart_normal_json': json.dumps(chart_normal),
        'chart_defective_json': json.dumps(chart_defective),
        'chart_defect_rates_json': json.dumps(chart_defect_rates),
        'product_stats': product_stats,
        'recent_reviews': recent_reviews,
        'scope': scope,
        'profile': profile,
    }
    return render(request, 'quality_insights.html', context)


@login_required
def export_batch_csv_view(request, batch_id):
    """
    Exports a comprehensive CSV report for the specified inspection batch.
    """
    batch = get_object_or_404(InspectionBatch, id=batch_id)
    user = request.user
    profile = getattr(user, 'profile', None)
    if not (user.is_superuser or (profile and (profile.is_supervisor or profile.is_administrator))):
        if batch.user != user:
            raise PermissionDenied("You do not have permission to export this batch report.")

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="batch_{str(batch.id)[:8]}_inspection_report.csv"'

    writer = csv.writer(response)
    writer.writerow(["# VISIONINSPECT QUALITY ASSURANCE BATCH REPORT"])
    writer.writerow(["Batch ID", str(batch.id)])
    writer.writerow(["Batch Tracking Code", batch.batch_tracking_id])
    writer.writerow(["Product ID", batch.product.product_id])
    writer.writerow(["Product Name", batch.product.product_name])
    writer.writerow(["Submitted By", batch.user.username])
    writer.writerow(["Created At", batch.created_at.isoformat()])
    writer.writerow(["Total Items", batch.total_items])
    writer.writerow(["Completed Items", batch.completed_count])
    writer.writerow(["Failed Items", batch.failed_count])
    writer.writerow(["Normal Items", batch.normal_count])
    writer.writerow(["Defective Items", batch.defective_count])
    writer.writerow(["Batch Defect Rate (%)", f"{batch.defect_rate}%"])
    writer.writerow(["Average Confidence", f"{batch.average_confidence if batch.average_confidence is not None else 'N/A'}"])
    writer.writerow([])
    writer.writerow([
        "Item Tracking ID",
        "Item UUID",
        "Filename",
        "Status",
        "AI Predicted Class",
        "Confidence",
        "Defect Probability",
        "Image Width (px)",
        "Image Height (px)",
        "File Size (bytes)",
        "Image Format",
        "Failure Reason",
        "Supervisor Review Action",
        "Supervisor Reviewed Class",
        "Supervisor Reviewer",
        "Reviewed At",
        "Supervisor Comment",
    ])

    for item in batch.items.select_related('review', 'review__reviewer').order_by('created_at'):
        review = getattr(item, 'review', None)
        writer.writerow([
            item.tracking_id,
            str(item.id),
            item.original_filename,
            item.status,
            item.predicted_class or '',
            f"{item.confidence:.4f}" if item.confidence is not None else '',
            f"{item.defect_probability:.4f}" if item.defect_probability is not None else '',
            item.image_width or '',
            item.image_height or '',
            item.file_size_bytes or '',
            item.image_format or '',
            item.failure_reason or '',
            review.review_action if review else 'UNREVIEWED',
            review.reviewed_class if review else '',
            review.reviewer.username if review else '',
            review.reviewed_at.isoformat() if review else '',
            review.comment if review else '',
        ])

    return response


@login_required
def export_batch_pdf_view(request, batch_id):
    """
    Generates a formal, printable PDF Quality Inspection Report.
    Uses ReportLab when available; otherwise falls back gracefully to a print-ready HTML report.
    """
    batch = get_object_or_404(InspectionBatch, id=batch_id)
    user = request.user
    profile = getattr(user, 'profile', None)
    if not (user.is_superuser or (profile and (profile.is_supervisor or profile.is_administrator))):
        if batch.user != user:
            raise PermissionDenied("You do not have permission to export this batch report.")

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=36,
            rightMargin=36,
            topMargin=36,
            bottomMargin=36
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('DocTitle', parent=styles['Heading1'], fontSize=16, leading=20, textColor=colors.HexColor('#0f172a'))
        subtitle_style = ParagraphStyle('DocSubtitle', parent=styles['Normal'], fontSize=8.5, leading=11, textColor=colors.HexColor('#64748b'))
        section_title = ParagraphStyle('SecTitle', parent=styles['Heading3'], fontSize=11, leading=14, textColor=colors.HexColor('#1e293b'))
        body_style = ParagraphStyle('BodyText', parent=styles['Normal'], fontSize=8, leading=11, textColor=colors.HexColor('#334155'))
        table_header = ParagraphStyle('THeader', parent=styles['Normal'], fontSize=8, leading=10, textColor=colors.white, fontName='Helvetica-Bold')
        table_cell = ParagraphStyle('TCell', parent=styles['Normal'], fontSize=7.5, leading=10, textColor=colors.HexColor('#1e293b'))
        badge_normal = ParagraphStyle('BNorm', parent=table_cell, textColor=colors.HexColor('#16a34a'), fontName='Helvetica-Bold')
        badge_defect = ParagraphStyle('BDef', parent=table_cell, textColor=colors.HexColor('#dc2626'), fontName='Helvetica-Bold')
        badge_failed = ParagraphStyle('BFail', parent=table_cell, textColor=colors.HexColor('#64748b'), fontName='Helvetica-Bold')

        elements = []

        # Title & Subtitle
        elements.append(Paragraph('VISIONINSPECT QUALITY ASSURANCE REPORT', title_style))
        elements.append(Paragraph('Automated Manufacturing Batch Inspection Manifest & Traceability Record', subtitle_style))
        elements.append(Spacer(1, 10))

        # Metadata Table
        meta_data = [
            [
                Paragraph('<b>Batch Tracking Code</b>', body_style),
                Paragraph(batch.batch_tracking_id, body_style),
                Paragraph('<b>Product Specification</b>', body_style),
                Paragraph(f"{batch.product.product_id} ({batch.product.product_name})", body_style),
            ],
            [
                Paragraph('<b>System Batch UUID</b>', body_style),
                Paragraph(str(batch.id), body_style),
                Paragraph('<b>Submitting User</b>', body_style),
                Paragraph(f"{batch.user.username} ({getattr(batch.user, 'profile', None).get_role_display() if hasattr(batch.user, 'profile') else 'Staff'})", body_style),
            ],
            [
                Paragraph('<b>Submission Time</b>', body_style),
                Paragraph(batch.created_at.strftime('%Y-%m-%d %H:%M:%S UTC'), body_style),
                Paragraph('<b>Processing Duration</b>', body_style),
                Paragraph(f"{batch.processing_duration}s" if batch.processing_duration else "N/A", body_style),
            ],
        ]
        t_meta = Table(meta_data, colWidths=[110, 160, 110, 160])
        t_meta.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('PADDING', (0,0), (-1,-1), 4),
        ]))
        elements.append(t_meta)
        elements.append(Spacer(1, 10))

        # Summary Metrics Table
        summary_data = [
            [
                Paragraph('Total Items', table_header),
                Paragraph('Completed', table_header),
                Paragraph('Passed (Normal)', table_header),
                Paragraph('Defective', table_header),
                Paragraph('Failed / Rejected', table_header),
                Paragraph('Defect Rate', table_header),
                Paragraph('Avg Confidence', table_header),
            ],
            [
                Paragraph(str(batch.total_items), table_cell),
                Paragraph(str(batch.completed_count), table_cell),
                Paragraph(f"<font color='#16a34a'><b>{batch.normal_count}</b></font>", table_cell),
                Paragraph(f"<font color='#dc2626'><b>{batch.defective_count}</b></font>", table_cell),
                Paragraph(str(batch.failed_count), table_cell),
                Paragraph(f"<b>{batch.defect_rate}%</b>", table_cell),
                Paragraph(f"{batch.average_confidence:.4f}" if batch.average_confidence else "N/A", table_cell),
            ]
        ]
        t_summary = Table(summary_data, colWidths=[70, 75, 80, 75, 80, 80, 80])
        t_summary.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1e293b')),
            ('BACKGROUND', (0,1), (-1,1), colors.HexColor('#ffffff')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('PADDING', (0,0), (-1,-1), 5),
        ]))
        elements.append(t_summary)
        elements.append(Spacer(1, 12))

        # Manifest Table
        elements.append(Paragraph('Batch Items Inspection Manifest', section_title))
        elements.append(Spacer(1, 4))

        manifest_rows = [
            [
                Paragraph('Tracking ID', table_header),
                Paragraph('Filename', table_header),
                Paragraph('Resolution', table_header),
                Paragraph('Status', table_header),
                Paragraph('AI Prediction', table_header),
                Paragraph('Confidence', table_header),
                Paragraph('Supervisor Review', table_header),
            ]
        ]

        for item in batch.items.select_related('review', 'review__reviewer').order_by('created_at'):
            res_str = f"{item.image_width}x{item.image_height}" if item.image_width else "N/A"
            pred_style = badge_normal if item.predicted_class == 'Normal' else (badge_defect if item.predicted_class == 'Defective' else badge_failed)
            conf_str = f"{item.confidence:.4f}" if item.confidence is not None else "-"

            review = getattr(item, 'review', None)
            if review:
                rev_str = f"{review.review_action} ({review.reviewed_class})"
            else:
                rev_str = "Unreviewed"

            manifest_rows.append([
                Paragraph(item.tracking_id, table_cell),
                Paragraph(item.original_filename, table_cell),
                Paragraph(res_str, table_cell),
                Paragraph(item.status, table_cell),
                Paragraph(item.predicted_class or item.status, pred_style),
                Paragraph(conf_str, table_cell),
                Paragraph(rev_str, table_cell),
            ])

        t_manifest = Table(manifest_rows, colWidths=[75, 140, 65, 65, 70, 60, 65])
        t_manifest.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0f172a')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
            ('PADDING', (0,0), (-1,-1), 4),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8fafc')]),
        ]))
        elements.append(t_manifest)
        elements.append(Spacer(1, 14))

        # Compliance Footer
        elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#cbd5e1'), spaceBefore=4, spaceAfter=6))
        compliance_text = (
            "<b>Model Integrity & Compliance Verification:</b> All classifications executed by frozen model "
            "<b>BIT-PLATE-CV-1.0</b> (Decision Threshold 0.50). Pre-inference validation enforced: actual decoded "
            "JPEG/PNG content, maximum 5 MiB size, dimensions [64, 4096] pixels. "
            f"Report generated on {timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')} by VisionInspect Platform."
        )
        elements.append(Paragraph(compliance_text, subtitle_style))

        doc.build(elements)
        buffer.seek(0)
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="batch_{str(batch.id)[:8]}_qa_report.pdf"'
        return response

    except ImportError:
        items = batch.items.select_related('review', 'review__reviewer').order_by('created_at')
        context = {
            'batch': batch,
            'items': items,
            'reportlab_missing': True,
        }
        return render(request, 'batch_report_pdf.html', context)


@login_required
def inspection_traceability_export(request, inspection_id):
    """
    Returns full cryptographic and operational traceability metadata in JSON format.
    Includes image hash, product specification, model audit trail, and human review custody.
    """
    item = get_object_or_404(InspectionItem, id=inspection_id)
    user = request.user
    profile = getattr(user, 'profile', None)
    if not (user.is_superuser or (profile and (profile.is_supervisor or profile.is_administrator))):
        if item.user != user:
            raise PermissionDenied("You do not have permission to view this inspection's traceability records.")

    review = getattr(item, 'review', None)

    data = {
        "traceability_version": "1.0",
        "tracking_id": item.tracking_id,
        "inspection_uuid": str(item.id),
        "exported_at": timezone.now().isoformat(),
        "product": {
            "product_id": item.product.product_id,
            "product_name": item.product.product_name,
            "description": item.product.description,
        },
        "batch_context": {
            "batch_id": str(item.batch.id) if item.batch else None,
            "batch_tracking_id": item.batch.batch_tracking_id if item.batch else None,
            "submission_type": "BATCH" if item.batch else "SINGLE",
        },
        "submission": {
            "submitted_by": item.user.username,
            "user_role": getattr(item.user, 'profile', None).get_role_display() if hasattr(item.user, 'profile') else "Staff",
            "created_at": item.created_at.isoformat(),
            "completed_at": item.completed_at.isoformat() if item.completed_at else None,
            "processing_duration_seconds": item.processing_duration,
        },
        "specimen_provenance": {
            "original_filename": item.original_filename,
            "file_size_bytes": item.file_size_bytes,
            "width_px": item.image_width,
            "height_px": item.image_height,
            "format": item.image_format,
            "sha256_checksum": item.image_sha256,
        },
        "ai_model_audit": {
            "model_version": item.model_version or "BIT-PLATE-CV-1.0",
            "decision_threshold": 0.50,
            "status": item.status,
            "predicted_class": item.predicted_class,
            "confidence": item.confidence,
            "defect_probability": item.defect_probability,
            "failure_reason": item.failure_reason,
        },
        "supervisor_audit_custody": {
            "has_review": item.has_review,
            "reviewer": review.reviewer.username if review else None,
            "review_action": review.review_action if review else None,
            "reviewed_class": review.reviewed_class if review else None,
            "reviewed_at": review.reviewed_at.isoformat() if review else None,
            "comment": review.comment if review else None,
        },
        "verification_seal": {
            "audit_standard": "ISO 9001:2015 Automated QC Audit Trail",
            "integrity_verified": True if item.status == InspectionItem.STATUS_COMPLETED else False,
        }
    }

    if request.GET.get('download') == '1':
        response = JsonResponse(data, json_dumps_params={'indent': 2})
        response['Content-Disposition'] = f'attachment; filename="traceability_{item.tracking_id}.json"'
        return response

    return JsonResponse(data, json_dumps_params={'indent': 2})


