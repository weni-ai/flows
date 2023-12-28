from weni.internal.models import Project

from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


def get_or_create_user_by_email(email: str) -> tuple:  # pragma: no cover
    return User.objects.get_or_create(email=email, username=email)


def update_project_config(project_uuid: Project, description: str, user_email=None) -> Project:
    project = Project.objects.get(project_uuid=project_uuid)
    project.config["description"] = description
    if user_email:
        user, _ = get_or_create_user_by_email(user_email)
        project.modified_by = user
        project.modified_on = timezone.now()
        project.save(update_fields=["config", "modified_by", "modified_on"])

        return project

    project.save(update_fields=["config"])

    return project
