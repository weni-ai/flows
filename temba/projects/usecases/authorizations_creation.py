from weni.internal.models import Project

from django.contrib.auth import get_user_model

from temba.projects.usecases.exceptions import InvalidProjectData

User = get_user_model()


def get_or_create_user_by_email(email: str) -> tuple:
        return User.objects.get_or_create(email=email)


def create_authorizations(authorizations: dict, project: Project):
    for authorization in authorizations:
        user, _ = get_or_create_user_by_email(authorization.get("user_email"))
        if authorization.get("role") == 1:
            project.viewers.add(user)
        if authorization.get("role") == 2:
            project.editors.add(user)
        if authorization.get("role") == 3 or authorization.get("role") == 4:
            project.administrators.add(user)
        if authorization.get("role") == 5:
            project.agents.add(user)

    project.save()
