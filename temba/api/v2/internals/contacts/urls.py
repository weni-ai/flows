from django.urls import path

from .views import (
    ContactHasOpenTicketView,
    ContactsImportConfirmView,
    ContactsImportUploadView,
    ContactsWithMessagesView,
    GroupsContactFieldsView,
    InternalContactFieldsEndpoint,
    InternalContactGroupsView,
    InternalContactView,
    UpdateContactFieldsView,
)

urlpatterns = [
    path("contacts", InternalContactView.as_view(), name="internal_contacts"),
    path("contacts_fields", InternalContactFieldsEndpoint.as_view(), name="internal_contacts_fields"),
    path("update_contacts_fields", UpdateContactFieldsView.as_view(), name="internal_update_contacts_fields"),
    path("contact_has_open_ticket", ContactHasOpenTicketView.as_view(), name="contact_has_open_ticket"),
    path("contacts_with_messages", ContactsWithMessagesView.as_view(), name="contacts_with_messages"),
    path("contact_groups", InternalContactGroupsView.as_view(), name="internal_contact_groups"),
    path("contacts_import_upload", ContactsImportUploadView.as_view(), name="internal_contacts_import_upload"),
    path(
        "contacts_import_confirm/<int:import_id>/",
        ContactsImportConfirmView.as_view(),
        name="internal_contacts_import_confirm",
    ),
    path("groups_contact_fields", GroupsContactFieldsView.as_view(), name="groups_contact_fields"),
]
