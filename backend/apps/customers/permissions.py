from rest_framework.permissions import BasePermission


class IsCustomer(BasePermission):
    """Signed in AND a customer account. A restaurant user or the platform owner is not a customer."""

    message = "Sign in with your customer account."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and hasattr(user, "customer_profile"))
