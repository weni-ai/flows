from sentry_sdk import capture_exception
from weni.eda.django.consumers import EDAConsumer
from weni.eda.messages import Message

from temba.projects.usecases.project_creation import ProjectCreationUseCase

from ..usecases import FlowSetupHandlerUseCase, ProjectCreationDTO, TemplateTypeIntegrationUseCase


class ProjectEventType:
    CREATED = "project.created"


class ProjectConsumer(EDAConsumer):
    def consume(self, message: Message):  # pragma: no cover
        try:
            event = message.event()

            if event.event_type == ProjectEventType.CREATED:
                self._handle_project_created(event.data)

            self.ack()
        except Exception as exception:
            capture_exception(exception)
            raise

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
