from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from inspection_app.models import UserProfile


class SeparateRoleLoginTests(TestCase):
    """
    Test suite verifying separate login pages for each role:
    - Administrator Login (/login/admin/)
    - Engineer Login (/login/engineer/)
    - Supervisor Login (/login/supervisor/)
    - Cross-role login attempts are strictly rejected on the backend.
    - No demo credentials or auto-login shortcuts exist.
    """

    def setUp(self):
        self.client = Client()

        # Admin User
        self.admin = User.objects.create_user(username='admin_auth', password='admin_password_99')
        self.admin.profile.role = UserProfile.ROLE_ADMINISTRATOR
        self.admin.profile.save()
        self.admin.refresh_from_db()

        # Engineer User
        self.engineer = User.objects.create_user(username='engineer_auth', password='eng_password_99')
        self.engineer.profile.role = UserProfile.ROLE_ENGINEER
        self.engineer.profile.save()
        self.engineer.refresh_from_db()

        # Supervisor User
        self.supervisor = User.objects.create_user(username='supervisor_auth', password='sup_password_99')
        self.supervisor.profile.role = UserProfile.ROLE_SUPERVISOR
        self.supervisor.profile.save()
        self.supervisor.refresh_from_db()

    def test_admin_login_success_for_administrator(self):
        """Administrator logs in through Administrator portal successfully."""
        resp = self.client.post(reverse('login_admin'), {
            'username': 'admin_auth',
            'password': 'admin_password_99'
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue('_auth_user_id' in self.client.session)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.admin.id)

    def test_admin_login_rejects_engineer(self):
        """Engineer attempting to log in through Administrator portal is denied."""
        resp = self.client.post(reverse('login_admin'), {
            'username': 'engineer_auth',
            'password': 'eng_password_99'
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "does not have Administrator privileges")
        self.assertFalse('_auth_user_id' in self.client.session)

    def test_admin_login_rejects_supervisor(self):
        """Supervisor attempting to log in through Administrator portal is denied."""
        resp = self.client.post(reverse('login_admin'), {
            'username': 'supervisor_auth',
            'password': 'sup_password_99'
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "does not have Administrator privileges")
        self.assertFalse('_auth_user_id' in self.client.session)

    def test_engineer_login_success_for_engineer(self):
        """Engineer logs in through Engineer portal successfully."""
        resp = self.client.post(reverse('login_engineer'), {
            'username': 'engineer_auth',
            'password': 'eng_password_99'
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue('_auth_user_id' in self.client.session)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.engineer.id)

    def test_engineer_login_rejects_admin(self):
        """Administrator attempting to log in through Engineer portal is denied."""
        resp = self.client.post(reverse('login_engineer'), {
            'username': 'admin_auth',
            'password': 'admin_password_99'
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "does not have Engineer privileges")
        self.assertFalse('_auth_user_id' in self.client.session)

    def test_engineer_login_rejects_supervisor(self):
        """Supervisor attempting to log in through Engineer portal is denied."""
        resp = self.client.post(reverse('login_engineer'), {
            'username': 'supervisor_auth',
            'password': 'sup_password_99'
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "does not have Engineer privileges")
        self.assertFalse('_auth_user_id' in self.client.session)

    def test_supervisor_login_success_for_supervisor(self):
        """Supervisor logs in through Supervisor portal successfully."""
        resp = self.client.post(reverse('login_supervisor'), {
            'username': 'supervisor_auth',
            'password': 'sup_password_99'
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue('_auth_user_id' in self.client.session)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.supervisor.id)

    def test_supervisor_login_rejects_engineer(self):
        """Engineer attempting to log in through Supervisor portal is denied."""
        resp = self.client.post(reverse('login_supervisor'), {
            'username': 'engineer_auth',
            'password': 'eng_password_99'
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "does not have Supervisor privileges")
        self.assertFalse('_auth_user_id' in self.client.session)

    def test_supervisor_login_rejects_admin(self):
        """Administrator attempting to log in through Supervisor portal is denied."""
        resp = self.client.post(reverse('login_supervisor'), {
            'username': 'admin_auth',
            'password': 'admin_password_99'
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "does not have Supervisor privileges")
        self.assertFalse('_auth_user_id' in self.client.session)

    def test_login_pages_contain_no_demo_credentials_or_auto_login(self):
        """Verify that login pages have no quick demo login buttons or hardcoded shortcuts."""
        for url_name in ['login_admin', 'login_engineer', 'login_supervisor', 'login']:
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 200)
            self.assertNotContains(resp, "Quick Demo")
            self.assertNotContains(resp, "fillDemo")
            self.assertNotContains(resp, "adminpassword123")
            self.assertNotContains(resp, "engineerpassword123")
            self.assertNotContains(resp, "supervisorpassword123")

