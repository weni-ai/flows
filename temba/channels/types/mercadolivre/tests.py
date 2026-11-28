import threading
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import connections
from django.urls import NoReverseMatch, reverse

from temba.campaigns.models import Campaign
from temba.channels.models import MERCADOLIVRE_CHANNEL_TYPE_CODE, Channel, ChannelAddressConflict
from temba.channels.types.mercadolivre.usecases import MERCADOLIVRE_CONTACT_FIELDS
from temba.contacts.models import URN, ContactField
from temba.orgs.models import Org
from temba.tests import TembaTest
from temba.tests.base import TembaNonAtomicTest
from temba.triggers.models import Trigger

SELLER_ID = "415458330"
OTHER_SELLER_ID = "415458331"
FIELD_KEYS = [key for key, label in MERCADOLIVRE_CONTACT_FIELDS]


def create_channel(org, user, address=SELLER_ID):
    return Channel.create(org, user, None, MERCADOLIVRE_CHANNEL_TYPE_CODE, name="Mercado Livre", address=address)


class MercadoLivreChannelUniquenessTest(TembaTest):
    def active_channels(self, address=SELLER_ID):
        return Channel.objects.filter(channel_type=MERCADOLIVRE_CHANNEL_TYPE_CODE, address=address, is_active=True)

    def test_first_channel_is_the_only_active_one_for_the_seller(self):
        channel = create_channel(self.org, self.admin)

        self.assertEqual(SELLER_ID, channel.address)
        self.assertEqual(["mercadolivre"], channel.schemes)
        self.assertEqual([channel], list(self.active_channels()))

    def test_duplicate_in_the_same_org_is_rejected(self):
        create_channel(self.org, self.admin)

        with self.assertRaises(ChannelAddressConflict) as ctx:
            create_channel(self.org, self.admin)

        self.assertEqual("address_conflict", ctx.exception.code)
        self.assertEqual(1, Channel.objects.filter(channel_type=MERCADOLIVRE_CHANNEL_TYPE_CODE).count())

    def test_duplicate_in_another_org_is_rejected_without_naming_the_holder(self):
        create_channel(self.org, self.admin)

        with self.assertRaises(ChannelAddressConflict) as ctx:
            create_channel(self.org2, self.admin2)

        self.assertEqual("address_conflict", ctx.exception.code)
        message = " ".join(ctx.exception.messages)
        for secret in (self.org.name, self.admin.username, self.admin.email, self.admin.first_name):
            if secret:
                self.assertNotIn(secret, message)
        self.assertEqual(1, Channel.objects.filter(channel_type=MERCADOLIVRE_CHANNEL_TYPE_CODE).count())

    def test_transaction_survives_a_rejected_duplicate(self):
        create_channel(self.org, self.admin)

        with self.assertRaises(ChannelAddressConflict):
            create_channel(self.org2, self.admin2)

        # the caller can keep using the connection after the conflict
        channel = create_channel(self.org2, self.admin2, OTHER_SELLER_ID)
        self.assertEqual(OTHER_SELLER_ID, channel.address)

    def test_same_seller_can_be_connected_again_after_release(self):
        first = create_channel(self.org, self.admin)
        first.release(self.admin)

        second = create_channel(self.org2, self.admin2)

        self.assertEqual([second], list(self.active_channels()))
        self.assertFalse(Channel.objects.get(id=first.id).is_active)

    def test_two_sellers_do_not_conflict(self):
        first = create_channel(self.org, self.admin, SELLER_ID)
        second = create_channel(self.org, self.admin, OTHER_SELLER_ID)

        self.assertEqual([first], list(self.active_channels(SELLER_ID)))
        self.assertEqual([second], list(self.active_channels(OTHER_SELLER_ID)))

    def test_rule_does_not_apply_to_other_channel_types(self):
        first = Channel.create(
            self.org, self.admin, None, "IG", name="Instagram", address="123", schemes=["instagram"]
        )
        second = Channel.create(
            self.org2, self.admin2, None, "IG", name="Instagram", address="123", schemes=["instagram"]
        )

        self.assertNotEqual(first.id, second.id)


