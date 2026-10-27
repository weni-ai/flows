import logging
from typing import Optional

from django.contrib.auth import get_user_model
from django.utils import timezone

from temba.orgs.models import Org

User = get_user_model()

logger = logging.getLogger(__name__)


def get_or_create_user_by_email(email: str) -> tuple:  # pragma: no cover
    """Get or create a user by email."""
    # We lookup by email only because the existing user might have a different username.
    user = User.objects.filter(email=email).first()
    if user:
        return user, False
    return User.objects.get_or_create(email=email, defaults={"username": email})


def update_project_status(project_uuid: str, status: str, user_email: str) -> Optional[Org]:
    """
    Update project (Org) suspension status based on the received status.

    Status mapping:
    - ACTIVE: Sets is_suspended to False
    - IN_TEST: Sets is_suspended to False
    - INACTIVE: Sets is_suspended to True

    Args:
        project_uuid: UUID of the project (stored in Org.proj_uuid)
        status: Status to set ('ACTIVE', 'IN_TEST', or 'INACTIVE')
        user_email: Email of the user performing the update

    Returns:
        The updated Org object, or None if not found
    """
    try:
        org = Org.objects.get(proj_uuid=project_uuid)
    except Org.DoesNotExist:
        logger.warning(f"Project with uuid {project_uuid} not found for status update")
        return None

    user, _ = get_or_create_user_by_email(user_email)

    # Map status to is_suspended field (is_active is reserved for org release/deletion)
    status_mapping = {
        "ACTIVE": False,
        "IN_TEST": False,
        "INACTIVE": True,
    }

    if status not in status_mapping:
        raise ValueError(f"Invalid status: {status}. Must be one of: ACTIVE, IN_TEST, INACTIVE")

    new_is_suspended = status_mapping[status]

    # Only update if the status is different
    if org.is_suspended != new_is_suspended:
        org.is_suspended = new_is_suspended
        org.modified_by = user
        org.modified_on = timezone.now()
        org.save(update_fields=["is_suspended", "modified_by", "modified_on"])

        logger.info(
            f"Project '{org.name}' ({project_uuid}) status updated to {status} "
            f"(is_suspended={new_is_suspended}) by {user_email}"
        )
    else:
        logger.info(
            f"Project '{org.name}' ({project_uuid}) already has status {status} "
            f"(is_suspended={new_is_suspended}), no update needed"
        )

    return org
