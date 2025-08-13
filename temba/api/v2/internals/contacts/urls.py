from django.urls import path

from .views import (
    ContactHasOpenTicketView,
    InternalContactFieldsEndpoint,
    InternalContactView,
    UpdateContactFieldsView,
    ContactsImportUploadView,
    ContactsImportConfirmView,
)

urlpatterns = [
    path("contacts", InternalContactView.as_view(), name="internal_contacts"),
    path("contacts_fields", InternalContactFieldsEndpoint.as_view(), name="internal_contacts_fields"),
    path("update_contacts_fields", UpdateContactFieldsView.as_view(), name="internal_update_contacts_fields"),
    path("contact_has_open_ticket", ContactHasOpenTicketView.as_view(), name="contact_has_open_ticket"),
    path("contacts_import_upload", ContactsImportUploadView.as_view(), name="internal_contacts_import_upload"),
    path("contacts_import_confirm", ContactsImportConfirmView.as_view(), name="internal_contacts_import_confirm"),
]
