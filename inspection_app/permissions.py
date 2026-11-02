"""
Role-based permission classes and decorators for Visual Quality Inspection.
Enforces roles on the backend for both DRF API endpoints and standard Django views.
"""

from rest_framework import permissions
from django.core.exceptions import PermissionDenied
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


# -------------------------------------------------------------------------
# DRF Permission Classes
# -------------------------------------------------------------------------

class IsAdministratorUser(permissions.BasePermission):
    """
    Allows access only to Administrators (or superusers).
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return (
            request.user.is_superuser or
            (hasattr(request.user, 'profile') and request.user.profile.is_administrator)
        )


class IsSupervisorUser(permissions.BasePermission):
    """
    Allows access only to Supervisors.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return (
            hasattr(request.user, 'profile') and request.user.profile.is_supervisor
        )


class IsEngineerUser(permissions.BasePermission):
    """
    Allows access to Engineers.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return (
            hasattr(request.user, 'profile') and request.user.profile.is_engineer
        )


class IsInspectionOwnerOrSupervisor(permissions.BasePermission):
    """
    Allows Engineers to view only their own inspections.
    Supervisors can view all inspections.
    Administrators have administrative view access.
    """
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        profile = getattr(request.user, 'profile', None)
        if profile and (profile.is_supervisor or profile.is_administrator):
            return True
        if request.user.is_superuser:
            return True
        return obj.user == request.user


# -------------------------------------------------------------------------
# View Decorators for Django Template Views
# -------------------------------------------------------------------------

def role_required(*allowed_roles):
    """
    Decorator for views that checks whether a user has one of the allowed roles.
    Raises PermissionDenied (HTTP 403) if authenticated but not authorized.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            profile = getattr(request.user, 'profile', None)
            user_role = profile.role if profile else None
            # Allow superuser as administrator
            if request.user.is_superuser and 'ADMINISTRATOR' in allowed_roles:
                return view_func(request, *args, **kwargs)
            if user_role not in allowed_roles:
                raise PermissionDenied("You do not have permission to access this resource.")
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


def supervisor_required(view_func):
    return role_required('SUPERVISOR')(view_func)


def administrator_required(view_func):
    return role_required('ADMINISTRATOR')(view_func)


def engineer_or_supervisor_required(view_func):
    return role_required('ENGINEER', 'SUPERVISOR', 'ADMINISTRATOR')(view_func)

