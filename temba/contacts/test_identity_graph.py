from django.db import IntegrityError, transaction

from temba.contacts.models import ContactAnchor, ContactURN
from temba.tests import TembaTest


class IdentityGraphTest(TembaTest):
    def test_new_urn_starts_not_attached(self):
        contact = self.create_contact("Ann", urns=["tel:+250788111000"])
        urn = contact.urns.get()
        self.assertEqual(urn.attachment_status, ContactURN.ATTACHMENT_NOT_ATTACHED)

    def test_anchor_is_unique_inside_the_org(self):
        first = self.create_contact("Ann", urns=["tel:+250788111001"])
        second = self.create_contact("Bob", urns=["tel:+250788111002"])
        ContactAnchor.objects.create(
            org=self.org,
            contact=first,
            anchor_type=ContactAnchor.ANCHOR_COMMERCE_USER_ID,
            value="store-user-42",
            verified=True,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ContactAnchor.objects.create(
                    org=self.org,
                    contact=second,
                    anchor_type=ContactAnchor.ANCHOR_COMMERCE_USER_ID,
                    value="store-user-42",
                    verified=True,
                )

    def test_same_anchor_value_is_allowed_in_another_org(self):
        first = self.create_contact("Ann", urns=["tel:+250788111003"])
        second = self.create_contact("Bob", urns=["tel:+250788111004"], org=self.org2)
        ContactAnchor.objects.create(
            org=self.org,
            contact=first,
            anchor_type=ContactAnchor.ANCHOR_COMMERCE_USER_ID,
            value="store-user-42",
            verified=True,
        )
        other = ContactAnchor.objects.create(
            org=self.org2,
            contact=second,
            anchor_type=ContactAnchor.ANCHOR_COMMERCE_USER_ID,
            value="store-user-42",
            verified=True,
        )
        self.assertEqual(other.org_id, self.org2.id)
