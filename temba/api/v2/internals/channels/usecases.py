import logging

from rest_framework import status
from rest_framework.exceptions import APIException

from temba.channels.models import Channel
from temba.channels.types.telephony import provisioning
from temba.channels.types.telephony.connection import build_connection_data
from temba.channels.types.telephony.constants import CONFIG_SIP_RESET_REQUIRED

logger = logging.getLogger(__name__)


class ChannelNotFoundError(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "Channel not found"


class ElevenLabsApiKeyNotFoundError(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "ElevenLabs API key not found"


class GetElevenLabsApiKeyUseCase:
    def execute(self, channel_uuid: str) -> str:
        try:
            channel = Channel.objects.get(uuid=channel_uuid)
        except Channel.DoesNotExist:
            raise ChannelNotFoundError()

        api_key = channel.config.get("voice_mode", {}).get("elevenLabs", {}).get("apiKey")
        if api_key is None:
            raise ElevenLabsApiKeyNotFoundError()

        return api_key


class GetChannelMarketingTagsUseCase:
    def execute(self, channel_uuid: str) -> bool:
        try:
            channel = Channel.objects.get(uuid=channel_uuid)
        except Channel.DoesNotExist:
            raise ChannelNotFoundError()

        return bool(channel.config.get("marketing_tags", False))


class SIPChannelNotFoundError(Exception):
    """One error for every reason a channel cannot be used, so callers cannot probe which channels exist."""


class SIPNotProvisionedError(Exception):
    pass


class _SIPUseCase:
    def __init__(self, provisioner=None):
        self._provisioner = provisioner

    @property
    def provisioner(self):
        if self._provisioner is None:
            self._provisioner = provisioning.SIPProvisioner()
        return self._provisioner

    @staticmethod
    def find_channel(channel_uuid, project_uuid):
        """The channel must be an active TPH channel of that project. Nothing else is revealed (SEC-03)."""
        channel = (
            Channel.objects.filter(uuid=channel_uuid, org__proj_uuid=project_uuid, is_active=True, channel_type="TPH")
            .select_related("org")
            .first()
        )
        if channel is None:
            raise SIPChannelNotFoundError()
        if not provisioning.channel_is_provisioned(channel):
            raise SIPNotProvisionedError()
        return channel


class GetSIPConnectionUseCase(_SIPUseCase):
    def execute(self, channel_uuid, project_uuid) -> dict:
        channel = self.find_channel(channel_uuid, project_uuid)
        return build_connection_data(channel, self.provisioner.read_status(channel.uuid))


class IssueSIPCredentialsUseCase(_SIPUseCase):
    def execute(self, channel_uuid, project_uuid, actor_id=None) -> dict:
        """
        Issues a new password for the channel. Raises ``SIPRateLimitError`` past the limit and
        ``SIPProvisioningError`` when the credential store cannot be updated. The password is returned and never kept.
        """
        channel = self.find_channel(channel_uuid, project_uuid)

        provisioning.check_issue_rate(channel.uuid)
        password = self.provisioner.issue_password(channel.uuid)

        config = dict(channel.config or {})
        if config.pop(CONFIG_SIP_RESET_REQUIRED, None) is not None:
            channel.config = config
            channel.save(update_fields=["config"])

        logger.info(
            "tph sip: password issued",
            extra={
                "event": "issue_credentials",
                "channel_uuid": str(channel.uuid),
                "org_id": channel.org_id,
                "user_id": actor_id,
            },
        )

        data = build_connection_data(channel, self.provisioner.read_status(channel.uuid))
        data["password"] = password
        return data
