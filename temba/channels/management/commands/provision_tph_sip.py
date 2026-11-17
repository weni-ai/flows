import uuid

from django.core.management.base import BaseCommand, CommandError

from temba.channels.models import Channel
from temba.channels.types.telephony import provisioning
from temba.channels.types.telephony.provisioning import SIPProvisioningError


class Command(BaseCommand):
    help = (
        "Creates the KubeVoIP objects of an existing TPH channel (one created before provisioning was enabled). "
        "Safe to run again: existing objects and passwords are kept. Refuses to run while provisioning is disabled."
    )

    def add_arguments(self, parser):
        parser.add_argument("--channel", required=True, help="UUID of the TPH channel")

    def handle(self, *args, **options):
        if not provisioning.is_enabled():
            raise CommandError("TPH_SIP_PROVISIONING_ENABLED is off, nothing was changed")

        try:
            channel_uuid = uuid.UUID(options["channel"])
        except ValueError:
            raise CommandError("--channel must be a UUID")

        channel = Channel.objects.filter(uuid=channel_uuid, channel_type="TPH", is_active=True).first()
        if channel is None:
            raise CommandError("No active TPH channel with that uuid")

        try:
            provisioning.provision_channel(channel)
        except SIPProvisioningError as e:
            raise CommandError(f"Provisioning failed ({e.code}), nothing was left in the cluster")

        self.stdout.write(f"Channel {channel.uuid} is provisioned")
