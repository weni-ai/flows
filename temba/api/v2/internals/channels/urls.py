from django.urls import path

from .views import ChannelProjectView

urlpatterns = [path("channel_projects", ChannelProjectView.as_view(), name="channel_projects")]
