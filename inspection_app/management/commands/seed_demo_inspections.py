import os
from pathlib import Path
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.core.files import File
from django.contrib.auth.models import User
from django.utils import timezone
from django.conf import settings
from inspection_app.models import Product, InspectionBatch, InspectionItem, SupervisorReview, UserProfile
from inspection_app.ai_service import run_inspection_model
from PIL import Image


class Command(BaseCommand):
    help = "Seeds realistic demo inspections, batches, and supervisor reviews using real sample images and model inference"

    def add_arguments(self, parser):
        parser.add_argument(
            '--clean',
            action='store_true',
            help='Clear existing inspections and batches before seeding',
        )

    def handle(self, *args, **options):
        if options['clean']:
            self.stdout.write("Cleaning existing inspections, reviews, and batches...")
            SupervisorReview.objects.all().delete()
            InspectionItem.objects.all().delete()
            InspectionBatch.objects.all().delete()

        # Ensure product P-PLATE01 exists
        product, _ = Product.objects.get_or_create(
            product_id='P-PLATE01',
            defaults={
                'product_name': 'Demonstration metal plate',
                'description': 'Flat metal plate specimen with potential surface scratch or pit defects.',
                'is_active': True,
            }
        )

        # Ensure second product for multi-product insights exists
        product2, _ = Product.objects.get_or_create(
            product_id='P-BRKT02',
            defaults={
                'product_name': 'Precision Machined Bracket',
                'description': 'Machined structural bracket inspected for surface anomalies.',
                'is_active': True,
            }
        )

        # Ensure users exist
        engineer = User.objects.filter(username='engineer').first()
        engineer2 = User.objects.filter(username='engineer2').first()
        supervisor = User.objects.filter(username='supervisor').first()

        if not engineer or not supervisor:
            self.stdout.write("Default users missing. Please run `python manage.py seed_users` first.")
            return

        samples_dir = Path(settings.BASE_DIR) / 'Samples' / 'images'
        if not samples_dir.exists():
            self.stdout.write(self.style.ERROR(f"Samples directory not found: {samples_dir}"))
            return

        sample_files = sorted(list(samples_dir.glob('*.*')))[:24]
        if not sample_files:
            self.stdout.write(self.style.ERROR("No sample files found in Samples/images"))
            return

        now = timezone.now()
        created_items = []

        # 1. Create a 6-item batch for engineer (e.g. 2 days ago)
        batch_files = sample_files[:6]
        batch_created_at = now - timedelta(days=2, hours=4)
        batch = InspectionBatch.objects.create(
            user=engineer,
            product=product,
            total_items=len(batch_files),
        )
        # Update timestamp
        InspectionBatch.objects.filter(id=batch.id).update(created_at=batch_created_at, updated_at=batch_created_at + timedelta(seconds=2))

        for idx, fpath in enumerate(batch_files):
            with Image.open(fpath) as img:
                w, h = img.size
                fmt = img.format
            file_size = os.path.getsize(fpath)

            pred = run_inspection_model(fpath)
            item_comp_time = batch_created_at + timedelta(seconds=1 + idx * 0.3)

            with open(fpath, 'rb') as f:
                item = InspectionItem(
                    batch=batch,
                    user=engineer,
                    product=product,
                    original_filename=fpath.name,
                    file_size_bytes=file_size,
                    image_width=w,
                    image_height=h,
                    image_format=fmt,
                    status=InspectionItem.STATUS_COMPLETED,
                    predicted_class=pred['predicted_class'],
                    confidence=pred['confidence'],
                    defect_probability=pred['defect_probability'],
                    model_version=pred['model_version'],
                    completed_at=item_comp_time,
                )
                item.image.save(fpath.name, File(f), save=False)
                item.save()

            InspectionItem.objects.filter(id=item.id).update(created_at=batch_created_at, completed_at=item_comp_time)
            created_items.append((item, batch_created_at))

        self.stdout.write(self.style.SUCCESS(f"Seeded Batch {batch.id} with {len(batch_files)} items."))

        # 2. Create single inspections across the last 4 days by engineer and engineer2
        day_offsets = [4, 3, 3, 2, 1, 1, 0, 0]
        remaining_files = sample_files[6:14]

        for idx, fpath in enumerate(remaining_files):
            day_offset = day_offsets[idx % len(day_offsets)]
            sub_user = engineer2 if (engineer2 and idx % 2 == 1) else engineer
            sub_prod = product2 if idx % 4 == 0 else product
            sub_time = now - timedelta(days=day_offset, hours=(idx * 2) % 12, minutes=idx * 7)

            with Image.open(fpath) as img:
                w, h = img.size
                fmt = img.format
            file_size = os.path.getsize(fpath)

            pred = run_inspection_model(fpath)
            item_comp_time = sub_time + timedelta(seconds=1.2)

            with open(fpath, 'rb') as f:
                item = InspectionItem(
                    user=sub_user,
                    product=sub_prod,
                    original_filename=fpath.name,
                    file_size_bytes=file_size,
                    image_width=w,
                    image_height=h,
                    image_format=fmt,
                    status=InspectionItem.STATUS_COMPLETED,
                    predicted_class=pred['predicted_class'],
                    confidence=pred['confidence'],
                    defect_probability=pred['defect_probability'],
                    model_version=pred['model_version'],
                    completed_at=item_comp_time,
                )
                item.image.save(fpath.name, File(f), save=False)
                item.save()

            InspectionItem.objects.filter(id=item.id).update(created_at=sub_time, completed_at=item_comp_time)
            created_items.append((item, sub_time))

        self.stdout.write(self.style.SUCCESS(f"Seeded {len(remaining_files)} individual inspections."))

        # 3. Create Supervisor Reviews (demonstrating agreement & disagreement)
        # We review 8 of the completed items
        review_targets = created_items[:8]
        review_count = 0

        for idx, (item, sub_time) in enumerate(review_targets):
            review_time = sub_time + timedelta(hours=2, minutes=15)
            # Create mostly CONFIRMED (high agreement) and 1-2 realistic CORRECTED overrides
            if idx == 4 and item.predicted_class == 'Normal':
                # Supervisor overrides Normal to Defective (caught subtle hairline scratch)
                rev_class = 'Defective'
                action = SupervisorReview.ACTION_CORRECTED
                comment = "Hairline surface scratch identified near plate mounting edge during visual audit."
            elif idx == 6 and item.predicted_class == 'Defective':
                # Supervisor overrides Defective to Normal (classified acceptable factory surface grain)
                rev_class = 'Normal'
                action = SupervisorReview.ACTION_CORRECTED
                comment = "Surface variance within tolerance for standard finish. Approved as Normal."
            else:
                rev_class = item.predicted_class
                action = SupervisorReview.ACTION_CONFIRMED
                comment = f"Verified by quality supervisor. AI {item.predicted_class} classification confirmed."

            review, _ = SupervisorReview.objects.update_or_create(
                inspection=item,
                defaults={
                    'reviewer': supervisor,
                    'reviewed_class': rev_class,
                    'review_action': action,
                    'comment': comment,
                }
            )
            SupervisorReview.objects.filter(id=review.id).update(reviewed_at=review_time)
            review_count += 1

        self.stdout.write(self.style.SUCCESS(f"Seeded {review_count} supervisor reviews (including confirmations and corrections)."))
        self.stdout.write(self.style.SUCCESS("All demo inspection data seeded successfully with authentic model inference!"))