class MercadoLivreAddressRaceTest(TembaNonAtomicTest):
    def setUp(self):
        super().setUp()
        self.setUpOrgs()

    def test_two_simultaneous_connections_for_one_seller_create_one_channel(self):
        org_ids = [self.org.id, self.org2.id]
        user_ids = [self.admin.id, self.admin2.id]
        results = [None, None]
        barrier = threading.Barrier(2)

        def worker(index):
            connections.close_all()
            try:
                barrier.wait(timeout=5)
                org = Org.objects.get(id=org_ids[index])
                user = User.objects.get(id=user_ids[index])
                results[index] = create_channel(org, user)
            except Exception as exc:  # pragma: no cover - asserted below
                results[index] = exc
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)
            self.assertFalse(thread.is_alive())

        channels = list(Channel.objects.filter(channel_type=MERCADOLIVRE_CHANNEL_TYPE_CODE, address=SELLER_ID))
        self.assertEqual(1, len(channels))
        self.assertEqual(1, len([item for item in results if isinstance(item, Channel)]))
        failures = [item for item in results if isinstance(item, ChannelAddressConflict)]
        self.assertEqual(1, len(failures))
        self.assertEqual("address_conflict", failures[0].code)

        # the rejected attempt leaves no extra fields: each key exists once, in the org of the channel that won
        for key in FIELD_KEYS:
            self.assertEqual(1, ContactField.user_fields.filter(key=key, is_active=True).count())


class MercadoLivreContactFieldsTest(TembaTest):
    def active_fields(self, org, key=None):
        fields = ContactField.user_fields.active_for_org(org=org)
        return fields.filter(key=key) if key else fields.filter(key__in=FIELD_KEYS)

    def test_channel_creates_the_seven_text_fields(self):
        self.assertEqual(0, self.active_fields(self.org).count())

        create_channel(self.org, self.admin)

        fields = {field.key: field for field in self.active_fields(self.org)}
        self.assertEqual(
            ["ml_kind", "ml_buyer_id", "ml_nickname", "ml_pack_id", "ml_order_ids", "ml_item_id", "ml_question_id"],
            FIELD_KEYS,
        )
        self.assertEqual(set(FIELD_KEYS), set(fields))
        for field in fields.values():
            self.assertEqual(ContactField.TYPE_TEXT, field.value_type)

    def test_existing_field_is_reused_unchanged(self):
        existing = ContactField.get_or_create(
            self.org, self.admin, "ml_pack_id", label="Pack Number", value_type=ContactField.TYPE_NUMBER
        )

        create_channel(self.org, self.admin)

        existing.refresh_from_db()
        self.assertEqual("Pack Number", existing.label)
        self.assertEqual(ContactField.TYPE_NUMBER, existing.value_type)
        self.assertEqual(1, self.active_fields(self.org, "ml_pack_id").count())
        self.assertEqual(7, self.active_fields(self.org).count())

    def test_second_channel_does_not_duplicate_the_fields(self):
        create_channel(self.org, self.admin, SELLER_ID)
        ids = set(self.active_fields(self.org).values_list("id", flat=True))

        create_channel(self.org, self.admin, OTHER_SELLER_ID)

        self.assertEqual(7, self.active_fields(self.org).count())
        self.assertEqual(ids, set(self.active_fields(self.org).values_list("id", flat=True)))

    def test_other_orgs_are_not_touched(self):
        create_channel(self.org, self.admin)

        self.assertEqual(0, self.active_fields(self.org2).count())

    def test_org_at_its_field_limit_keeps_the_channel_and_skips_the_fields(self):
        # room for three of the seven fields
        self.org.limits = {Org.LIMIT_FIELDS: ContactField.user_fields.count_active_for_org(org=self.org) + 3}
        self.org.save(update_fields=("limits",))

        with self.assertLogs("temba.channels.types.mercadolivre.usecases", level="WARNING") as logs:
            with patch("temba.channels.types.mercadolivre.usecases.capture_message") as mock_capture:
                channel = create_channel(self.org, self.admin)

        self.assertTrue(Channel.objects.get(id=channel.id).is_active)
        self.assertEqual(3, self.active_fields(self.org).count())

        # the warning carries the opaque org id and nothing else about the org or the seller
        self.assertEqual(1, len(logs.output))
        self.assertIn(str(self.org.id), logs.output[0])
        self.assertNotIn(self.org.name, logs.output[0])
        self.assertNotIn(SELLER_ID, logs.output[0])
        mock_capture.assert_called_once()
        self.assertNotIn(self.org.name, mock_capture.call_args[0][0])
        self.assertEqual("warning", mock_capture.call_args[1]["level"])

    def test_release_keeps_the_fields_and_their_values(self):
        channel = create_channel(self.org, self.admin)
        contact = self.create_contact("Buyer", urns=["mercadolivre:162981404"])
        self.set_contact_field(contact, "ml_pack_id", "2000000089077943")

        channel.release(self.admin)

        self.assertEqual(7, self.active_fields(self.org).count())
        contact.refresh_from_db()
        self.assertEqual(
            "2000000089077943", contact.get_field_value(ContactField.user_fields.get(org=self.org, key="ml_pack_id"))
        )


