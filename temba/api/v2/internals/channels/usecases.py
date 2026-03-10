from temba.channels.models import Channel


class ChannelNotFoundError(Exception):
    pass


class ElevenLabsApiKeyNotFoundError(Exception):
    pass


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
