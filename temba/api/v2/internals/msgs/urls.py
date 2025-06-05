from django.urls import path

from .views import InternalMessagesView

urlpatterns = [path("messages", InternalMessagesView.as_view(), name="internal_messages")]
