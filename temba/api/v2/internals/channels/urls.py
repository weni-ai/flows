from django.urls import path

from .views import ChannelAllowedDomainsView, ChannelProjectView, InternalChannelView, LanguageByChannelView

urlpatterns = [
    path("channel_projects", ChannelProjectView.as_view(), name="channel_projects"),
    path("channels-by-project", InternalChannelView.as_view(), name="channels-by-project"),
    path("channel_allowed_domains", ChannelAllowedDomainsView.as_view(), name="channel_allowed_domains"),
    path("language_by_channel", LanguageByChannelView.as_view(), name="language-by-channel"),
]
