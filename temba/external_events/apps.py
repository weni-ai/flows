from django.apps import AppConfig


class ExternalEventsConfig(AppConfig):
    name = "temba.external_events"
    verbose_name = "External Events"
    default_auto_field = "django.db.models.BigAutoField" 