import re
import uuid
from dataclasses import dataclass

import pytz

from .project_events import InvalidProjectEvent, ProjectStatus

__all__ = [
    "ENVELOPE_TOKEN_PATTERN",
    "InvalidProjectEvent",
    "ProjectDeletedData",
    "ProjectEventEnvelope",
    "ProjectStatusUpdatedData",
    "ProjectTypeUpdatedData",
    "ProjectUpdatedData",
]

ENVELOPE_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,64}")
ENVELOPE_TOKEN_RULE = "a string of 1 to 64 characters from A-Z a-z 0-9 . _ : -"


def _envelope_token(value, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not ENVELOPE_TOKEN_PATTERN.fullmatch(value):
        rule = f"{ENVELOPE_TOKEN_RULE} or null" if nullable else ENVELOPE_TOKEN_RULE
        raise InvalidProjectEvent(f"{field} must be {rule}")
    return value


def _require_dict(data) -> dict:
    if not isinstance(data, dict):
        raise InvalidProjectEvent("data must be an object")
    return data


def _project_uuid(data: dict) -> str:
    value = data.get("uuid")
    if not isinstance(value, str):
        raise InvalidProjectEvent("data.uuid must be a string in UUID format")
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise InvalidProjectEvent("data.uuid must be a string in UUID format") from None


def _user_email(data: dict) -> str:
    value = data.get("user_email")
    if not isinstance(value, str) or not value.strip():
        raise InvalidProjectEvent("data.user_email must be a non-empty string")
    return value


def _optional_string(data: dict, field: str) -> str | None:
    value = data.get(field)
    if value is not None and not isinstance(value, str):
        raise InvalidProjectEvent(f"data.{field} must be a string or null")
    return value


def _timezone(data: dict) -> str | None:
    value = data.get("timezone")
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidProjectEvent("data.timezone must be a known time zone name or null")
    try:
        pytz.timezone(value)
    except pytz.UnknownTimeZoneError:
        raise InvalidProjectEvent("data.timezone must be a known time zone name or null") from None
    return value


def _status(data: dict) -> ProjectStatus:
    value = data.get("status")
    allowed = [status.value for status in ProjectStatus]
    if not isinstance(value, str) or value not in allowed:
        raise InvalidProjectEvent(f"data.status must be one of: {', '.join(allowed)}")
    return ProjectStatus(value)


def _is_multi_agents(data: dict) -> bool:
    value = data.get("is_multi_agents")
    if not isinstance(value, bool):
        raise InvalidProjectEvent("data.is_multi_agents must be a boolean")
    return value


@dataclass(frozen=True)
class ProjectEventEnvelope:
    """The envelope fields that are written to logs, Sentry tags and the rejection message."""

    event_id: str
    event_type: str
    producer: str | None

    @classmethod
    def from_event(cls, event) -> "ProjectEventEnvelope":
        return cls(
            event_id=_envelope_token(event.event_id, "event_id"),
            event_type=_envelope_token(event.event_type, "event_type"),
            producer=_envelope_token(event.producer, "producer", nullable=True),
        )


@dataclass(frozen=True)
class ProjectUpdatedData:
    project_uuid: str
    user_email: str
    name: str | None
    description: str | None
    language: str | None
    timezone: str | None

    @classmethod
    def from_data(cls, data) -> "ProjectUpdatedData":
        data = _require_dict(data)
        return cls(
            project_uuid=_project_uuid(data),
            user_email=_user_email(data),
            name=_optional_string(data, "name"),
            description=_optional_string(data, "description"),
            language=_optional_string(data, "language"),
            timezone=_timezone(data),
        )


@dataclass(frozen=True)
class ProjectStatusUpdatedData:
    project_uuid: str
    user_email: str
    status: ProjectStatus

    @classmethod
    def from_data(cls, data) -> "ProjectStatusUpdatedData":
        data = _require_dict(data)
        return cls(project_uuid=_project_uuid(data), user_email=_user_email(data), status=_status(data))


@dataclass(frozen=True)
class ProjectTypeUpdatedData:
    project_uuid: str
    user_email: str
    is_multi_agents: bool

    @classmethod
    def from_data(cls, data) -> "ProjectTypeUpdatedData":
        data = _require_dict(data)
        return cls(
            project_uuid=_project_uuid(data), user_email=_user_email(data), is_multi_agents=_is_multi_agents(data)
        )


@dataclass(frozen=True)
class ProjectDeletedData:
    project_uuid: str
    user_email: str

    @classmethod
    def from_data(cls, data) -> "ProjectDeletedData":
        data = _require_dict(data)
        return cls(project_uuid=_project_uuid(data), user_email=_user_email(data))
