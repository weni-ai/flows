import logging
import re
import uuid
from dataclasses import dataclass
from enum import StrEnum
from functools import partial

from sentry_sdk import capture_exception, push_scope

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import DatabaseError

from temba.orgs.models import Org

User = get_user_model()

logger = logging.getLogger(__name__)

LOG_EVENT_CONSUMED = "project_event_consumed"
LOG_EVENT_SKIPPED = "project_event_skipped"
LOG_EVENT_ORG_NOT_FOUND = "project_event_org_not_found"

SKIP_REASON_LEGACY_CONSUMER_APPLIES = "legacy_consumer_applies"
SKIP_REASON_AMAZONMQ_CONSUMER_APPLIES = "amazonmq_consumer_applies"

REDACTED_EMAIL = "[email]"
REDACTED_NAME = "[name]"
EMAIL_PATTERN = re.compile(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)+")


class EventAction(StrEnum):
    DELETED = "deleted"
    UPDATED = "updated"
    STATUS_UPDATED = "status_updated"
    PROJECT_TYPE_UPDATED = "project_type_update"


class ProjectStatus(StrEnum):
    ACTIVE = "ACTIVE"
    IN_TEST = "IN_TEST"
    INACTIVE = "INACTIVE"


class InvalidProjectEvent(ValueError):
    """
    A project event that fails validation. The message names the field and the rule, never the received value,
    so it is safe to log and to send to Sentry.
    """


def is_legacy_action(action: str) -> bool:
    """Whether the legacy flows.project-events consumer is the one that applies this action."""
    return action in settings.PROJECT_EVENTS_LEGACY_ACTIONS


@dataclass
class ProjectEventContext:
    """
    Opaque identifiers collected while a project event is processed. It must never hold an e-mail, a name or any
    other payload value, because it ends up in logs, Sentry tags and the rejection message.
    """

    event_id: str | None = None
    event_type: str | None = None
    action: str | None = None
    project_uuid: str | None = None
    org_id: int | None = None
    user_id: int | None = None

    def log_fields(self) -> str:
        fields = {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "action": self.action,
            "project_uuid": self.project_uuid,
        }
        return " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)

    def sentry_tags(self) -> dict:
        tags = {
            "project_uuid": self.project_uuid,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "action": self.action,
            "org_id": self.org_id,
            "user_id": self.user_id,
        }
        return {key: value for key, value in tags.items() if value is not None}


class ProjectEventRejected(Exception):
    """
    Raised in place of the original failure so that the weni-eda rejection log, and the Sentry event made from it,
    carry neither the payload nor the original exception's message.
    """

    def __init__(self, context: ProjectEventContext, exception: Exception):
        reason = str(exception) if isinstance(exception, InvalidProjectEvent) else type(exception).__name__
        fields = context.log_fields()
        super().__init__(f"project event rejected: {fields + ' ' if fields else ''}reason={reason}")


def canonical_uuid(value) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def find_org_id(project_uuid: str | None) -> int | None:
    if project_uuid is None:
        return None
    return Org.objects.filter(proj_uuid=project_uuid).values_list("id", flat=True).first()


def find_user_id(email) -> int | None:
    """Looks up the user with this e-mail without ever creating one."""
    if not isinstance(email, str) or not email.strip():
        return None
    return User.objects.filter(email=email).values_list("id", flat=True).first()


def scrub_sentry_event(event: dict, hint: dict, redacted_names: tuple = ()) -> dict:
    """Drops stack frame variables and redacts e-mail addresses and the given names in exception values."""
    name_patterns = [re.compile(rf"(?<!\w){re.escape(name)}(?!\w)") for name in redacted_names if name]
    for container in ("exception", "threads"):
        for value in (event.get(container) or {}).get("values") or []:
            if isinstance(value.get("value"), str):
                text = EMAIL_PATTERN.sub(REDACTED_EMAIL, value["value"])
                for pattern in name_patterns:
                    text = pattern.sub(REDACTED_NAME, text)
                value["value"] = text
            for frame in (value.get("stacktrace") or {}).get("frames") or []:
                frame.pop("vars", None)
    return event


def _org_names(org_id: int | None) -> tuple:
    if org_id is None:
        return ()
    try:
        return tuple(Org.objects.filter(id=org_id).values_list("name", flat=True))
    except DatabaseError:
        # reporting must not fail when the failure being reported broke the connection
        return ()


def report_exception(exception: Exception, context: ProjectEventContext) -> None:
    redacted_names = _org_names(context.org_id)
    with push_scope() as scope:
        for key, value in context.sentry_tags().items():
            scope.set_tag(key, value)
        scope.add_event_processor(partial(scrub_sentry_event, redacted_names=redacted_names))
        capture_exception(exception)
