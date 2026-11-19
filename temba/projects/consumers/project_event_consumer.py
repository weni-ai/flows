import logging

from weni.eda.django.consumers import EDAConsumer
from weni.eda.messages import Message

from django.db import DatabaseError

from temba.projects.usecases.project_delete import delete_project
from temba.projects.usecases.project_status_update import update_project_status
from temba.projects.usecases.project_type_update import update_project_type
from temba.projects.usecases.project_update import update_project_config

from .project_events import (
    LOG_EVENT_CONSUMED,
    LOG_EVENT_SKIPPED,
    SKIP_REASON_AMAZONMQ_CONSUMER_APPLIES,
    EventAction,
    ProjectEventContext,
    ProjectEventRejected,
    ProjectStatus,
    canonical_uuid,
    find_org_id,
    find_user_id,
    is_legacy_action,
    report_exception,
)

logger = logging.getLogger(__name__)


class ProjectEventConsumer(EDAConsumer):
    """
    Consumer for handling project events (update, delete, and status update).

    Deprecated: flows.project-events is replaced by ProjectConsumer on flows.projects.queue. An action is applied
    here only while it is listed in PROJECT_EVENTS_LEGACY_ACTIONS.

    Handles messages from update-projects.topic exchange.
    Events are differentiated by the 'action' field:
    - action: "deleted" -> calls delete_project
    - action: "updated" -> calls update_project_config
    - action: "status_updated" -> calls update_project_status
    - action: "project_type_update" -> calls update_project_type
    """

    def consume(self, message: Message):
        context = ProjectEventContext()
        try:
            self._process(message, context)
        except Exception as exception:
            try:
                context.org_id = find_org_id(context.project_uuid)
            except DatabaseError:
                # the tag lookup must never replace the failure being reported
                pass
            report_exception(exception, context)
            raise ProjectEventRejected(context, exception) from None

    def _process(self, message: Message, context: ProjectEventContext):
        body = message.json()

        self._validate_message(body)

        project_uuid = body.get("project_uuid")
        user_email = body.get("user_email")
        action = body.get("action")

        context.action = action
        context.project_uuid = canonical_uuid(project_uuid)
        logger.info("%s %s", LOG_EVENT_CONSUMED, context.log_fields())

        if not is_legacy_action(action):
            logger.info(
                "%s %s reason=%s", LOG_EVENT_SKIPPED, context.log_fields(), SKIP_REASON_AMAZONMQ_CONSUMER_APPLIES
            )
            self.ack()
            return

        context.user_id = find_user_id(user_email)
        self._apply_event(project_uuid, user_email, action, body)

        self.ack()

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

    def _apply_event(self, project_uuid: str, user_email: str, action: str, body: dict):
        """
        Apply the project event based on action.

        Args:
            project_uuid: UUID of the project
            user_email: Email of the user performing the action
            action: Action to perform ('deleted', 'updated', 'status_updated' or 'project_type_update')
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
