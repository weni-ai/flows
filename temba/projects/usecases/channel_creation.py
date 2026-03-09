from django.conf import settings

from temba.channels.models import Channel

DEFAULT_WWC_CHANNEL_NAME = "Weni Web Chat - Preview"


def create_default_wwc_channel(project, user) -> Channel:
    existing_channel = Channel.objects.filter(org=project.org, channel_type="WWC").first()
    if existing_channel and existing_channel.config.get("preview"):
        return existing_channel

    return Channel.create(
        org=project.org,
        user=user,
        country=None,
        channel_type="WWC",
        name=DEFAULT_WWC_CHANNEL_NAME,
        address=str(project.project_uuid),
        config={"preview": True, "version": 2, "allowd_domains": [settings.WENI_WEBCHAT_ALLOWED_DOMAINS]},
    )
