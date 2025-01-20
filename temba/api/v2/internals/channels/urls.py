from django.urls import path

from .views import ChannelProjectView, ChannelAllowedDomainsView

urlpatterns = [path("channel_projects", ChannelProjectView.as_view(), name="channel_projects")]

urlpatterns.append(
    path("channel_allowed_domains", ChannelAllowedDomainsView.as_view(), name="channel_allowed_domains")
)
