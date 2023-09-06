import amqp
from sentry_sdk import capture_exception

from temba.event_driven.consumers import EDAConsumer
from temba.event_driven.parsers import JSONParser
from temba.projects.usecases.project_creation import ProjectCreationUseCase

from ..usecases import FlowSetupHandlerUseCase, ProjectCreationDTO, TemplateTypeIntegrationUseCase


class ProjectConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        try:
            body = JSONParser.parse(message.body)
            print(f"[ProjectConsumer] - Consuming a message. Body: {body}")
            project_dto = ProjectCreationDTO(
                uuid=body.get("uuid"),
                name=body.get("name"),
                is_template=body.get("is_template"),
                date_format=body.get("date_format"),
                template_type_uuid=body.get("template_type_uuid"),
                timezone=body.get("timezone"),
            )

            flow_setup_handler = FlowSetupHandlerUseCase()
            template_type_integration = TemplateTypeIntegrationUseCase(flow_setup_handler)
            project_creation = ProjectCreationUseCase(template_type_integration)
            project_creation.create_project(project_dto, body.get("user_email"))

        except Exception as exception:
            capture_exception(exception)
            message.channel.basic_reject(message.delivery_tag, requeue=False)
            print(f"[ProjectConsumer] - Message rejected by: {exception}")
