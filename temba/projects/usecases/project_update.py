from django.contrib.auth import get_user_model
from django.utils import timezone

from temba.orgs.models import Org

User = get_user_model()


def get_or_create_user_by_email(email: str) -> tuple:  # pragma: no cover
    return User.objects.get_or_create(email=email, username=email)


def update_project_config(
    project_uuid: str,
    user_email=None,
    name: str = None,
    description: str = None,
    language: str = None,
) -> Org:
    """
    Update project (Org) configuration.
    
    Args:
        project_uuid: UUID of the project (stored in Org.proj_uuid)
        user_email: Email of the user performing the update
        name: New name for the project
        description: New description for the project
        language: New language for the project
    
    Returns:
        The updated Org object
    """
    org = Org.objects.get(proj_uuid=project_uuid)
    fields_to_update = []

    if name is not None and name != org.name:
        org.name = name
        fields_to_update.append("name")

    if description is not None:
        if org.config is None:
            org.config = {}
        org.config["description"] = description
        fields_to_update.append("config")

    if language is not None and language != org.language:
        org.language = language
        fields_to_update.append("language")

    if user_email:
        user, _ = get_or_create_user_by_email(user_email)
        org.modified_by = user
        org.modified_on = timezone.now()
        fields_to_update.append("modified_by")
        fields_to_update.append("modified_on")

    if fields_to_update:
        org.save(update_fields=fields_to_update)

    return org
