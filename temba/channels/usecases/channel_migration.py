from typing import Optional, Union
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from temba.channels.models import Channel
from temba.channels.usecases.exceptions import (
    ChannelNotFoundError,
    ChannelOrgMismatchError,
    ChannelWithoutOrgError,
    DestOrgNotFoundError,
)
from temba.orgs.models import Org
from temba.templates.models import Template, TemplateTranslation


class MigrateChannelUseCase:
    """Migrates a Channel (and its templates) to another org/project.

    Templates belong to the org while translations belong to channels. Exclusive
    templates move whole; shared templates only re-point this channel's translations.
    """

    def execute(
        self,
        channel_uuid: Union[UUID, str],
        project_to: Union[UUID, str],
        project_from: Optional[Union[UUID, str]] = None,
    ) -> Channel:
        channel_uuid_str = str(channel_uuid)
        project_to_str = str(project_to)

        with transaction.atomic():
            try:
                channel = Channel.objects.select_for_update().get(uuid=channel_uuid_str)
            except Channel.DoesNotExist as exc:
                raise ChannelNotFoundError(channel_uuid_str) from exc

            try:
                dest_org = Org.objects.get(
                    proj_uuid=project_to_str,
                    is_active=True,
                    released_on__isnull=True,
                )
            except Org.DoesNotExist as exc:
                raise DestOrgNotFoundError(project_to_str) from exc

            if channel.org_id == dest_org.id:
                return channel

            if channel.org is None:
                raise ChannelWithoutOrgError(channel_uuid_str)

            if project_from is not None and str(channel.org.proj_uuid) != str(project_from):
                raise ChannelOrgMismatchError(
                    channel_uuid_str,
                    expected_project_uuid=str(project_from),
                    actual_project_uuid=str(channel.org.proj_uuid),
                )

            self._migrate_templates(channel, dest_org)
            self._migrate_channel(channel, dest_org)
            self._migrate_child_channels(channel, dest_org)

        return channel

    def _migrate_templates(self, channel: Channel, dest_org: Org) -> None:
        templates = Template.objects.filter(translations__channel=channel).distinct()
        for template in templates:
            self._migrate_single_template(template, channel, dest_org)

    def _migrate_single_template(
        self,
        template: Template,
        channel: Channel,
        dest_org: Org,
    ) -> None:
        dest_template = Template.objects.filter(org=dest_org, name=template.name).first()
        shared_with_others = TemplateTranslation.objects.filter(template=template).exclude(channel=channel).exists()

        if dest_template is None and not shared_with_others:
            template.org = dest_org
            template.save(update_fields=["org"])
            return

        if dest_template is None:
            dest_template = Template.objects.create(
                org=dest_org,
                name=template.name,
                category=template.category,
            )

        TemplateTranslation.objects.filter(template=template, channel=channel).update(template=dest_template)

    def _migrate_channel(self, channel: Channel, dest_org: Org) -> None:
        channel.org = dest_org
        channel.modified_on = timezone.now()
        channel.save(update_fields=["org", "modified_on"])

    def _migrate_child_channels(self, channel: Channel, dest_org: Org) -> None:
        now = timezone.now()
        Channel.objects.filter(parent=channel).update(org=dest_org, modified_on=now)
