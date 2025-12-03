from weni.internal.models import Project

from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


def get_or_create_user_by_email(email: str) -> tuple:  # pragma: no cover
    return User.objects.get_or_create(email=email, username=email)


def update_project_config(project_uuid: Project, description: str, user_email=None, language: str = None) -> Project:
    project = Project.objects.get(project_uuid=project_uuid)
    project.config["description"] = description
    fields_to_update = ["config"]

    if language:
        project.language = language
        fields_to_update.append("language")

    if user_email:
        user, _ = get_or_create_user_by_email(user_email)
        project.modified_by = user
        project.modified_on = timezone.now()
        fields_to_update.append("modified_by")
        fields_to_update.append("modified_on")

    project.save(update_fields=fields_to_update)

    return project
