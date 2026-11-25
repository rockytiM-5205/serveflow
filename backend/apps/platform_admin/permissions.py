from rest_framework.permissions import BasePermission


class IsPlatformOwner(BasePermission):
    """ServeFlow's own administrators: active superusers. Restaurant roles never grant this, and no other
    signal (header, cookie, query parameter) can. Anonymous callers get 401, signed-in non-owners get 403."""

    message = "Platform owner access only."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.is_superuser)
