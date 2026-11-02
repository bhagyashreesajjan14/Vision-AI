from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from inspection_app.models import UserProfile, Product, InspectionItem, SupervisorReview


class RolePermissionTests(TestCase):
    """
    Test suite for role-based authorization:
    - Administrator, Engineer, Supervisor enforcement.
    - Engineer review attempts denied with HTTP 403 Forbidden.
    - Supervisor review permitted.
    - History isolation: Engineer sees own only, Supervisor sees all.
    """

    def setUp(self):
        # Create Administrator
        self.admin_user = User.objects.create_user(username='admin_test', password='password123')
        self.admin_user.profile.role = UserProfile.ROLE_ADMINISTRATOR
        self.admin_user.profile.save()
        self.admin_user.refresh_from_db()

        # Create Engineer 1
        self.engineer1 = User.objects.create_user(username='engineer_test1', password='password123')
        self.engineer1.profile.role = UserProfile.ROLE_ENGINEER
        self.engineer1.profile.save()
        self.engineer1.refresh_from_db()

        # Create Engineer 2
        self.engineer2 = User.objects.create_user(username='engineer_test2', password='password123')
        self.engineer2.profile.role = UserProfile.ROLE_ENGINEER
        self.engineer2.profile.save()
        self.engineer2.refresh_from_db()

        # Create Supervisor
        self.supervisor = User.objects.create_user(username='supervisor_test', password='password123')
        self.supervisor.profile.role = UserProfile.ROLE_SUPERVISOR
        self.supervisor.profile.save()
        self.supervisor.refresh_from_db()

        # Create Test Product
        self.product = Product.objects.create(
            product_id='P-PLATE01',
            product_name='Demonstration metal plate',
            is_active=True
        )

        # Create Completed Inspection submitted by Engineer 1
        self.inspection = InspectionItem.objects.create(
            user=self.engineer1,
            product=self.product,
            original_filename='specimen_001.png',
            status=InspectionItem.STATUS_COMPLETED,
            predicted_class='Defective',
            confidence=0.985,
            defect_probability=0.985,
            model_version='BIT-PLATE-CV-1.0'
        )

        # Create Completed Inspection submitted by Engineer 2
        self.inspection_eng2 = InspectionItem.objects.create(
            user=self.engineer2,
            product=self.product,
            original_filename='specimen_002.png',
            status=InspectionItem.STATUS_COMPLETED,
            predicted_class='Normal',
            confidence=0.92,
            defect_probability=0.08,
            model_version='BIT-PLATE-CV-1.0'
        )

    def test_engineer_cannot_review_via_api(self):
        """Engineer attempting to review via API must receive HTTP 403 Forbidden."""
        client = APIClient()
        client.force_authenticate(user=self.engineer1)

        url = f"/api/inspections/{self.inspection.id}/review/"
        data = {'reviewed_class': 'Normal', 'comment': 'Trying to review as engineer'}

        response = client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Only Supervisors", response.data['detail'])

        # Verify no review was created
        self.assertFalse(SupervisorReview.objects.filter(inspection=self.inspection).exists())

    def test_engineer_cannot_review_via_ui_post(self):
        """Engineer attempting to POST review to detail page must receive HTTP 403 Forbidden."""
        client = Client()
        client.login(username='engineer_test1', password='password123')

        url = reverse('inspection_detail', kwargs={'inspection_id': self.inspection.id})
        response = client.post(url, {'reviewed_class': 'Normal', 'comment': 'Engineer attempt'})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(SupervisorReview.objects.filter(inspection=self.inspection).exists())

    def test_supervisor_can_confirm_review_via_api(self):
        """Supervisor can review via API and confirm original prediction."""
        client = APIClient()
        client.force_authenticate(user=self.supervisor)

        url = f"/api/inspections/{self.inspection.id}/review/"
        data = {'reviewed_class': 'Defective', 'comment': 'Scratch confirmed visually'}

        response = client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        review = SupervisorReview.objects.get(inspection=self.inspection)
        self.assertEqual(review.reviewer, self.supervisor)
        self.assertEqual(review.reviewed_class, 'Defective')
        self.assertEqual(review.review_action, 'CONFIRMED')
        self.assertEqual(review.comment, 'Scratch confirmed visually')

    def test_supervisor_can_correct_review_via_api(self):
        """Supervisor can review via API and correct original prediction."""
        client = APIClient()
        client.force_authenticate(user=self.supervisor)

        url = f"/api/inspections/{self.inspection.id}/review/"
        data = {'reviewed_class': 'Normal', 'comment': 'Corrected: Surface texture within tolerances'}

        response = client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        review = SupervisorReview.objects.get(inspection=self.inspection)
        self.assertEqual(review.reviewer, self.supervisor)
        self.assertEqual(review.reviewed_class, 'Normal')
        self.assertEqual(review.review_action, 'CORRECTED')

        # Critical: Verify original prediction remains immutable!
        self.inspection.refresh_from_db()
        self.assertEqual(self.inspection.predicted_class, 'Defective')
        self.assertEqual(self.inspection.confidence, 0.985)

    def test_product_management_admin_only(self):
        """Only Administrator can access product management; Engineer gets 403."""
        client = Client()

        # Engineer access blocked
        client.login(username='engineer_test1', password='password123')
        resp = client.get(reverse('products'))
        self.assertEqual(resp.status_code, 403)

        # Admin access permitted
        client.login(username='admin_test', password='password123')
        resp = client.get(reverse('products'))
        self.assertEqual(resp.status_code, 200)

    def test_history_isolation_engineer_vs_supervisor(self):
        """Engineer sees only their own inspections in API; Supervisor sees all."""
        client = APIClient()

        # Engineer 1 sees only self.inspection
        client.force_authenticate(user=self.engineer1)
        resp1 = client.get('/api/inspections/')
        self.assertEqual(resp1.status_code, 200)
        ids1 = [item['id'] for item in resp1.data]
        self.assertIn(str(self.inspection.id), ids1)
        self.assertNotIn(str(self.inspection_eng2.id), ids1)

        # Supervisor sees both inspections
        client.force_authenticate(user=self.supervisor)
        resp_sup = client.get('/api/inspections/')
        self.assertEqual(resp_sup.status_code, 200)
        ids_sup = [item['id'] for item in resp_sup.data]
        self.assertIn(str(self.inspection.id), ids_sup)
        self.assertIn(str(self.inspection_eng2.id), ids_sup)
