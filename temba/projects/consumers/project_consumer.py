import logging

import amqp
from sentry_sdk import capture_exception
from weni.eda.django.consumers import EDAConsumer
from weni.eda.parsers import JSONParser

from temba.projects.usecases.project_creation import ProjectCreationUseCase

from ..usecases import FlowSetupHandlerUseCase, ProjectCreationDTO, TemplateTypeIntegrationUseCase

logger = logging.getLogger(__name__)


class ProjectConsumer(EDAConsumer):
    def consume(self, message: amqp.Message):  # pragma: no cover
        try:
            logger.info("[ProjectConsumer] Received message")
            body = JSONParser.parse(message.body)
            logger.info(
                "[ProjectConsumer] Processing project uuid=%s name=%s user_email=%s",
                body.get("uuid"),
                body.get("name"),
                body.get("user_email"),
            )
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
            )

            flow_setup_handler = FlowSetupHandlerUseCase()
            template_type_integration = TemplateTypeIntegrationUseCase(flow_setup_handler)
            project_creation = ProjectCreationUseCase(template_type_integration)
            project_creation.create_project(
                project_dto, body.get("user_email"), body.get("extra_fields"), body.get("authorizations")
            )

            self.ack()
            logger.info("[ProjectConsumer] Message processed successfully project_uuid=%s", body.get("uuid"))
        except Exception as exception:
            logger.exception("[ProjectConsumer] Failed to process message")
            capture_exception(exception)
            raise
