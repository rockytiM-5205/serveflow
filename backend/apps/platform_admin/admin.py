from django.contrib import admin

from . import services
from .models import ApiCredential, ApiUsageDaily, Plan, PlatformAuditEvent, PlatformNotification, RateLimitEvent, Subscription, SubscriptionPayment


class ReadOnlyAdmin(admin.ModelAdmin):
    """Records the owner API manages or that must never be edited by hand."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Plan)
class PlanAdmin(ReadOnlyAdmin):  # create and edit plans in the Owner Control Centre so they are audited
    list_display = ("name", "interval", "price", "currency", "status")


@admin.register(Subscription)
class SubscriptionAdmin(ReadOnlyAdmin):  # started with `manage.py start_trial`, moved by payments and `sync_subscriptions`
    list_display = ("restaurant", "plan", "status", "current_period_end")
    list_filter = ("status",)


@admin.register(ApiCredential)
class ApiCredentialAdmin(ReadOnlyAdmin):  # secrets are generated through the owner API only
    list_display = ("prefix", "restaurant", "environment", "status", "last_used_at")
    exclude = ("secret_hash",)


@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(admin.ModelAdmin):
    """Record a bank transfer a restaurant reports. It starts as AWAITING_CONFIRMATION; confirming it is an owner-API action."""

    list_display = ("reference", "subscription", "amount", "currency", "status", "transacted_at")
    list_filter = ("status",)
    search_fields = ("reference",)

    def get_fields(self, request, obj=None):
        return None if obj else ("subscription", "reference", "amount", "currency", "transacted_at")

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields] if obj else []

    def has_change_permission(self, request, obj=None):
        return obj is None

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.status = SubscriptionPayment.Status.AWAITING_CONFIRMATION
        super().save_model(request, obj, form, change)
        services.audit(request.user, "payment.recorded", "payment", obj.pk, obj.reference)


@admin.register(ApiUsageDaily)
class ApiUsageDailyAdmin(ReadOnlyAdmin):
    list_display = ("date", "restaurant", "method", "path", "requests", "errors")


@admin.register(RateLimitEvent)
class RateLimitEventAdmin(ReadOnlyAdmin):
    list_display = ("occurred_at", "restaurant", "endpoint", "limit")


@admin.register(PlatformAuditEvent)
class PlatformAuditEventAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "actor", "action", "resource_type", "resource_id", "summary")
    list_filter = ("action",)


@admin.register(PlatformNotification)
class PlatformNotificationAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "kind", "title", "read_at")
    list_filter = ("kind",)
