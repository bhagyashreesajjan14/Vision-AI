import os
import shutil
from pathlib import Path
from django.test import TestCase
from django.contrib.auth.models import User
from django.conf import settings
from django.core.files import File

from inspection_app.models import Product, InspectionBatch, InspectionItem
from inspection_app.tasks import process_inspection_batch


class BatchProcessingTests(TestCase):
    """
    Test suite for batch processing:
    - Background task execution.
    - Fault-tolerant processing: invalid files must not stop valid files.
    - Correct status transitions (QUEUED -> PROCESSING -> COMPLETED / FAILED).
    - Readable failure reasons.
    """

    def setUp(self):
        self.user = User.objects.create_user(username='batch_eng', password='password123')
        self.product = Product.objects.create(
            product_id='P-PLATE01',
            product_name='Demonstration metal plate',
            is_active=True
        )

        self.samples_dir = Path(settings.BASE_DIR) / 'Samples' / 'images'
        self.val_dir = Path(settings.BASE_DIR) / 'Validation'

    def test_mixed_batch_fault_tolerance(self):
        """
        A mixed batch containing:
        1. inspection_001.png (Valid Defective specimen)
        2. corrupt_image.png (Invalid corrupt file)
        3. inspection_002.jpg (Valid Normal specimen)
        4. too_small.png (Invalid dimension < 64px)

        Both valid files must complete successfully.
        Both invalid files must fail with readable reasons.
        Invalid files must NOT stop valid files.
        """
        batch = InspectionBatch.objects.create(
            user=self.user,
            product=self.product,
            total_items=4
        )

        # 1. Valid Defective
        valid_file1 = self.samples_dir / 'inspection_001.png'
        item1 = InspectionItem.objects.create(
            batch=batch,
            user=self.user,
            product=self.product,
            original_filename='inspection_001.png',
            status=InspectionItem.STATUS_QUEUED,
        )
        with open(valid_file1, 'rb') as f:
            item1.image.save('batch_test_001.png', File(f), save=True)

        # 2. Corrupt file
        corrupt_file = self.val_dir / 'corrupt_image.png'
        item2 = InspectionItem.objects.create(
            batch=batch,
            user=self.user,
            product=self.product,
            original_filename='corrupt_image.png',
            status=InspectionItem.STATUS_QUEUED,
        )
        with open(corrupt_file, 'rb') as f:
            item2.image.save('batch_corrupt.png', File(f), save=True)

        # 3. Valid Normal
        valid_file2 = self.samples_dir / 'inspection_002.jpg'
        item3 = InspectionItem.objects.create(
            batch=batch,
            user=self.user,
            product=self.product,
            original_filename='inspection_002.jpg',
            status=InspectionItem.STATUS_QUEUED,
        )
        with open(valid_file2, 'rb') as f:
            item3.image.save('batch_test_002.jpg', File(f), save=True)

        # 4. Too small file
        small_file = self.val_dir / 'too_small.png'
        item4 = InspectionItem.objects.create(
            batch=batch,
            user=self.user,
            product=self.product,
            original_filename='too_small.png',
            status=InspectionItem.STATUS_QUEUED,
        )
        with open(small_file, 'rb') as f:
            item4.image.save('batch_too_small.png', File(f), save=True)

        # Execute the batch processing task
        success = process_inspection_batch(str(batch.id))
        self.assertTrue(success)

        # Refresh all items from DB
        item1.refresh_from_db()
        item2.refresh_from_db()
        item3.refresh_from_db()
        item4.refresh_from_db()

        # Item 1: Must be COMPLETED and Defective
        self.assertEqual(item1.status, InspectionItem.STATUS_COMPLETED)
        self.assertEqual(item1.predicted_class, 'Defective')
        self.assertAlmostEqual(item1.confidence, 1.0, places=3)
        self.assertEqual(item1.model_version, 'BIT-PLATE-CV-1.0')

        # Item 2: Must be FAILED with corrupt reason
        self.assertEqual(item2.status, InspectionItem.STATUS_FAILED)
        self.assertIn("Corrupted or unrecognizable", item2.failure_reason)
        self.assertIsNone(item2.predicted_class)

        # Item 3: Must be COMPLETED and Normal
        self.assertEqual(item3.status, InspectionItem.STATUS_COMPLETED)
        self.assertEqual(item3.predicted_class, 'Normal')
        self.assertEqual(item3.model_version, 'BIT-PLATE-CV-1.0')

        # Item 4: Must be FAILED with dimension reason
        self.assertEqual(item4.status, InspectionItem.STATUS_FAILED)
        self.assertIn("outside the allowed range", item4.failure_reason)
        self.assertIsNone(item4.predicted_class)

        # Batch counts verification
        self.assertEqual(batch.completed_count, 2)
        self.assertEqual(batch.failed_count, 2)
        self.assertTrue(batch.is_finished)

