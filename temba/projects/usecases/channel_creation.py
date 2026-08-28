from django.conf import settings

from temba.channels.models import Channel
from temba.projects.usecases.channel_publisher import publish_channel_event

DEFAULT_WWC_CHANNEL_NAME = "Weni Web Chat - Preview"
COPILOT_WWC_CHANNEL_NAME = "Weni Web Chat - Copilot"


def is_hidden_from_ui(channel: Channel) -> bool:
    config = channel.config or {}
    return bool(config.get("preview")) or bool(config.get("is_live_desk_copilot"))


def _get_wwc_channel_by_config_flag(org, flag_key: str) -> Channel | None:
    for channel in Channel.objects.filter(org=org, channel_type="WWC"):
        if channel.config and channel.config.get(flag_key):
            return channel
    return None


def _build_default_wwc_config(preview: bool = False, is_live_desk_copilot: bool = False) -> dict:
    config = {
        "version": 2,
        "allowed_domains": settings.WENI_WEBCHAT_ALLOWED_DOMAINS,
        "base_url": settings.SOCKET_BASE_URL,
        "voice_mode": {
            "enabled": True,
            "elevenLabs": {
                "apiKey": settings.WENI_VOICE_TOKEN,
                "voiceId": settings.WENI_ELEVENLABS_VOICE_ID,
            },
        },
    }
    if preview:
        config["preview"] = True
    if is_live_desk_copilot:
        config["is_live_desk_copilot"] = True
    return config


def create_default_wwc_channel(project, user) -> Channel:
    existing_channel = _get_wwc_channel_by_config_flag(project.org, "preview")
    if existing_channel:
        return existing_channel

    channel = Channel.create(
        org=project.org,
        user=user,
        country=None,
        channel_type="WWC",
        name=DEFAULT_WWC_CHANNEL_NAME,
        address=str(project.project_uuid),
        config=_build_default_wwc_config(preview=True),
    )
    publish_channel_event(channel, action="create")
    return channel


def create_live_desk_copilot_channel(project, user) -> Channel:
    existing_channel = _get_wwc_channel_by_config_flag(project.org, "is_live_desk_copilot")
    if existing_channel:
        return existing_channel

    channel = Channel.create(
        org=project.org,
        user=user,
        country=None,
        channel_type="WWC",
        name=COPILOT_WWC_CHANNEL_NAME,
        address=f"{project.project_uuid}-copilot",
        config=_build_default_wwc_config(is_live_desk_copilot=True),
    )
    publish_channel_event(channel, action="create")
    return channel


def create_live_desk_copilot_channel(project, user) -> Channel:
    existing_channel = _get_wwc_channel_by_config_flag(
        project.org, "is_live_desk_copilot"
    )
    if existing_channel:
        return existing_channel

    channel = Channel.create(
        org=project.org,
        user=user,
        country=None,
        channel_type="WWC",
        name=COPILOT_WWC_CHANNEL_NAME,
        address=f"{project.project_uuid}-copilot",
        config=_build_default_wwc_config(is_live_desk_copilot=True),
    )
    publish_channel_event(channel, action="create")
    print(f"Channel published: {channel.uuid}")
    return channel
