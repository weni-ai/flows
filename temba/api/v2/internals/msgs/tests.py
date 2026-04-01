from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from temba.api.v2.internals.msgs.views import FirstContactsPagination
from temba.channels.models import Channel
from temba.msgs.models import Msg
from temba.tests.base import TembaTest

User = get_user_model()


class TestInternalMessages(TembaTest):
    def setUp(self):
        super().setUp()
        self.org.proj_uuid = uuid4()
        self.org.save()

    @patch("temba.api.v2.internals.msgs.views.InternalMessagesView.authentication_classes", [])
    @patch("temba.api.v2.internals.msgs.views.InternalMessagesView.permission_classes", [])
    def test_list_messages_success(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            contact = self.create_contact("Junior", urns=["tel:+250788123123"])
            msg1 = self.create_incoming_msg(
                contact=contact,
                text="Test message 1",
                status="H",
            )
            msg2 = self.create_outgoing_msg(
                contact=contact,
                text="Test message 2",
                status="S",
            )

            url = f"{reverse('internal_messages')}?project_uuid={self.org.proj_uuid}"
            response = self.client.get(url)

            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]["id"], msg2.id)
            self.assertEqual(results[0]["text"], "Test message 2")
            self.assertEqual(results[0]["direction"], "out")
            self.assertEqual(results[1]["id"], msg1.id)
            self.assertEqual(results[1]["text"], "Test message 1")
            self.assertEqual(results[1]["direction"], "in")

    @patch("temba.api.v2.internals.msgs.views.InternalMessagesView.authentication_classes", [])
    @patch("temba.api.v2.internals.msgs.views.InternalMessagesView.permission_classes", [])
    def test_list_messages_with_filters(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            contact = self.create_contact("Junior", urns=["tel:+250788123123"])
            msg1 = self.create_incoming_msg(
                contact=contact,
                text="Test inbox",
                msg_type="I",
                status="H",
                channel=self.channel,
            )
            self.create_outgoing_msg(
                contact=contact,
                text="Test flow",
                msg_type="F",
                status="S",
            )

            response = self.client.get(
                f"{reverse('internal_messages')}?project_uuid={self.org.proj_uuid}&folder=inbox"
            )
            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["id"], msg1.id)

            response = self.client.get(
                f"{reverse('internal_messages')}?project_uuid={self.org.proj_uuid}&contact={contact.uuid}"
            )
            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 2)

            # Test invalid folder
            response = self.client.get(
                f"{reverse('internal_messages')}?project_uuid={self.org.proj_uuid}&folder=invalid_folder"
            )
            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 0)  # Should return empty list due to pk=-1 filter

            # Test get messages by channel_uuid
            response = self.client.get(
                f"{reverse('internal_messages')}?project_uuid={self.org.proj_uuid}&channel_uuid={self.channel.uuid}"
            )
            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 2)

    @patch("temba.api.v2.internals.msgs.views.InternalMessagesView.authentication_classes", [])
    @patch("temba.api.v2.internals.msgs.views.InternalMessagesView.permission_classes", [])
    def test_list_messages_no_org(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            # Test missing project_uuid
            url = reverse("internal_messages")
            response = self.client.get(url)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json(), {"error": "Project not provided"})

            # Test invalid project_uuid
            url = f"{reverse('internal_messages')}?project_uuid={uuid4()}"
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"error": "Project not found"})

    @patch("temba.api.v2.internals.msgs.views.InternalMessagesView.authentication_classes", [])
    @patch("temba.api.v2.internals.msgs.views.InternalMessagesView.permission_classes", [])
    def test_list_messages_pagination(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            contact = self.create_contact("Junior", urns=["tel:+250788123123"])

            for i in range(15):
                self.create_incoming_msg(
                    contact=contact,
                    text=f"Test message {i}",
                    status="H",
                )

            response = self.client.get(f"{reverse('internal_messages')}?project_uuid={self.org.proj_uuid}")
            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 10)
            self.assertIsNotNone(response.json()["next"])

            # Test invalid limit parameter
            response = self.client.get(
                f"{reverse('internal_messages')}?project_uuid={self.org.proj_uuid}&limit=invalid"
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["results"]), 10)  # Should use default limit

            # Test custom limit
            response = self.client.get(f"{reverse('internal_messages')}?project_uuid={self.org.proj_uuid}&limit=5")
            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 5)

    @patch("temba.api.v2.internals.msgs.views.InternalMessagesView.authentication_classes", [])
    @patch("temba.api.v2.internals.msgs.views.InternalMessagesView.permission_classes", [])
    def test_list_messages_with_date_filters(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            contact = self.create_contact("Junior", urns=["tel:+250788123123"])
            now = timezone.now()

            # Create a message in the past
            past_date = now - timezone.timedelta(days=2)
            past_msg = self.create_outgoing_msg(
                contact=contact,
                text="Past message",
                status="S",
                created_on=past_date,
            )

            # Create a message in the future
            future_date = now + timezone.timedelta(days=2)
            future_msg = self.create_outgoing_msg(
                contact=contact,
                text="Future message",
                status="S",
                created_on=future_date,
            )

            # Test after filter for non-incoming messages
            after_date = timezone.localtime(now - timezone.timedelta(days=1))
            params = {"project_uuid": self.org.proj_uuid, "after": after_date.isoformat()}
            response = self.client.get(f"{reverse('internal_messages')}?{urlencode(params)}")
            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 1)  # Should only get the future message
            self.assertEqual(results[0]["id"], future_msg.id)

            # Test before filter for non-incoming messages
            before_date = timezone.localtime(now + timezone.timedelta(days=1))
            params = {"project_uuid": self.org.proj_uuid, "before": before_date.isoformat()}
            response = self.client.get(f"{reverse('internal_messages')}?{urlencode(params)}")
            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 1)  # Should only get the past message
            self.assertEqual(results[0]["id"], past_msg.id)

    @patch("temba.api.v2.internals.msgs.views.InternalMessagesView.authentication_classes", [])
    @patch("temba.api.v2.internals.msgs.views.InternalMessagesView.permission_classes", [])
    def test_list_messages_with_urn_filters(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            contact = self.create_contact("Junior", urns=["tel:+250788123123"])
            self.create_incoming_msg(
                contact=contact,
                text="Test message",
                status="H",
            )

            # Test with valid URN
            response = self.client.get(
                f"{reverse('internal_messages')}?project_uuid={self.org.proj_uuid}&contact_urn=tel:+250788123123"
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["results"]), 1)

            # Test with invalid URN format
            response = self.client.get(
                f"{reverse('internal_messages')}?project_uuid={self.org.proj_uuid}&contact_urn=invalid"
            )
            self.assertEqual(response.status_code, 400)

            # Test with anonymous org
            self.org.is_anon = True
            self.org.save()

            response = self.client.get(
                f"{reverse('internal_messages')}?project_uuid={self.org.proj_uuid}&contact_urn=tel:+250788123123"
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"detail": "URN lookups not allowed for anonymous organizations"})

    @patch("temba.api.v2.internals.msgs.views.InternalMessagesView.authentication_classes", [])
    @patch("temba.api.v2.internals.msgs.views.InternalMessagesView.permission_classes", [])
    def test_list_incoming_messages_with_date_filters(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            contact = self.create_contact("Junior", urns=["tel:+250788123123"])
            now = timezone.now()

            past_date = now - timezone.timedelta(days=2)
            past_msg = self.create_incoming_msg(
                contact=contact,
                text="Past message",
                status="H",
                created_on=past_date,
                msg_type="I",
            )
            past_msg.direction = "I"
            past_msg.modified_on = past_date
            past_msg.save(update_fields=["modified_on", "direction"])

            future_date = now + timezone.timedelta(days=2)
            future_msg = self.create_incoming_msg(
                contact=contact,
                text="Future message",
                status="H",
                created_on=future_date,
                msg_type="I",
            )
            future_msg.direction = "I"
            future_msg.modified_on = future_date
            future_msg.save(update_fields=["modified_on", "direction"])

            # Test after filter for incoming messages folder
            after_date = timezone.localtime(now - timezone.timedelta(days=1))
            params = {"project_uuid": self.org.proj_uuid, "folder": "incoming", "after": after_date.isoformat()}
            response = self.client.get(f"{reverse('internal_messages')}?{urlencode(params)}")
            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]["id"], future_msg.id)

            before_date = timezone.localtime(now + timezone.timedelta(days=1))
            params = {"project_uuid": self.org.proj_uuid, "folder": "incoming", "before": before_date.isoformat()}
            response = self.client.get(f"{reverse('internal_messages')}?{urlencode(params)}")
            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 2)

    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.authentication_classes", [])
    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.permission_classes", [])
    def test_stream_create_incoming_with_contact_uuid(self):
        contact = self.create_contact("Alice", urns=["tel:+250788000111"])
        payload = {
            "project_uuid": str(self.org.proj_uuid),
            "direction": "in",
            "contact_uuid": str(contact.uuid),
            "text": "Olá!",
        }
        response = self.client.post(reverse("internal_messages_stream"), data=payload, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        msg = Msg.objects.get(id=response.json()["ids"][0])
        self.assertEqual(msg.direction, Msg.DIRECTION_IN)
        self.assertEqual(msg.status, Msg.STATUS_HANDLED)

    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.authentication_classes", [])
    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.permission_classes", [])
    def test_stream_create_outgoing_default_sent(self):
        contact = self.create_contact("Bob", urns=["tel:+250788000222"])
        payload = {
            "project_uuid": str(self.org.proj_uuid),
            "direction": "out",
            "contact_uuid": str(contact.uuid),
            "text": "Hey!",
        }
        response = self.client.post(reverse("internal_messages_stream"), data=payload, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        created = Msg.objects.get(id=response.json()["ids"][0])
        self.assertEqual(created.direction, Msg.DIRECTION_OUT)
        self.assertEqual(created.status, Msg.STATUS_SENT)
        self.assertIsNotNone(created.sent_on)

    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.authentication_classes", [])
    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.permission_classes", [])
    def test_stream_create_with_urn_only(self):
        contact = self.create_contact("Carol", urns=["tel:+250788000333"])
        payload = {
            "project_uuid": str(self.org.proj_uuid),
            "direction": "in",
            "urns": ["tel:+250788000333"],
            "text": "ping",
        }
        response = self.client.post(reverse("internal_messages_stream"), data=payload, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        msg = Msg.objects.get(id=response.json()["ids"][0])
        self.assertEqual(msg.contact_id, contact.id)
        self.assertEqual(msg.direction, Msg.DIRECTION_IN)

    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.authentication_classes", [])
    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.permission_classes", [])
    def test_stream_labels_association(self):
        contact = self.create_contact("Dora", urns=["tel:+250788000444"])
        label = self.create_label("demo")
        payload = {
            "project_uuid": str(self.org.proj_uuid),
            "direction": "out",
            "contact_uuid": str(contact.uuid),
            "text": "with label",
            "labels": [str(label.uuid)],
        }
        response = self.client.post(reverse("internal_messages_stream"), data=payload, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        msg = Msg.objects.get(id=response.json()["ids"][0])
        self.assertEqual(list(msg.labels.all()), [label])

    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.authentication_classes", [])
    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.permission_classes", [])
    def test_stream_channel_override_validation(self):
        # create a channel in a different org
        other_channel = Channel.create(
            self.org2,
            self.admin2,
            "RW",
            "A",
            name="Other Channel",
            address="+250789000999",
            device="Test",
            secret="xyz",
            config={},
        )
        contact = self.create_contact("Eve", urns=["tel:+250788000555"])
        payload = {
            "project_uuid": str(self.org.proj_uuid),
            "direction": "out",
            "contact_uuid": str(contact.uuid),
            "text": "wrong channel",
            "channel_uuid": str(other_channel.uuid),
        }
        response = self.client.post(reverse("internal_messages_stream"), data=payload, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Channel not found", response.json()["error"])

    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.authentication_classes", [])
    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.permission_classes", [])
    def test_stream_missing_identifiers(self):
        payload = {
            "project_uuid": str(self.org.proj_uuid),
            "direction": "out",
            "text": "no identifiers",
        }
        response = self.client.post(reverse("internal_messages_stream"), data=payload, content_type="application/json")
        self.assertEqual(response.status_code, 400)

    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.authentication_classes", [])
    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.permission_classes", [])
    def test_stream_missing_content(self):
        contact = self.create_contact("Frank", urns=["tel:+250788000666"])
        payload = {
            "project_uuid": str(self.org.proj_uuid),
            "direction": "out",
            "contact_uuid": str(contact.uuid),
        }
        response = self.client.post(reverse("internal_messages_stream"), data=payload, content_type="application/json")
        self.assertEqual(response.status_code, 400)

    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.authentication_classes", [])
    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.permission_classes", [])
    def test_stream_invalid_urn(self):
        contact = self.create_contact("Grace", urns=["tel:+250788000777"])
        payload = {
            "project_uuid": str(self.org.proj_uuid),
            "direction": "in",
            "contact_uuid": str(contact.uuid),
            "urns": ["invalid-urn"],
            "text": "hi",
        }
        response = self.client.post(reverse("internal_messages_stream"), data=payload, content_type="application/json")
        self.assertEqual(response.status_code, 400)

    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.authentication_classes", [])
    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.permission_classes", [])
    def test_stream_project_not_found(self):
        contact = self.create_contact("Hank", urns=["tel:+250788000888"])
        payload = {
            "project_uuid": str(uuid4()),
            "direction": "out",
            "contact_uuid": str(contact.uuid),
            "text": "hi",
        }
        response = self.client.post(reverse("internal_messages_stream"), data=payload, content_type="application/json")
        self.assertEqual(response.status_code, 404)


def _patch_first_contacts_auth(func):
    @patch(
        "temba.api.v2.internals.msgs.views.InternalFirstContactsView.authentication_classes",
        [],
    )
    @patch(
        "temba.api.v2.internals.msgs.views.InternalFirstContactsView.permission_classes",
        [],
    )
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


class TestInternalFirstContacts(TembaTest):
    def setUp(self):
        super().setUp()
        self.org.proj_uuid = uuid4()
        self.org.save()

        self.mock_user = MagicMock(spec=User)
        self.mock_user.is_authenticated = True
        self.mock_user.email = "mockuser@example.com"

    def _url(self, **params):
        base = reverse("internal_first_contacts")
        defaults = {
            "project_uuid": str(self.org.proj_uuid),
            "channel_uuid": str(self.channel.uuid),
            "after": "2026-01-01T00:00:00Z",
            "before": "2026-12-31T23:59:59Z",
        }
        defaults.update({k: v if isinstance(v, str) else str(v) for k, v in params.items()})
        # urlencode so e.g. timezone.now().isoformat() '+' is not decoded as space in query strings
        return f"{base}?{urlencode(defaults)}"

    @_patch_first_contacts_auth
    def test_first_contacts_success(self):
        with patch("rest_framework.request.Request.user", self.mock_user):
            contact = self.create_contact("Alice", urns=["tel:+250788000001"])
            self.create_incoming_msg(contact=contact, text="Hello", status="H", channel=self.channel)

            response = self.client.get(self._url())

            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 1)
            self.assertIn("contact_urn_identity", results[0])
            self.assertIn("first_created_on", results[0])

    @_patch_first_contacts_auth
    def test_first_contacts_distinct_per_urn(self):
        with patch("rest_framework.request.Request.user", self.mock_user):
            contact = self.create_contact("Alice", urns=["tel:+250788000001"])
            now = timezone.now()
            earlier = now - timezone.timedelta(hours=2)

            self.create_incoming_msg(
                contact=contact, text="First", status="H", channel=self.channel, created_on=earlier
            )
            self.create_incoming_msg(contact=contact, text="Second", status="H", channel=self.channel, created_on=now)

            response = self.client.get(self._url())

            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 1)

    @_patch_first_contacts_auth
    def test_first_contacts_excludes_outgoing(self):
        with patch("rest_framework.request.Request.user", self.mock_user):
            contact = self.create_contact("Alice", urns=["tel:+250788000001"])
            self.create_outgoing_msg(contact=contact, text="Outgoing", status="S", channel=self.channel)

            response = self.client.get(self._url())

            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 0)

    @_patch_first_contacts_auth
    def test_first_contacts_queryset_excludes_failed_errored_statuses(self):
        """
        Incoming messages with F/E cannot be inserted (temba_msg_on_change); assert the API queryset
        still applies .exclude for those statuses (defense in depth / legacy rows).
        """
        captured = []
        _real_paginate = FirstContactsPagination.paginate_queryset

        def track_paginate(paginator, queryset, request, view=None):
            captured.append(queryset)
            return _real_paginate(paginator, queryset, request, view=view)

        with patch("rest_framework.request.Request.user", self.mock_user):
            contact = self.create_contact("Alice", urns=["tel:+250788000001"])
            self.create_incoming_msg(contact=contact, text="Hello", status="H", channel=self.channel)

            with patch.object(FirstContactsPagination, "paginate_queryset", track_paginate):
                response = self.client.get(self._url())

            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(captured), 1)
            sql = str(captured[0].query)
            self.assertIn("NOT", sql)
            self.assertRegex(sql, r'"msgs_msg"\."status" IN \(F, E\)|"msgs_msg"\."status" IN \(E, F\)')

    @_patch_first_contacts_auth
    def test_first_contacts_filters_by_channel(self):
        with patch("rest_framework.request.Request.user", self.mock_user):
            other_channel = self.create_channel("TG", "Telegram", "+250785551212")
            contact = self.create_contact("Alice", urns=["tel:+250788000001"])

            self.create_incoming_msg(contact=contact, text="On other channel", status="H", channel=other_channel)

            response = self.client.get(self._url())

            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 0)

    @_patch_first_contacts_auth
    def test_first_contacts_filters_by_date_range(self):
        with patch("rest_framework.request.Request.user", self.mock_user):
            contact = self.create_contact("Alice", urns=["tel:+250788000001"])
            old_date = timezone.now() - timezone.timedelta(days=365)

            self.create_incoming_msg(
                contact=contact, text="Old msg", status="H", channel=self.channel, created_on=old_date
            )

            after = (timezone.now() - timezone.timedelta(days=1)).isoformat()
            before = (timezone.now() + timezone.timedelta(days=1)).isoformat()

            response = self.client.get(self._url(after=after, before=before))

            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 0)

    @_patch_first_contacts_auth
    def test_first_contacts_missing_project_uuid(self):
        with patch("rest_framework.request.Request.user", self.mock_user):
            url = (
                f"{reverse('internal_first_contacts')}"
                f"?channel_uuid={self.channel.uuid}&after=2026-01-01T00:00:00Z&before=2026-12-31T23:59:59Z"
            )
            response = self.client.get(url)

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"error": "project_uuid is required"})

    @_patch_first_contacts_auth
    def test_first_contacts_invalid_project_uuid(self):
        with patch("rest_framework.request.Request.user", self.mock_user):
            response = self.client.get(self._url(project_uuid=uuid4()))

            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"error": "Project not found"})

    @_patch_first_contacts_auth
    def test_first_contacts_missing_required_params(self):
        with patch("rest_framework.request.Request.user", self.mock_user):
            base = reverse("internal_first_contacts")
            proj = f"project_uuid={self.org.proj_uuid}"

            response = self.client.get(f"{base}?{proj}&after=2026-01-01&before=2026-12-31")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"error": "channel_uuid is required"})

            response = self.client.get(f"{base}?{proj}&channel_uuid={self.channel.uuid}&before=2026-12-31")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"error": "after is required"})

            response = self.client.get(f"{base}?{proj}&channel_uuid={self.channel.uuid}&after=2026-01-01")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"error": "before is required"})

    @_patch_first_contacts_auth
    def test_first_contacts_pagination(self):
        with patch("rest_framework.request.Request.user", self.mock_user):
            for i in range(5):
                contact = self.create_contact(f"Contact{i}", urns=[f"tel:+25078800000{i}"])
                self.create_incoming_msg(contact=contact, text=f"Msg {i}", status="H", channel=self.channel)

            response = self.client.get(self._url() + "&limit=2")

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data["results"]), 2)
            self.assertIsNotNone(data["next"])

            response2 = self.client.get(data["next"])
            self.assertEqual(response2.status_code, 200)
            self.assertEqual(len(response2.json()["results"]), 2)

    @_patch_first_contacts_auth
    def test_first_contacts_multiple_contacts(self):
        with patch("rest_framework.request.Request.user", self.mock_user):
            contact_a = self.create_contact("Alice", urns=["tel:+250788000001"])
            contact_b = self.create_contact("Bob", urns=["tel:+250788000002"])

            now = timezone.now()
            self.create_incoming_msg(
                contact=contact_a,
                text="Alice first",
                status="H",
                channel=self.channel,
                created_on=now - timezone.timedelta(hours=3),
            )
            self.create_incoming_msg(
                contact=contact_a,
                text="Alice second",
                status="H",
                channel=self.channel,
                created_on=now - timezone.timedelta(hours=1),
            )
            self.create_incoming_msg(
                contact=contact_b,
                text="Bob msg",
                status="H",
                channel=self.channel,
                created_on=now - timezone.timedelta(hours=2),
            )

            response = self.client.get(self._url())

            self.assertEqual(response.status_code, 200)
            results = response.json()["results"]
            self.assertEqual(len(results), 2)
