from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

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
        msg = Msg.objects.get(id=response.json()["id"])
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
        created = Msg.objects.get(id=response.json()["id"])
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
            "urn": "tel:+250788000333",
            "text": "ping",
        }
        response = self.client.post(reverse("internal_messages_stream"), data=payload, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        msg = Msg.objects.get(id=response.json()["id"])
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
        msg = Msg.objects.get(id=response.json()["id"])
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
            "urn": "invalid-urn",
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

    @patch("temba.event_driven.publisher.rabbitmq_publisher.RabbitmqPublisher.send_message")
    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.authentication_classes", [])
    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.permission_classes", [])
    def test_stream_publishes_billing_outgoing(self, *_mocks, mock_publish):
        contact = self.create_contact("Ivan", urns=["tel:+250788001234"])
        payload = {
            "project_uuid": str(self.org.proj_uuid),
            "direction": "O",
            "contact_uuid": str(contact.uuid),
            "text": "bill me",
            "template": "template-uuid",
        }
        response = self.client.post(reverse("internal_messages_stream"), data=payload, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(mock_publish.called)
        args, kwargs = mock_publish.call_args
        self.assertEqual(kwargs.get("exchange"), "msgs.topic")
        self.assertEqual(kwargs.get("routing_key"), "billing;msgs-create")
        self.assertIn("body", kwargs)
        body = kwargs["body"]
        self.assertEqual(body["direction"], "O")
        self.assertEqual(body["text"], "bill me")
        self.assertEqual(body["template"], "template-uuid")

    @patch("temba.event_driven.publisher.rabbitmq_publisher.RabbitmqPublisher.send_message")
    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.authentication_classes", [])
    @patch("temba.api.v2.internals.msgs.views.MsgStreamView.permission_classes", [])
    def test_stream_publishes_billing_incoming(self, *_mocks, mock_publish):
        self.create_contact("Judy", urns=["telegram:844380532"])
        payload = {
            "project_uuid": str(self.org.proj_uuid),
            "direction": "I",
            "urn": "telegram:844380532",
            "text": "hello",
        }
        response = self.client.post(reverse("internal_messages_stream"), data=payload, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(mock_publish.called)
        body = mock_publish.call_args.kwargs["body"]
        self.assertEqual(body["contact_urn"], "telegram:844380532")
        self.assertEqual(body["direction"], "I")