class MercadoLivreTypeTest(TembaTest):
    def test_type_attributes_match_the_contract(self):
        channel_type = Channel.get_type_from_code("ML")

        self.assertEqual("ML", channel_type.code)
        self.assertEqual("Mercado Livre", channel_type.name)
        self.assertEqual("mercadolivre", channel_type.slug)
        self.assertEqual([URN.MERCADOLIVRE_SCHEME], channel_type.schemes)
        self.assertEqual("mercadolivre", URN.MERCADOLIVRE_SCHEME)
        self.assertEqual(r"^ml/receive", channel_type.courier_url)
        self.assertEqual(350, channel_type.max_length)
        self.assertTrue(channel_type.attachment_support)
        self.assertEqual(channel_type.Category.SOCIAL_MEDIA, channel_type.category)
        self.assertFalse(channel_type.show_config_page)
        self.assertFalse(channel_type.has_claim_view())
        self.assertEqual([], channel_type.get_urls())

    def test_numeric_address_creates_a_channel_with_the_scheme(self):
        channel = create_channel(self.org, self.admin)

        self.assertEqual("ML", channel.channel_type)
        self.assertEqual(SELLER_ID, channel.address)
        self.assertEqual(["mercadolivre"], channel.schemes)
        self.assertEqual({}, channel.config)

    def test_invalid_addresses_are_rejected_and_create_no_channel(self):
        for address in ("", "   ", None, 415458330, "abc", "41545 8330", "4154-58330", "+415458330", "4" * 256):
            with self.subTest(address=address):
                with self.assertRaises(ValidationError):
                    create_channel(self.org, self.admin, address)

        self.assertEqual(0, Channel.objects.filter(channel_type="ML").count())
        self.assertEqual(0, ContactField.user_fields.filter(key__in=FIELD_KEYS).count())

    def test_address_is_stripped_and_longest_valid_address_is_accepted(self):
        channel = create_channel(self.org, self.admin, f" {SELLER_ID}\n")
        self.assertEqual(SELLER_ID, channel.address)

        channel = create_channel(self.org, self.admin, "4" * 255)
        self.assertEqual("4" * 255, channel.address)

    def test_whitespace_around_the_address_is_the_same_seller(self):
        create_channel(self.org, self.admin, SELLER_ID)

        with self.assertRaises(ChannelAddressConflict):
            create_channel(self.org2, self.admin2, f"  {SELLER_ID} ")

    def test_other_types_keep_their_address(self):
        channel = Channel.create(
            self.org, self.admin, None, "IG", name="Instagram", address=" 019283 ", schemes=["instagram"]
        )

        self.assertEqual(" 019283 ", channel.address)

    def test_claim_page_and_channel_list_work_without_a_claim_view(self):
        create_channel(self.org, self.admin)
        self.login(self.admin)

        response = self.client.get(reverse("channels.channel_claim"))
        self.assertEqual(200, response.status_code)
        self.assertNotContains(response, "Mercado Livre")

        with self.assertRaises(NoReverseMatch):
            reverse("channels.types.mercadolivre.claim")

        response = self.client.get(reverse("channels.channel_list"), follow=True)
        self.assertEqual(200, response.status_code)

    def test_channel_works_in_an_org_without_flows_triggers_or_campaigns(self):
        self.assertEqual(0, self.org.flows.count())
        self.assertEqual(0, Trigger.objects.filter(org=self.org).count())
        self.assertEqual(0, Campaign.objects.filter(org=self.org).count())

        channel = create_channel(self.org, self.admin)

        self.assertTrue(channel.is_active)
        self.assertEqual(7, ContactField.user_fields.filter(org=self.org, key__in=FIELD_KEYS).count())
