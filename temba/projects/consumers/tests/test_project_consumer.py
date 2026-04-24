import json
import uuid
from unittest.mock import Mock, patch

from temba.projects.consumers.project_consumer import ProjectConsumer
from temba.tests.base import TembaTest


class TestProjectConsumer(TembaTest):
    def _create_mock_message(self, body_dict):
        message = Mock()
        message.body = json.dumps(body_dict, default=str)
        message.channel = Mock()
        message.delivery_tag = "test-delivery-tag"
        return message

    @patch("temba.projects.consumers.project_consumer.ProjectCreationUseCase")
    @patch("temba.projects.consumers.project_consumer.TemplateTypeIntegrationUseCase")
    @patch("temba.projects.consumers.project_consumer.FlowSetupHandlerUseCase")
    def test_consume_passes_inline_agent_switch_and_language_to_use_case(
        self, mock_flow_uc, mock_template_uc, mock_project_creation_uc
    ):
        mock_use_case = Mock()
        mock_project_creation_uc.return_value = mock_use_case

        body = {
            "uuid": str(uuid.uuid4()),
            "name": "Test Project",
            "is_template": False,
            "date_format": "D",
            "template_type_uuid": "",
            "timezone": "Africa/Kigali",
            "description": "desc",
            "brain_on": False,
            "language": "pt-br",
            "inline_agent_switch": True,
            "user_email": "admin@example.com",
            "extra_fields": {},
            "authorizations": [],
        }
        message = self._create_mock_message(body)

        ProjectConsumer().consume(message)

        mock_use_case.create_project.assert_called_once()
        project_dto, user_email, extra_fields, authorizations = mock_use_case.create_project.call_args[0]
        self.assertEqual(user_email, "admin@example.com")
        self.assertEqual(extra_fields, {})
        self.assertEqual(authorizations, [])
        self.assertEqual(project_dto.language, "pt-br")
        self.assertTrue(project_dto.inline_agent_switch)
        message.channel.basic_ack.assert_called_once_with(message.delivery_tag)

    @patch("temba.projects.consumers.project_consumer.ProjectCreationUseCase")
    @patch("temba.projects.consumers.project_consumer.TemplateTypeIntegrationUseCase")
    @patch("temba.projects.consumers.project_consumer.FlowSetupHandlerUseCase")
    def test_consume_defaults_inline_agent_switch_when_absent(
        self, mock_flow_uc, mock_template_uc, mock_project_creation_uc
    ):
        mock_use_case = Mock()
        mock_project_creation_uc.return_value = mock_use_case

        body = {
            "uuid": str(uuid.uuid4()),
            "name": "Test Project",
            "is_template": False,
            "date_format": "D",
            "template_type_uuid": "",
            "timezone": "Africa/Kigali",
            "description": "desc",
            "user_email": "admin@example.com",
            "extra_fields": None,
            "authorizations": None,
        }
        message = self._create_mock_message(body)

        ProjectConsumer().consume(message)

        project_dto = mock_use_case.create_project.call_args[0][0]
        self.assertTrue(project_dto.inline_agent_switch)
        self.assertFalse(project_dto.brain_on)
        message.channel.basic_ack.assert_called_once_with(message.delivery_tag)
