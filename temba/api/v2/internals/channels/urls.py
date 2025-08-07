from django.urls import path

from .views import ChannelAllowedDomainsView, ChannelProjectView, InternalChannelView

urlpatterns = [
    path("channel_projects", ChannelProjectView.as_view(), name="channel_projects"),
    path("channels", InternalChannelView.as_view(), name="channels"),
]

urlpatterns.append(
    path(
        "channel_allowed_domains",
        ChannelAllowedDomainsView.as_view(),
        name="channel_allowed_domains",
    )
)
