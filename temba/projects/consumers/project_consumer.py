import logging

from weni.eda.django.consumers import EDAConsumer
from weni.eda.messages import Message

from temba.projects.usecases.project_creation import ProjectCreationUseCase
from temba.projects.usecases.project_delete import delete_project
from temba.projects.usecases.project_status_update import update_project_status
from temba.projects.usecases.project_type_update import update_project_type
from temba.projects.usecases.project_update import update_project_config

from ..usecases import FlowSetupHandlerUseCase, ProjectCreationDTO, TemplateTypeIntegrationUseCase
from .project_event_payloads import (
    ProjectDeletedData,
    ProjectEventEnvelope,
    ProjectStatusUpdatedData,
    ProjectTypeUpdatedData,
    ProjectUpdatedData,
)
from .project_events import (
    LOG_EVENT_CONSUMED,
    LOG_EVENT_ORG_NOT_FOUND,
    LOG_EVENT_SKIPPED,
    SKIP_REASON_LEGACY_CONSUMER_APPLIES,
    EventAction,
    ProjectEventContext,
    ProjectEventRejected,
    find_org_id,
    find_user_id,
    is_legacy_action,
    report_exception,
)

logger = logging.getLogger(__name__)


class ProjectEventType:
    CREATED = "project.created"
    UPDATED = "project.updated"
    STATUS_UPDATED = "project.status.updated"
    TYPE_UPDATED = "project.type.updated"
    DELETED = "project.deleted"


LEGACY_ACTION_BY_EVENT_TYPE = {
    ProjectEventType.UPDATED: EventAction.UPDATED,
    ProjectEventType.STATUS_UPDATED: EventAction.STATUS_UPDATED,
    ProjectEventType.TYPE_UPDATED: EventAction.PROJECT_TYPE_UPDATED,
    ProjectEventType.DELETED: EventAction.DELETED,
}

PAYLOAD_BY_EVENT_TYPE = {
    ProjectEventType.UPDATED: ProjectUpdatedData,
    ProjectEventType.STATUS_UPDATED: ProjectStatusUpdatedData,
    ProjectEventType.TYPE_UPDATED: ProjectTypeUpdatedData,
    ProjectEventType.DELETED: ProjectDeletedData,
}


class ProjectConsumer(EDAConsumer):
    """
    Consumer for project events on flows.projects.queue (AmazonMQ projects.topic, routing key = event_type).

    project.updated, project.status.updated, project.type.updated and project.deleted are applied only when their
    legacy action is not in PROJECT_EVENTS_LEGACY_ACTIONS; otherwise ProjectEventConsumer applies them.
    """

    def consume(self, message: Message):
        context = ProjectEventContext()
        try:
            self._process(message, context)
        except Exception as exception:
            report_exception(exception, context)
            raise ProjectEventRejected(context, exception) from None

    def _process(self, message: Message, context: ProjectEventContext):
        event = message.event()
        envelope = ProjectEventEnvelope.from_event(event)
        context.event_id = envelope.event_id
        context.event_type = envelope.event_type

        if envelope.event_type in PAYLOAD_BY_EVENT_TYPE:
            self._handle_project_change(event.data, envelope, context)
        else:
            self._log_consumed(context, envelope)
            if envelope.event_type == ProjectEventType.CREATED:
                self._handle_project_created(event.data)

        self.ack()

    def _log_consumed(self, context: ProjectEventContext, envelope: ProjectEventEnvelope):
        logger.info("%s %s producer=%s", LOG_EVENT_CONSUMED, context.log_fields(), envelope.producer)

    def _handle_project_change(self, data, envelope: ProjectEventEnvelope, context: ProjectEventContext):
        payload = PAYLOAD_BY_EVENT_TYPE[envelope.event_type].from_data(data)
        context.project_uuid = payload.project_uuid
        self._log_consumed(context, envelope)

        if is_legacy_action(LEGACY_ACTION_BY_EVENT_TYPE[envelope.event_type]):
            logger.info(
                "%s %s reason=%s", LOG_EVENT_SKIPPED, context.log_fields(), SKIP_REASON_LEGACY_CONSUMER_APPLIES
            )
            return

        context.org_id = find_org_id(payload.project_uuid)
        if context.org_id is None:
            logger.warning("%s %s", LOG_EVENT_ORG_NOT_FOUND, context.log_fields())
            return

        context.user_id = find_user_id(payload.user_email)

        if envelope.event_type == ProjectEventType.UPDATED:
            update_project_config(
                project_uuid=payload.project_uuid,
                user_email=payload.user_email,
                name=payload.name,
                description=payload.description,
                language=payload.language,
                timezone_location=payload.timezone,
            )
        elif envelope.event_type == ProjectEventType.STATUS_UPDATED:
            update_project_status(
                project_uuid=payload.project_uuid, status=payload.status.value, user_email=payload.user_email
            )
        elif envelope.event_type == ProjectEventType.TYPE_UPDATED:
            update_project_type(
                project_uuid=payload.project_uuid,
                is_multi_agents=payload.is_multi_agents,
                user_email=payload.user_email,
            )
        else:
            delete_project(project_uuid=payload.project_uuid, user_email=payload.user_email)

    def _handle_project_created(self, body: dict):
        project_dto = ProjectCreationDTO(
            uuid=body.get("uuid"),
            name=body.get("name"),
            is_template=body.get("is_template"),
            date_format=body.get("date_format"),
            template_type_uuid=body.get("template_type_uuid"),
            timezone=body.get("timezone"),
            description=body.get("description"),
            brain_on=body.get("brain_on", False),
            language=body.get("language"),
            inline_agent_switch=body.get("inline_agent_switch", True),
            is_live_desk_copilot=body.get("is_live_desk_copilot", False),
        )

        flow_setup_handler = FlowSetupHandlerUseCase()
        template_type_integration = TemplateTypeIntegrationUseCase(flow_setup_handler)
        project_creation = ProjectCreationUseCase(template_type_integration)
        project_creation.create_project(
            project_dto,
            body.get("user_email"),
            body.get("extra_fields"),
            body.get("authorizations"),
        )
