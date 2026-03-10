from rest_framework import status
from rest_framework.exceptions import APIException

from temba.channels.models import Channel


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
