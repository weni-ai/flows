from django.urls import path

from .views import InternalFirstContactsView, InternalMessagesView, MsgStreamView

urlpatterns = [
    path("messages", InternalMessagesView.as_view(), name="internal_messages"),
    path("messages/stream", MsgStreamView.as_view(), name="internal_messages_stream"),
    path("messages/first_contacts", InternalFirstContactsView.as_view(), name="internal_first_contacts"),
]
