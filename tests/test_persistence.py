import os
from pathlib import Path
from django.test import TestCase
from django.contrib.auth.models import User
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

from inspection_app.models import UserProfile, Product, InspectionItem, SupervisorReview
from inspection_app.validators import validate_image_file
from inspection_app.ai_service import run_inspection_model


class InspectionPersistenceTests(TestCase):
    """
    Test suite for persistence and model immutability:
    - Products, predictions, confidence, model version, timestamps, submitting users.
    - Separate storage of supervisor reviews.
    - Preserved original predictions across reviews and page refreshes.
    - Failed attempts persisted with readable reason.
    """

    def setUp(self):
        self.user = User.objects.create_user(username='persist_eng', password='password123')
        self.supervisor = User.objects.create_user(username='persist_sup', password='password123')
        self.sup_profile = UserProfile.objects.get_or_create(
            user=self.supervisor, defaults={'role': UserProfile.ROLE_SUPERVISOR}
        )[0]
        self.sup_profile.role = UserProfile.ROLE_SUPERVISOR
        self.sup_profile.save()

        self.product = Product.objects.create(
            product_id='P-PLATE01',
            product_name='Demonstration metal plate',
            description='Test plate'
        )

    def test_inspection_record_persistence(self):
        """Inspection item persists full AI metadata and timestamps."""
        item = InspectionItem.objects.create(
            user=self.user,
            product=self.product,
            original_filename='test_image.png',
            status=InspectionItem.STATUS_COMPLETED,
            predicted_class='Defective',
            confidence=0.9912,
            defect_probability=0.9912,
            model_version='BIT-PLATE-CV-1.0',
            image_width=256,
            image_height=256,
            image_format='PNG',
            file_size_bytes=10240,
        )

        item_id = item.id

        # Reload fresh from database
        reloaded = InspectionItem.objects.get(id=item_id)
        self.assertEqual(reloaded.product.product_id, 'P-PLATE01')
        self.assertEqual(reloaded.user.username, 'persist_eng')
        self.assertEqual(reloaded.predicted_class, 'Defective')
        self.assertAlmostEqual(reloaded.confidence, 0.9912, places=4)
        self.assertAlmostEqual(reloaded.defect_probability, 0.9912, places=4)
        self.assertEqual(reloaded.model_version, 'BIT-PLATE-CV-1.0')
        self.assertEqual(reloaded.image_width, 256)
        self.assertEqual(reloaded.image_height, 256)
        self.assertIsNotNone(reloaded.created_at)

    def test_supervisor_review_stored_separately_and_original_immutable(self):
        """Supervisor review is stored separately and does not mutate original AI outputs."""
        item = InspectionItem.objects.create(
            user=self.user,
            product=self.product,
            original_filename='specimen_003.jpg',
            status=InspectionItem.STATUS_COMPLETED,
            predicted_class='Normal',
            confidence=0.887,
            defect_probability=0.113,
            model_version='BIT-PLATE-CV-1.0',
        )

        # Supervisor corrects prediction to Defective
        review = SupervisorReview.objects.create(
            inspection=item,
            reviewer=self.supervisor,
            reviewed_class='Defective',
            review_action=SupervisorReview.ACTION_CORRECTED,
            comment='Superficial hairline pit spotted under diagonal angle.'
        )

        # Reload both from DB
        item.refresh_from_db()
        review.refresh_from_db()

        # Check separate review fields
        self.assertEqual(review.reviewer.username, 'persist_sup')
        self.assertEqual(review.reviewed_class, 'Defective')
        self.assertEqual(review.review_action, 'CORRECTED')
        self.assertIn("hairline pit", review.comment)
        self.assertIsNotNone(review.reviewed_at)

        # Check original prediction remained completely UNCHANGED
        self.assertEqual(item.predicted_class, 'Normal')
        self.assertAlmostEqual(item.confidence, 0.887, places=3)
        self.assertAlmostEqual(item.defect_probability, 0.113, places=3)
        self.assertEqual(item.model_version, 'BIT-PLATE-CV-1.0')

    def test_failed_attempt_persistence_without_model_call(self):
        """Invalid file attempt persists as status='FAILED' with reason, no prediction."""
        item = InspectionItem.objects.create(
            user=self.user,
            product=self.product,
            original_filename='corrupt_data.png',
            status=InspectionItem.STATUS_FAILED,
            failure_reason='Corrupted or unrecognizable image content.',
            file_size_bytes=30,
        )

        reloaded = InspectionItem.objects.get(id=item.id)
        self.assertEqual(reloaded.status, 'FAILED')
        self.assertIn("Corrupted or unrecognizable", reloaded.failure_reason)
        self.assertIsNone(reloaded.predicted_class)
        self.assertIsNone(reloaded.confidence)
        self.assertIsNone(reloaded.defect_probability)
        self.assertIsNone(reloaded.model_version)

