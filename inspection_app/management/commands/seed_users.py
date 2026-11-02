from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from inspection_app.models import UserProfile


class Command(BaseCommand):
    help = "Seeds default demo users for all three roles: Administrator, Engineer, Supervisor"

    def handle(self, *args, **options):
        users_data = [
            {
                'username': 'admin',
                'email': 'admin@visualinspection.local',
                'password': 'adminpassword123',
                'role': UserProfile.ROLE_ADMINISTRATOR,
                'is_staff': True,
                'is_superuser': True,
            },
            {
                'username': 'engineer',
                'email': 'engineer@visualinspection.local',
                'password': 'engineerpassword123',
                'role': UserProfile.ROLE_ENGINEER,
                'is_staff': False,
                'is_superuser': False,
            },
            {
                'username': 'engineer2',
                'email': 'engineer2@visualinspection.local',
                'password': 'engineer2password123',
                'role': UserProfile.ROLE_ENGINEER,
                'is_staff': False,
                'is_superuser': False,
            },
            {
                'username': 'supervisor',
                'email': 'supervisor@visualinspection.local',
                'password': 'supervisorpassword123',
                'role': UserProfile.ROLE_SUPERVISOR,
                'is_staff': False,
                'is_superuser': False,
            },
        ]

        for u_data in users_data:
            user, created = User.objects.get_or_create(
                username=u_data['username'],
                defaults={
                    'email': u_data['email'],
                    'is_staff': u_data['is_staff'],
                    'is_superuser': u_data['is_superuser'],
                }
            )
            user.set_password(u_data['password'])
            user.is_staff = u_data['is_staff']
            user.is_superuser = u_data['is_superuser']
            user.save()

            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = u_data['role']
            profile.save()

            action = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"{action} user: {user.username} with role: {profile.get_role_display()}"))

