from rest_framework.exceptions import ValidationError
from weni.internal.models import Project

from django.contrib.auth.models import User
from django.utils import timezone

# User = get_user_model()


def get_or_create_user_by_email(email: str) -> tuple:  # pragma: no cover
    print("ENTRA AQUI")
    print(email)
    return User.objects.get_or_create(email=email, username=email)


def create_user_permission(role: int, project: Project, user: User):
    if role == 1:
        project.viewers.add(user)
    if role == 2:
        project.editors.add(user)
    if role == 3 or role == 4:
        project.administrators.add(user)
    if role == 5:
        project.agents.add(user)

    project.save()


def get_name_permisssions(role: int):
    if role == 1:
        return "viewer"
    if role == 2:
        return "editor"
    if role == 3 or role == 4:
        return "administrator"
    if role == 5:
        return "agent"


def update_permission(project_uuid: Project, action: str, user_email: str, role: int) -> Project:
    project = Project.objects.get(project_uuid=project_uuid)
    user, _ = get_or_create_user_by_email(user_email)

    if action == "create":
        create_user_permission(role, project, user)

    if action == "update":
        _validate_permission(project, get_name_permisssions(role))
        _set_user_permission(project, user, get_name_permisssions(role))

    if action == "delete":
        _validate_permission(project, get_name_permisssions(role))
        _remove_user_permission(project, user, get_name_permisssions(role))

    project.modified_by = user
    project.modified_on = timezone.now()
    project.save(update_fields=["modified_by", "modified_on"])

    return project


def _remove_user_permission(project: Project, user: User, permission: str):
    permissions = _get_permissions(project)
    permissions.get(permission).remove(user)
    project.save()


def _set_user_permission(project: Project, user: User, permission: str):
    permissions = _get_permissions(project)

    for perm_name, org_field in permissions.items():
        if not perm_name == permission:
            org_field.remove(user)

    permissions.get(permission).add(user)
    project.save()


def _validate_permission(project: Project, permission: str):
    permissions_keys = _get_permissions(project).keys()
    if permission not in permissions_keys:
        raise ValidationError(detail=f"{permission} is not a valid permission!")


def _get_permissions(project: Project) -> dict:
    return {
        "administrator": project.administrators,
        "viewer": project.viewers,
        "editor": project.editors,
        "surveyor": project.surveyors,
        "agent": project.agents,
    }


def _get_user_permissions(project: Project, user: User) -> dict:
    permissions = {}
    org_permissions = _get_permissions(project)

    for perm_name, org_field in org_permissions.items():
        if org_field.filter(pk=user.id).exists():
            permissions[perm_name] = True

    return permissions
