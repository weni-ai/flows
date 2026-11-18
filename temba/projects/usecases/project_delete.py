import logging
from typing import Optional

from django.contrib.auth import get_user_model
from django.db import transaction

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

    An org that is already released is returned unchanged, so a repeated deletion does not move released_on.

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

    if not org.is_active:
        logger.info("project_already_released project_uuid=%s org_id=%s", project_uuid, org.id)
        return org

    user, _ = get_or_create_user_by_email(user_email)

    # Org.release deactivates the org before releasing its channels, and a redelivery of an inactive org is skipped,
    # so a failure part way through must leave the org active.
    with transaction.atomic():
        org.release(user)

    logger.info("project_released project_uuid=%s org_id=%s", project_uuid, org.id)

    return org
