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


def update_project_type(project_uuid: str, is_multi_agents: bool, user_email: str) -> Optional[Org]:
    """
    Update the project (Org) type by setting the is_multi_agents flag in its config.

    Args:
        project_uuid: UUID of the project (stored in Org.proj_uuid)
        is_multi_agents: Whether the project is a multi-agent project
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

    if org.config.get("is_multi_agents") == is_multi_agents:
        logger.info(
            "project_type_unchanged project_uuid=%s org_id=%s is_multi_agents=%s",
            project_uuid,
            org.id,
            is_multi_agents,
        )
        return org

    org.config["is_multi_agents"] = is_multi_agents

    user, _ = get_or_create_user_by_email(user_email)
    org.modified_by = user
    org.modified_on = timezone.now()

    org.save(update_fields=["config", "modified_by", "modified_on"])

    logger.info(
        "project_type_updated project_uuid=%s org_id=%s is_multi_agents=%s", project_uuid, org.id, is_multi_agents
    )

    return org
