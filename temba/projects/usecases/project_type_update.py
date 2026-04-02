import logging
from typing import Optional

from django.contrib.auth import get_user_model
from django.utils import timezone

from temba.orgs.models import Org

User = get_user_model()

logger = logging.getLogger(__name__)


def get_or_create_user_by_email(email: str) -> tuple:  # pragma: no cover
    user = User.objects.filter(email=email).first()
    if user:
        return user, False
    return User.objects.get_or_create(email=email, defaults={"username": email})


def update_project_type(project_uuid: str, is_multi_agent: bool, user_email: str) -> Optional[Org]:
    """
    Update the project (Org) type by setting the is_multi_agent flag in its config.

    Args:
        project_uuid: UUID of the project (stored in Org.proj_uuid)
        is_multi_agent: Whether the project is a multi-agent project
        user_email: Email of the user performing the update

    Returns:
        The updated Org object, or None if not found
    """
    try:
        org = Org.objects.get(proj_uuid=project_uuid)
    except Org.DoesNotExist:
        logger.warning(f"Project with uuid {project_uuid} not found for type update")
        return None

    if org.config is None:
        org.config = {}

    if org.config.get("is_multi_agent") == is_multi_agent:
        logger.info(
            f"Project '{org.name}' ({project_uuid}) already has is_multi_agent={is_multi_agent}, no update needed"
        )
        return org

    org.config["is_multi_agent"] = is_multi_agent

    user, _ = get_or_create_user_by_email(user_email)
    org.modified_by = user
    org.modified_on = timezone.now()

    org.save(update_fields=["config", "modified_by", "modified_on"])

    logger.info(f"Project '{org.name}' ({project_uuid}) is_multi_agent set to {is_multi_agent} by {user_email}")

    return org
