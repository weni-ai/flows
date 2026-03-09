import uuid
from unittest.mock import Mock, patch

import pytz

from django.conf import settings

from temba.channels.models import Channel
from temba.projects.usecases.channel_creation import DEFAULT_WWC_CHANNEL_NAME
from temba.projects.usecases.project_creation import ProjectCreationDTO, ProjectCreationUseCase
from temba.tests.base import TembaTest


class ProjectCreationUseCaseTest(TembaTest):
    @patch("temba.projects.usecases.project_creation.ConnectInternalClient.update_project")
    @patch("temba.projects.usecases.channel_creation.publish_channel_event")
    def test_create_project_creates_default_wwc_channel(self, mock_publish_channel_event, mock_update_project):
        user_email = "new-project-admin@example.com"
        project_uuid = uuid.uuid4()
        project_dto = ProjectCreationDTO(
            uuid=str(project_uuid),
            name="Projeto com WWC",
            is_template=False,
            date_format="D",
            timezone=pytz.timezone("Africa/Kigali"),
            template_type_uuid="",
            description="Projeto de teste",
            brain_on=False,
        )

        use_case = ProjectCreationUseCase(template_type_integration=Mock())

        use_case.create_project(project_dto, user_email, extra_fields={}, authorizations=[])

        project = self.project.__class__.objects.get(project_uuid=project_uuid)
        channel = Channel.objects.get(org=project.org, channel_type="WWC")

        self.assertEqual(channel.name, DEFAULT_WWC_CHANNEL_NAME)
        self.assertEqual(channel.address, str(project.project_uuid))
        self.assertTrue(channel.config["preview"])
        mock_update_project.assert_called_once_with(project)
        mock_publish_channel_event.assert_called_once_with(channel, action="create")

    @patch("temba.projects.usecases.project_creation.ConnectInternalClient.update_project")
    @patch("temba.projects.usecases.channel_creation.publish_channel_event")
    def test_create_project_creates_new_wwc_channel_when_existing_lacks_preview(
        self, mock_publish_channel_event, mock_update_project
    ):
        project_uuid = uuid.uuid4()
        project = self.project.__class__.objects.create(
            project_uuid=project_uuid,
            name="Projeto existente",
            timezone=pytz.timezone("Africa/Kigali"),
            brand=settings.DEFAULT_BRAND,
            created_by=self.user,
            modified_by=self.user,
        )

        Channel.create(
            org=project.org,
            user=self.user,
            country=None,
            channel_type="WWC",
            name="Weni Web Chat",
            address=str(project.project_uuid),
            config={},
        )

        project_dto = ProjectCreationDTO(
            uuid=str(project_uuid),
            name="Projeto existente",
            is_template=False,
            date_format="D",
            timezone=pytz.timezone("Africa/Kigali"),
            template_type_uuid="",
            description="Projeto existente",
            brain_on=False,
        )

        use_case = ProjectCreationUseCase(template_type_integration=Mock())

        use_case.create_project(project_dto, self.user.email, extra_fields={}, authorizations=[])

        channels = Channel.objects.filter(org=project.org, channel_type="WWC").order_by("created_on")
        new_channel = channels.last()

        self.assertEqual(channels.count(), 2)
        self.assertEqual(new_channel.name, DEFAULT_WWC_CHANNEL_NAME)
        self.assertEqual(new_channel.address, str(project.project_uuid))
        self.assertTrue(new_channel.config["preview"])
        mock_update_project.assert_called_once()
        mock_publish_channel_event.assert_called_once_with(new_channel, action="create")

    @patch("temba.projects.usecases.project_creation.ConnectInternalClient.update_project")
    @patch("temba.projects.usecases.channel_creation.publish_channel_event")
    def test_create_project_reuses_existing_wwc_channel_with_preview(self, mock_publish_channel_event, mock_update_project):
        project_uuid = uuid.uuid4()
        project = self.project.__class__.objects.create(
            project_uuid=project_uuid,
            name="Projeto existente com preview",
            timezone=pytz.timezone("Africa/Kigali"),
            brand=settings.DEFAULT_BRAND,
            created_by=self.user,
            modified_by=self.user,
        )

        existing_channel = Channel.create(
            org=project.org,
            user=self.user,
            country=None,
            channel_type="WWC",
            name=DEFAULT_WWC_CHANNEL_NAME,
            address=str(project.project_uuid),
            config={"preview": True},
        )

        project_dto = ProjectCreationDTO(
            uuid=str(project_uuid),
            name="Projeto existente com preview",
            is_template=False,
            date_format="D",
            timezone=pytz.timezone("Africa/Kigali"),
            template_type_uuid="",
            description="Projeto existente",
            brain_on=False,
        )

        use_case = ProjectCreationUseCase(template_type_integration=Mock())

        use_case.create_project(project_dto, self.user.email, extra_fields={}, authorizations=[])

        self.assertEqual(Channel.objects.filter(org=project.org, channel_type="WWC").count(), 1)
        self.assertEqual(Channel.objects.get(org=project.org, channel_type="WWC"), existing_channel)
        mock_update_project.assert_called_once()
        mock_publish_channel_event.assert_not_called()
