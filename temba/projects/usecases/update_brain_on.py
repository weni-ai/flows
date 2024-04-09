from weni.internal.models import Project

from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


def get_or_create_user_by_email(email: str) -> tuple:  # pragma: no cover
    return User.objects.get_or_create(email=email, username=email)


def update_project_brain_on(project_uuid: Project, brain_on: bool, user_email=None) -> Project:
    project = Project.objects.get(project_uuid=project_uuid)
    user, _ = get_or_create_user_by_email(user_email)

    project.brain_on = brain_on
    project.modified_by = user
    project.modified_on = timezone.now()
    project.save(update_fields=["brain_on", "modified_by", "modified_on"])

    return project
