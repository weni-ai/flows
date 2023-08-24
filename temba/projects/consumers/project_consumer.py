import amqp
from sentry_sdk import capture_exception

from temba.projects.usecases.project_creation import ProjectCreationUseCase

from ..usecases import ProjectCreationDTO, FlowSetupHandlerUseCase, TemplateTypeIntegrationUseCase
from temba.event_driven.parsers import JSONParser


class ProjectConsumer:
    @staticmethod
    def consume(message: amqp.Message):
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
            return None

        message.channel.basic_ack(message.delivery_tag)