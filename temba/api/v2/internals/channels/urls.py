from django.urls import path

from .views import ChannelAllowedDomainsView, ChannelElevenLabsApiKeyView, ChannelProjectView, InternalChannelView

urlpatterns = [
    path("channel_projects", ChannelProjectView.as_view(), name="channel_projects"),
    path("channels-by-project", InternalChannelView.as_view(), name="channels-by-project"),
    path("channel_allowed_domains", ChannelAllowedDomainsView.as_view(), name="channel_allowed_domains"),
    path("elevenlabs_api_key", ChannelElevenLabsApiKeyView.as_view(), name="elevenlabs_api_key"),
]
