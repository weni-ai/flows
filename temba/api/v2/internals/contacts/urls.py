from django.urls import path

from .views import InternalContactFieldsEndpoint, InternalContactView

urlpatterns = [
    path("contacts", InternalContactView.as_view(), name="internal_contacts"),
    path("contacts_fields", InternalContactFieldsEndpoint.as_view(), name="internal_contacts_fields"),
]
