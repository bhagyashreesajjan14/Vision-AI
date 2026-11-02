from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from inspection_app.models import UserProfile, Product, InspectionBatch, InspectionItem, SupervisorReview
from PIL import Image
from io import BytesIO
import json


class QualityInsightsAndReportsTests(TestCase):
    def setUp(self):
        self.client = Client()

        self.admin_user = User.objects.create_user(username='testadmin', password='password123', is_staff=True, is_superuser=True)
        self.admin_user.profile.role = UserProfile.ROLE_ADMINISTRATOR
        self.admin_user.profile.save()
        self.admin_user.refresh_from_db()

        self.engineer_user = User.objects.create_user(username='testengineer', password='password123')
        self.engineer_user.profile.role = UserProfile.ROLE_ENGINEER
        self.engineer_user.profile.save()
        self.engineer_user.refresh_from_db()

        self.engineer2_user = User.objects.create_user(username='testengineer2', password='password123')
        self.engineer2_user.profile.role = UserProfile.ROLE_ENGINEER
        self.engineer2_user.profile.save()
        self.engineer2_user.refresh_from_db()

        self.supervisor_user = User.objects.create_user(username='testsupervisor', password='password123')
        self.supervisor_user.profile.role = UserProfile.ROLE_SUPERVISOR
        self.supervisor_user.profile.save()
        self.supervisor_user.refresh_from_db()

        self.product = Product.objects.create(
            product_id='P-PLATE01',
            product_name='Demonstration metal plate',
            description='Test plate'
        )

        # Create dummy image
        img = Image.new('RGB', (128, 128), color='gray')
        img_io = BytesIO()
        img.save(img_io, format='PNG')
        self.img_content = img_io.getvalue()

        # Create a batch with 2 items for engineer
        self.batch = InspectionBatch.objects.create(
            user=self.engineer_user,
            product=self.product,
            total_items=2
        )

        self.item1 = InspectionItem.objects.create(
            batch=self.batch,
            user=self.engineer_user,
            product=self.product,
            image=SimpleUploadedFile('test_plate_1.png', self.img_content, content_type='image/png'),
            original_filename='test_plate_1.png',
            status=InspectionItem.STATUS_COMPLETED,
            predicted_class='Normal',
            confidence=0.9850,
            defect_probability=0.0150,
            model_version='BIT-PLATE-CV-1.0',
            completed_at=timezone.now()
        )

        self.item2 = InspectionItem.objects.create(
            batch=self.batch,
            user=self.engineer_user,
            product=self.product,
            image=SimpleUploadedFile('test_plate_2.png', self.img_content, content_type='image/png'),
            original_filename='test_plate_2.png',
            status=InspectionItem.STATUS_COMPLETED,
            predicted_class='Defective',
            confidence=0.9620,
            defect_probability=0.9620,
            model_version='BIT-PLATE-CV-1.0',
            completed_at=timezone.now()
        )

        # Create reviews: item1 confirmed, item2 corrected
        self.review1 = SupervisorReview.objects.create(
            inspection=self.item1,
            reviewer=self.supervisor_user,
            reviewed_class='Normal',
            review_action='CONFIRMED',
            comment='Verified Normal'
        )

        self.review2 = SupervisorReview.objects.create(
            inspection=self.item2,
            reviewer=self.supervisor_user,
            reviewed_class='Normal',
            review_action='CORRECTED',
            comment='Acceptable cosmetic tolerance'
        )

    def test_quality_insights_view_accessible_and_accurate(self):
        """Test Quality Insights dashboard renders and computes accurate statistics."""
        self.client.login(username='testsupervisor', password='password123')
        resp = self.client.get('/insights/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Quality Insights")
        self.assertContains(resp, "AI vs. Supervisor Review Calibration")
        # Agreement rate: 1 confirmed out of 2 reviews = 50.0%
        self.assertContains(resp, "50.0%")
        # Defect rate: 1 defective out of 2 completed = 50.0%
        self.assertContains(resp, "Defect Rate")

    def test_export_batch_csv(self):
        """Test batch CSV export generates valid downloadable CSV."""
        self.client.login(username='testengineer', password='password123')
        resp = self.client.get(f'/batches/{self.batch.id}/export/csv/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv')
        self.assertIn('attachment', resp['Content-Disposition'])
        content = resp.content.decode('utf-8')
        self.assertIn("VISIONINSPECT QUALITY ASSURANCE BATCH REPORT", content)
        self.assertIn(self.batch.batch_tracking_id, content)
        self.assertIn("test_plate_1.png", content)
        self.assertIn("test_plate_2.png", content)
        self.assertIn("CONFIRMED", content)
        self.assertIn("CORRECTED", content)

    def test_export_batch_pdf(self):
        """Test batch PDF export generates valid binary PDF with reportlab, or falls back to print report."""
        self.client.login(username='testengineer', password='password123')
        resp = self.client.get(f'/batches/{self.batch.id}/export/pdf/')
        self.assertEqual(resp.status_code, 200)
        if resp.get('Content-Type') == 'application/pdf':
            self.assertIn('attachment', resp['Content-Disposition'])
            self.assertTrue(resp.content.startswith(b'%PDF-'))
        else:
            self.assertContains(resp, "VisionInspect Quality Assurance Report")

    def test_inspection_traceability_export(self):
        """Test inspection traceability JSON export contains checksum and complete audit data."""
        self.client.login(username='testengineer', password='password123')
        resp = self.client.get(f'/inspections/{self.item1.id}/traceability/')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content.decode('utf-8'))
        self.assertEqual(data['tracking_id'], self.item1.tracking_id)
        self.assertEqual(data['product']['product_id'], 'P-PLATE01')
        self.assertIn('sha256_checksum', data['specimen_provenance'])
        self.assertEqual(data['ai_model_audit']['model_version'], 'BIT-PLATE-CV-1.0')
        self.assertEqual(data['supervisor_audit_custody']['review_action'], 'CONFIRMED')

    def test_unauthorized_user_cannot_export_others_batch(self):
        """Test engineer2 cannot export engineer's batch report (strict RBAC)."""
        self.client.login(username='testengineer2', password='password123')
        resp = self.client.get(f'/batches/{self.batch.id}/export/csv/')
        self.assertEqual(resp.status_code, 403)
        resp_pdf = self.client.get(f'/batches/{self.batch.id}/export/pdf/')
        self.assertEqual(resp_pdf.status_code, 403)
