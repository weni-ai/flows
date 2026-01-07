import logging
from typing import Optional

from django.contrib.auth import get_user_model

from temba.orgs.models import Org

User = get_user_model()

logger = logging.getLogger(__name__)


def get_or_create_user_by_email(email: str) -> tuple:
    """Get or create a user by email."""
    # We lookup by email only because the existing user might have a different username.
    user = User.objects.filter(email=email).first()
    if user:
        return user, False
    return User.objects.get_or_create(email=email, defaults={"username": email})


def delete_project(project_uuid: str, user_email: str) -> Optional[Org]:
    """
    Delete (release) a project/org.

    This function performs a soft delete by calling org.release() which:
    - Sets is_active to False
    - Sets released_on timestamp
    - Releases all channels
    - Removes all org users

    Args:
        project_uuid: UUID of the project to delete
        user_email: Email of the user performing the deletion

    Returns:
        The released Org object, or None if not found
    """
    try:
        org = Org.objects.get(proj_uuid=project_uuid)
    except Org.DoesNotExist:
        logger.warning(f"Project with uuid {project_uuid} not found for deletion")
        return None

    user, _ = get_or_create_user_by_email(user_email)

    org.release(user)

    logger.info(f"Project '{org.name}' ({project_uuid}) released by {user_email}")

    return org
