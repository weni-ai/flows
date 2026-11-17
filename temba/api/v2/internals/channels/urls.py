from django.urls import path

from .views import (
    ChannelAllowedDomainsView,
    ChannelElevenLabsApiKeyView,
    ChannelMarketingTagsView,
    ChannelProjectView,
    ChannelSIPConnectionView,
    ChannelSIPCredentialsView,
    ChannelWabaMigrationView,
    InternalChannelView,
)

urlpatterns = [
    path("channel_projects", ChannelProjectView.as_view(), name="channel_projects"),
    path("channels-by-project", InternalChannelView.as_view(), name="channels-by-project"),
    path("channel_allowed_domains", ChannelAllowedDomainsView.as_view(), name="channel_allowed_domains"),
    path("elevenlabs_api_key", ChannelElevenLabsApiKeyView.as_view(), name="elevenlabs_api_key"),
    path("channel_marketing_tags", ChannelMarketingTagsView.as_view(), name="channel_marketing_tags"),
    path("channel_sip_connection", ChannelSIPConnectionView.as_view(), name="channel_sip_connection"),
    path("channel_sip_credentials", ChannelSIPCredentialsView.as_view(), name="channel_sip_credentials"),
    path("channel_waba_migration", ChannelWabaMigrationView.as_view(), name="channel_waba_migration"),
]
