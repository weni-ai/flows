from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "temba.projects"

    def ready(self):
        from . import checks  # noqa: F401
