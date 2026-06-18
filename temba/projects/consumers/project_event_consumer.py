from enum import StrEnum

import amqp
from sentry_sdk import capture_exception
from weni.eda.django.consumers import EDAConsumer
from weni.eda.parsers import JSONParser

from temba.projects.usecases.project_delete import delete_project
from temba.projects.usecases.project_status_update import update_project_status
from temba.projects.usecases.project_type_update import update_project_type
from temba.projects.usecases.project_update import update_project_config


class EventAction(StrEnum):
    DELETED = "deleted"
    UPDATED = "updated"
    STATUS_UPDATED = "status_updated"
    PROJECT_TYPE_UPDATED = "project_type_update"


class ProjectStatus(StrEnum):
    ACTIVE = "ACTIVE"
    IN_TEST = "IN_TEST"
    INACTIVE = "INACTIVE"


class ProjectEventConsumer(EDAConsumer):
    """
    Consumer for handling project events (update, delete, and status update).

    Handles messages from update-projects.topic exchange.
    Events are differentiated by the 'action' field:
    - action: "deleted" -> calls delete_project
    - action: "updated" -> calls update_project_config
    - action: "status_updated" -> calls update_project_status
    """

    def consume(self, message: amqp.Message):  # pragma: no cover
        try:
            body = JSONParser.parse(message.body)

            self._validate_message(body)

            project_uuid = body.get("project_uuid")
            user_email = body.get("user_email")
            action = body.get("action")

            self._process_event(project_uuid, user_email, action, body)

            self.ack()
        except Exception as exception:
            capture_exception(exception)
            raise

    def _validate_message(self, body):
        """Validate that all required fields are present in the message."""
        required_fields = ["project_uuid", "action", "user_email"]

        for field in required_fields:
            if not body.get(field):
                raise ValueError(f"Missing required field: {field}")

        action = body.get("action")
        try:
            EventAction(action)
        except ValueError:
            allowed = ", ".join(e.value for e in EventAction)
            raise ValueError(f"Invalid action: {action}. Must be one of: {allowed}") from None

        if action == EventAction.STATUS_UPDATED:
            status = body.get("status")
            if not status:
                raise ValueError("Missing required field 'status' for status_updated action")
            try:
                ProjectStatus(status)
            except ValueError:
                allowed = ", ".join(e.value for e in ProjectStatus)
                raise ValueError(f"Invalid status: {status}. Must be one of: {allowed}") from None

    def _process_event(self, project_uuid: str, user_email: str, action: str, body: dict):
        """
        Process the project event based on action.

        Args:
            project_uuid: UUID of the project
            user_email: Email of the user performing the action
            action: Action to perform ('deleted', 'updated', or 'status_updated')
            body: Full message body
        """
        if action == EventAction.DELETED:
            delete_project(
                project_uuid=project_uuid,
                user_email=user_email,
            )

        elif action == EventAction.UPDATED:
            update_project_config(
                project_uuid=project_uuid,
                user_email=user_email,
                name=body.get("name"),
                description=body.get("description"),
                language=body.get("language"),
                timezone_location=body.get("timezone"),
            )

        elif action == EventAction.STATUS_UPDATED:
            status = body.get("status")
            update_project_status(
                project_uuid=project_uuid,
                status=status,
                user_email=user_email,
            )

        elif action == EventAction.PROJECT_TYPE_UPDATED:
            is_multi_agents = bool(body.get("is_multi_agents"))
            update_project_type(
                project_uuid=project_uuid,
                is_multi_agents=is_multi_agents,
                user_email=user_email,
            )
        else:
            raise ValueError(f"Unknown action: {action}")
