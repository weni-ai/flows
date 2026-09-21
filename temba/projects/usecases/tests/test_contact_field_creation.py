import uuid

import pytz
from weni.internal.models import Project

from django.conf import settings

from temba.contacts.models import ContactField
from temba.projects.usecases.contact_field_creation import (
    ORIGINAL_CONTACT_URN_KEY,
    ORIGINAL_CONTACT_URN_LABEL,
    SELLER_EMAIL_KEY,
    SELLER_EMAIL_LABEL,
    create_live_desk_copilot_contact_fields,
)
from temba.tests.base import TembaTest


class ContactFieldCreationTestCase(TembaTest):
    def test_create_live_desk_copilot_contact_fields(self):
        project = Project.objects.create(
            project_uuid=uuid.uuid4(),
            name="Projeto Copilot",
            timezone=pytz.timezone("Africa/Kigali"),
            brand=settings.DEFAULT_BRAND,
            created_by=self.user,
            modified_by=self.user,
        )

        fields = create_live_desk_copilot_contact_fields(project, self.user)

        self.assertEqual(len(fields), 2)

        original_contact_urn = ContactField.user_fields.active_for_org(org=project.org).get(
            key=ORIGINAL_CONTACT_URN_KEY
        )
        seller_email = ContactField.user_fields.active_for_org(org=project.org).get(key=SELLER_EMAIL_KEY)

        self.assertEqual(original_contact_urn.label, ORIGINAL_CONTACT_URN_LABEL)
        self.assertEqual(original_contact_urn.value_type, ContactField.TYPE_TEXT)
        self.assertFalse(original_contact_urn.show_in_table)

        self.assertEqual(seller_email.label, SELLER_EMAIL_LABEL)
        self.assertEqual(seller_email.value_type, ContactField.TYPE_TEXT)
        self.assertFalse(seller_email.show_in_table)

    def test_create_live_desk_copilot_contact_fields_is_idempotent(self):
        project = Project.objects.create(
            project_uuid=uuid.uuid4(),
            name="Projeto Copilot",
            timezone=pytz.timezone("Africa/Kigali"),
            brand=settings.DEFAULT_BRAND,
            created_by=self.user,
            modified_by=self.user,
        )

        first_fields = create_live_desk_copilot_contact_fields(project, self.user)
        second_fields = create_live_desk_copilot_contact_fields(project, self.user)

        self.assertEqual(first_fields[0].id, second_fields[0].id)
        self.assertEqual(first_fields[1].id, second_fields[1].id)
        self.assertEqual(
            ContactField.user_fields.active_for_org(org=project.org)
            .filter(key__in=[ORIGINAL_CONTACT_URN_KEY, SELLER_EMAIL_KEY])
            .count(),
            2,
        )
