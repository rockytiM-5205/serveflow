from django.apps import AppConfig


class PlatformAdminConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.platform_admin"
    label = "platform_admin"
    verbose_name = "Platform administration"

    def ready(self):
        from . import signals  # noqa: F401 - registers the signal handlers
