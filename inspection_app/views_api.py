"""
Django REST Framework API ViewSets and Endpoints.
Enforces all role checks at the API layer.
"""

from rest_framework import status, views, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.db import transaction

from .models import Product, InspectionBatch, InspectionItem, SupervisorReview
from .serializers import (
    ProductSerializer,
    InspectionBatchSerializer,
    InspectionItemSerializer,
    SupervisorReviewSerializer,
    CreateReviewSerializer,
)
from .permissions import (
    IsAdministratorUser,
    IsSupervisorUser,
    IsInspectionOwnerOrSupervisor,
)
from .validators import validate_image_file, validate_batch_file_count
from .ai_service import run_inspection_model
from .tasks import dispatch_batch_processing


class ProductViewSet(viewsets.ModelViewSet):
    """
    Product Management API.
    - List/Retrieve: Authenticated users
    - Create/Update/Delete: Administrator only
    """
    queryset = Product.objects.all()
    serializer_class = ProductSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsAdministratorUser()]
        return [IsAuthenticated()]


class InspectionItemViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Inspection History and Retrieval API.
    - Engineers see ONLY their own records.
    - Supervisors and Administrators see ALL records.
    """
    serializer_class = InspectionItemSerializer
    permission_classes = [IsAuthenticated, IsInspectionOwnerOrSupervisor]

    def get_queryset(self):
        user = self.request.user
        profile = getattr(user, 'profile', None)

        if user.is_superuser or (profile and (profile.is_supervisor or profile.is_administrator)):
            qs = InspectionItem.objects.all()
        else:
            qs = InspectionItem.objects.filter(user=user)

        # Query parameter filters
        product_id = self.request.query_params.get('product')
        if product_id:
            qs = qs.filter(product_id=product_id)

        predicted_class = self.request.query_params.get('prediction')
        if predicted_class in ['Normal', 'Defective']:
            qs = qs.filter(predicted_class=predicted_class)

        item_status = self.request.query_params.get('status')
        if item_status:
            qs = qs.filter(status=item_status)

        review_filter = self.request.query_params.get('review_status')
        if review_filter == 'reviewed':
            qs = qs.filter(review__isnull=False)
        elif review_filter == 'unreviewed':
            qs = qs.filter(review__isnull=True)
        elif review_filter == 'confirmed':
            qs = qs.filter(review__review_action='CONFIRMED')
        elif review_filter == 'corrected':
            qs = qs.filter(review__review_action='CORRECTED')

        return qs.select_related('product', 'user', 'review', 'review__reviewer')

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def review(self, request, pk=None):
        """
        Supervisor Review Action: Confirm or correct a completed inspection.
        CRITICAL: Non-supervisors (e.g. Engineers) receive HTTP 403 Forbidden.
        """
        user = request.user
        profile = getattr(user, 'profile', None)

        # STRICT BACKEND ENFORCEMENT: Only Supervisors can review
        if not (profile and profile.is_supervisor):
            return Response(
                {"detail": "Forbidden: Only Supervisors are authorized to confirm or correct inspections."},
                status=status.HTTP_403_FORBIDDEN
            )

        inspection = get_object_or_404(InspectionItem, pk=pk)

        if inspection.status != InspectionItem.STATUS_COMPLETED:
            return Response(
                {"detail": f"Cannot review inspection with status '{inspection.status}'. Only COMPLETED inspections can be reviewed."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = CreateReviewSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        reviewed_class = serializer.validated_data['reviewed_class']
        comment = serializer.validated_data.get('comment', '').strip()

        # Determine if confirmed or corrected compared to immutable original prediction
        review_action = (
            SupervisorReview.ACTION_CONFIRMED
            if reviewed_class == inspection.predicted_class
            else SupervisorReview.ACTION_CORRECTED
        )

        # Create or update separate supervisor review
        review, created = SupervisorReview.objects.update_or_create(
            inspection=inspection,
            defaults={
                'reviewer': user,
                'reviewed_class': reviewed_class,
                'review_action': review_action,
                'comment': comment,
                'reviewed_at': timezone.now(),
            }
        )

        return Response(
            {
                "detail": f"Inspection {review_action.lower()} successfully.",
                "inspection_id": str(inspection.id),
                "review": SupervisorReviewSerializer(review).data,
            },
            status=status.HTTP_200_OK if not created else status.HTTP_201_CREATED
        )


class SingleInspectionAPIView(views.APIView):
    """
    API for uploading and running a single image inspection.
    Validates file before calling AI model.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        product_id = request.data.get('product')
        image_file = request.FILES.get('image')

        if not product_id:
            return Response({"error": "Product ID is required."}, status=status.HTTP_400_BAD_REQUEST)

        product = get_object_or_404(Product, product_id=product_id, is_active=True)

        if not image_file:
            return Response({"error": "No image file provided."}, status=status.HTTP_400_BAD_REQUEST)

        # Validate image file content, size, and dimensions
        is_valid, error_msg, metadata = validate_image_file(image_file)

        # Create record immediately to persist the attempt
        inspection = InspectionItem.objects.create(
            user=request.user,
            product=product,
            image=image_file,
            original_filename=image_file.name,
            file_size_bytes=image_file.size,
            status=InspectionItem.STATUS_QUEUED,
        )

        if not is_valid:
            inspection.status = InspectionItem.STATUS_FAILED
            inspection.failure_reason = error_msg
            inspection.save()
            return Response(
                {
                    "error": error_msg,
                    "status": "FAILED",
                    "inspection_id": str(inspection.id),
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validation passed: update metadata and execute inference
        inspection.status = InspectionItem.STATUS_PROCESSING
        inspection.image_width = metadata['width']
        inspection.image_height = metadata['height']
        inspection.image_format = metadata['format']
        inspection.save()

        try:
            result = run_inspection_model(inspection.image.path)
            inspection.predicted_class = result['predicted_class']
            inspection.confidence = result['confidence']
            inspection.defect_probability = result['defect_probability']
            inspection.model_version = result['model_version']
            inspection.status = InspectionItem.STATUS_COMPLETED
            inspection.completed_at = timezone.now()
            inspection.failure_reason = ""
            inspection.save()

            return Response(InspectionItemSerializer(inspection).data, status=status.HTTP_201_CREATED)
        except Exception as exc:
            inspection.status = InspectionItem.STATUS_FAILED
            inspection.failure_reason = f"Model execution error: {str(exc)}"
            inspection.save()
            return Response(
                {"error": inspection.failure_reason, "status": "FAILED", "inspection_id": str(inspection.id)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class BatchInspectionAPIView(views.APIView):
    """
    API for uploading a batch of 1 to 10 images.
    Persists batch and items, then dispatches background Celery processing.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        product_id = request.data.get('product')
        files = request.FILES.getlist('images')

        if not product_id:
            return Response({"error": "Product ID is required."}, status=status.HTTP_400_BAD_REQUEST)

        product = get_object_or_404(Product, product_id=product_id, is_active=True)

        is_valid_count, count_error = validate_batch_file_count(files)
        if not is_valid_count:
            return Response({"error": count_error}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
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

        # Dispatch background Celery task (or eager fallback)
        dispatch_status = dispatch_batch_processing(batch)

        return Response(
            {
                "batch_id": str(batch.id),
                "total_items": len(files),
                "dispatch_mode": dispatch_status,
                "message": "Batch queued successfully for background inspection.",
            },
            status=status.HTTP_202_ACCEPTED
        )


class BatchStatusAPIView(views.APIView):
    """
    Polling endpoint for batch processing progress.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, batch_id, *args, **kwargs):
        batch = get_object_or_404(InspectionBatch, id=batch_id)

        # Enforce view permissions
        profile = getattr(request.user, 'profile', None)
        if not (request.user.is_superuser or (profile and (profile.is_supervisor or profile.is_administrator))):
            if batch.user != request.user:
                return Response({"detail": "Forbidden: Access denied to this batch."}, status=status.HTTP_403_FORBIDDEN)

        serializer = InspectionBatchSerializer(batch)
        return Response(serializer.data, status=status.HTTP_200_OK)

