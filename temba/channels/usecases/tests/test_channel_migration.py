import uuid

from temba.channels.usecases.channel_migration import MigrateChannelUseCase
from temba.channels.usecases.exceptions import (
    ChannelNotFoundError,
    ChannelOrgMismatchError,
    DestOrgNotFoundError,
)
from temba.templates.models import Template, TemplateTranslation
from temba.tests.base import TembaTest


class MigrateChannelUseCaseTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.source_org = self.org
        self.source_org.proj_uuid = uuid.uuid4()
        self.source_org.save(update_fields=["proj_uuid"])

        self.dest_org = self.org2
        self.dest_org.proj_uuid = uuid.uuid4()
        self.dest_org.save(update_fields=["proj_uuid"])

        self.wac_channel = self.create_channel(
            "WAC",
            "WhatsApp Cloud",
            "+5511999999999",
            org=self.source_org,
        )
        self.other_wac_channel = self.create_channel(
            "WAC",
            "Other WhatsApp",
            "+5511888888888",
            org=self.source_org,
        )

    def _create_translation(self, template, channel, external_id="ext-1"):
        return TemplateTranslation.objects.create(
            template=template,
            channel=channel,
            content="Hello {{1}}",
            body="Hello {{1}}",
            variable_count=1,
            status=TemplateTranslation.STATUS_APPROVED,
            language="eng",
            external_id=external_id,
        )

    def test_migrates_channel_to_destination_org(self):
        MigrateChannelUseCase().execute(
            channel_uuid=self.wac_channel.uuid,
            project_from=self.source_org.proj_uuid,
            project_to=self.dest_org.proj_uuid,
        )

        self.wac_channel.refresh_from_db()
        self.assertEqual(self.wac_channel.org_id, self.dest_org.id)

    def test_migrates_exclusive_template_with_channel(self):
        template = Template.objects.create(
            org=self.source_org,
            name="exclusive_template",
            category="MARKETING",
        )
        self._create_translation(template, self.wac_channel)

        MigrateChannelUseCase().execute(
            channel_uuid=self.wac_channel.uuid,
            project_from=self.source_org.proj_uuid,
            project_to=self.dest_org.proj_uuid,
        )

        template.refresh_from_db()
        self.assertEqual(template.org_id, self.dest_org.id)

    def test_migrates_shared_template_by_repointing_translations(self):
        template = Template.objects.create(
            org=self.source_org,
            name="shared_template",
            category="MARKETING",
        )
        self._create_translation(template, self.wac_channel, external_id="ext-1")
        self._create_translation(template, self.other_wac_channel, external_id="ext-2")

        MigrateChannelUseCase().execute(
            channel_uuid=self.wac_channel.uuid,
            project_from=self.source_org.proj_uuid,
            project_to=self.dest_org.proj_uuid,
        )

        template.refresh_from_db()
        self.assertEqual(template.org_id, self.source_org.id)

        moved_translation = TemplateTranslation.objects.get(
            channel=self.wac_channel,
            external_id="ext-1",
        )
        self.assertEqual(moved_translation.template.org_id, self.dest_org.id)
        self.assertNotEqual(moved_translation.template_id, template.id)

        other_translation = TemplateTranslation.objects.get(
            channel=self.other_wac_channel,
            external_id="ext-2",
        )
        self.assertEqual(other_translation.template_id, template.id)

    def test_reuses_existing_template_in_destination_org(self):
        source_template = Template.objects.create(
            org=self.source_org,
            name="welcome",
            category="MARKETING",
        )
        dest_template = Template.objects.create(
            org=self.dest_org,
            name="welcome",
            category="UTILITY",
        )
        self._create_translation(source_template, self.wac_channel)

        MigrateChannelUseCase().execute(
            channel_uuid=self.wac_channel.uuid,
            project_from=self.source_org.proj_uuid,
            project_to=self.dest_org.proj_uuid,
        )

        translation = TemplateTranslation.objects.get(channel=self.wac_channel)
        self.assertEqual(translation.template_id, dest_template.id)

    def test_migrates_child_channels(self):
        child = self.create_channel(
            "WAC",
            "Delegate",
            "+5511777777777",
            org=self.source_org,
        )
        child.parent = self.wac_channel
        child.save(update_fields=["parent"])

        MigrateChannelUseCase().execute(
            channel_uuid=self.wac_channel.uuid,
            project_from=self.source_org.proj_uuid,
            project_to=self.dest_org.proj_uuid,
        )

        child.refresh_from_db()
        self.assertEqual(child.org_id, self.dest_org.id)

    def test_is_idempotent_when_channel_already_in_destination(self):
        self.wac_channel.org = self.dest_org
        self.wac_channel.save(update_fields=["org"])

        result = MigrateChannelUseCase().execute(
            channel_uuid=self.wac_channel.uuid,
            project_from=self.source_org.proj_uuid,
            project_to=self.dest_org.proj_uuid,
        )

        self.assertEqual(result.org_id, self.dest_org.id)

    def test_raises_when_channel_not_found(self):
        with self.assertRaises(ChannelNotFoundError):
            MigrateChannelUseCase().execute(
                channel_uuid=str(uuid.uuid4()),
                project_to=self.dest_org.proj_uuid,
            )

    def test_raises_when_destination_org_not_found(self):
        with self.assertRaises(DestOrgNotFoundError):
            MigrateChannelUseCase().execute(
                channel_uuid=self.wac_channel.uuid,
                project_to=str(uuid.uuid4()),
            )

    def test_raises_when_project_from_does_not_match(self):
        with self.assertRaises(ChannelOrgMismatchError):
            MigrateChannelUseCase().execute(
                channel_uuid=self.wac_channel.uuid,
                project_from=str(uuid.uuid4()),
                project_to=self.dest_org.proj_uuid,
            )
