import json
import time
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from uuid import uuid4
from wsgiref.util import setup_testing_defaults

import jwt
import sentry_sdk
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django_redis import get_redis_connection
from redis.exceptions import ConnectionError as RedisConnectionError, RedisError
from rest_framework import serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from sentry_sdk.integrations.wsgi import SentryWsgiMiddleware

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from temba.api.v2.internals.msgs.idempotency import (
    CLAIM_IN_PROGRESS,
    CLAIM_MISS,
    DONE_TTL_SECONDS,
    REDIS_KEY_PREFIX,
    SERVICE_UNAVAILABLE_ERROR,
    _redis_key,
    claim,
    get_client,
    release,
)
from temba.api.v2.internals.msgs.observability import bind_request_scope, scrub_stream_event
from temba.api.v2.internals.msgs.permissions import ModuleJWTProjectScope
from temba.api.v2.internals.msgs.serializers import (
    HeaderSerializer,
    StreamMsgField,
    _validate_component,
    validate_cta_url,
)
from temba.api.v2.internals.msgs.views import FirstContactsPagination, MsgStreamView
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


_JWT_MATERIAL = None


def _jwt_material():
    global _JWT_MATERIAL
    if _JWT_MATERIAL is None:
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        wrong = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = private.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        _JWT_MATERIAL = {"private": private, "wrong": wrong, "public": public.decode("ascii")}
    return _JWT_MATERIAL


@contextmanager
def assert_no_mailroom():
    with patch("temba.mailroom.queue._queue_task") as queue_task, patch(
        "temba.mailroom.queue._queue_batch_task"
    ) as queue_batch, patch("temba.mailroom.queue._queue_handler_task") as queue_handler:
        yield
        queue_task.assert_not_called()
        queue_batch.assert_not_called()
        queue_handler.assert_not_called()


class ModuleJWTTestMixin:
    def setUp(self):
        super().setUp()
        self.org.proj_uuid = uuid4()
        self.org.save(update_fields=["proj_uuid"])
        self.org2.proj_uuid = uuid4()
        self.org2.save(update_fields=["proj_uuid"])
        material = _jwt_material()
        settings_override = override_settings(JWT_PUBLIC_KEY=material["public"])
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self._private_key = material["private"]
        self._wrong_key = material["wrong"]
        self._purge_stream_keys()
        self.addCleanup(self._purge_stream_keys)

    def _purge_stream_keys(self):
        client = get_redis_connection()
        keys = list(client.scan_iter(f"{REDIS_KEY_PREFIX}:*"))
        if keys:
            client.delete(*keys)

    def jwt_headers(self, project_uuid=None, channel_uuid=None, *, expired=False, wrong_key=False):
        payload = {}
        if project_uuid is not None:
            payload["project_uuid"] = str(project_uuid)
        if channel_uuid is not None:
            payload["channel_uuid"] = str(channel_uuid)
        if expired:
            payload["exp"] = int(time.time()) - 30
        key = self._wrong_key if wrong_key else self._private_key
        token = jwt.encode(payload, key, algorithm="RS256")
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def post_stream(self, payload, headers=None, **extra):
        with assert_no_mailroom():
            return self.client.post(
                reverse("internal_messages_stream"),
                data=json.dumps(payload),
                content_type="application/json",
                **(headers or {}),
                **extra,
            )

    def component_msg(self, **overrides):
        msg = {"text": "Boa notícia", "quick_replies": ["Expressa", "Agendada", "Retirar"]}
        msg.update(overrides)
        return msg

    def payload_for(self, msg, **overrides):
        payload = {
            "project_uuid": str(self.org.proj_uuid),
            "direction": "out",
            "contact_uuid": str(self.contact.uuid),
            "msg": msg,
        }
        payload.update(overrides)
        return payload


class TestMsgStreamComponentsPersist(ModuleJWTTestMixin, TembaTest):
    def setUp(self):
        super().setUp()
        self.contact = self.create_contact("Alice", urns=["tel:+250788100111"])

    def test_quick_replies_are_stored_in_order(self):
        msg = self.component_msg()
        response = self.post_stream(self.payload_for(msg), self.jwt_headers(self.org.proj_uuid))
        stored = Msg.objects.get(id=response.json()["ids"][0])
        self.assertEqual(response.status_code, 201)
        self.assertEqual(stored.text, msg["text"])
        self.assertEqual(stored.metadata, msg)

    def test_list_message_keeps_item_count(self):
        msg = {
            "text": "Ofertas",
            "list_message": {
                "button_text": "Ver 9 ofertas",
                "item_count": 9,
                "list_items": [{"uuid": "item-1", "title": "Café", "description": "500g"}],
            },
        }
        response = self.post_stream(self.payload_for(msg), self.jwt_headers(self.org.proj_uuid))
        stored = Msg.objects.get(id=response.json()["ids"][0])
        self.assertEqual(stored.metadata["list_message"]["item_count"], 9)

    def test_list_message_without_item_count_does_not_invent_one(self):
        msg = {
            "text": "Receitas",
            "list_message": {"button_text": "Ver receitas", "list_items": [{"uuid": "item-1", "title": "Bolo"}]},
        }
        response = self.post_stream(self.payload_for(msg), self.jwt_headers(self.org.proj_uuid))
        stored = Msg.objects.get(id=response.json()["ids"][0])
        self.assertNotIn("item_count", stored.metadata["list_message"])

    def test_cta_and_header_are_stored_verbatim(self):
        msg = self.component_msg(
            cta_message={"display_text": "Acompanhar", "url": "https://loja.example/pedido"},
            header={"type": "text", "text": "Topo"},
            footer="Rodapé",
        )
        response = self.post_stream(self.payload_for(msg), self.jwt_headers(self.org.proj_uuid))
        self.assertEqual(Msg.objects.get(id=response.json()["ids"][0]).metadata, msg)

    def test_empty_text_with_valid_component(self):
        msg = {"text": "", "quick_replies": ["Sim", "Não"]}
        response = self.post_stream(self.payload_for(msg), self.jwt_headers(self.org.proj_uuid))
        stored = Msg.objects.get(id=response.json()["ids"][0])
        self.assertEqual(response.status_code, 201)
        self.assertEqual(stored.text, "")
        self.assertEqual(stored.metadata["quick_replies"], ["Sim", "Não"])

    def test_several_component_types_together(self):
        msg = {
            "text": "Ofertas e pedido",
            "interaction_type": "list",
            "quick_replies": ["Sim"],
            "list_message": {"button_text": "Ver 9 ofertas", "list_items": [{"uuid": "item-1", "title": "Café"}]},
            "cta_message": {"display_text": "Acompanhar", "url": "https://loja.example/pedido"},
        }
        response = self.post_stream(self.payload_for(msg), self.jwt_headers(self.org.proj_uuid))
        stored = Msg.objects.get(id=response.json()["ids"][0]).metadata
        self.assertEqual(stored["quick_replies"], ["Sim"])
        self.assertIn("list_message", stored)
        self.assertIn("cta_message", stored)

    def test_legacy_body_without_components_and_empty_urns(self):
        payload = {
            "project_uuid": str(self.org.proj_uuid),
            "direction": "out",
            "contact_uuid": str(self.contact.uuid),
            "urns": [],
            "text": "Olá!",
        }
        response = self.post_stream(payload, self.jwt_headers(self.org.proj_uuid))
        stored = Msg.objects.get(id=response.json()["ids"][0])
        self.assertEqual(response.status_code, 201)
        self.assertEqual(stored.text, "Olá!")
        self.assertEqual(stored.metadata, {})

    def test_two_urns_store_the_same_components(self):
        self.create_contact("Bob", urns=["tel:+250788100222"])
        payload = {
            "project_uuid": str(self.org.proj_uuid),
            "direction": "out",
            "urns": ["tel:+250788100111", "tel:+250788100222"],
            "msg": self.component_msg(),
        }
        response = self.post_stream(payload, self.jwt_headers(self.org.proj_uuid))
        ids = response.json()["ids"]
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(ids), 2)
        stored = [Msg.objects.get(id=msg_id).metadata for msg_id in ids]
        self.assertEqual(stored[0], stored[1])

    def test_unknown_project_and_foreign_channel_create_nothing(self):
        missing = uuid4()
        payload = self.payload_for(self.component_msg())
        payload["project_uuid"] = str(missing)
        before = Msg.objects.count()
        response = self.post_stream(payload, self.jwt_headers(missing))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"error": "Project not found"})
        self.assertEqual(Msg.objects.count(), before)

        other = Channel.create(
            self.org2,
            self.admin2,
            "RW",
            "A",
            name="Other",
            address="+250789000999",
            device="Test",
            secret="xyz",
            config={},
        )
        payload = self.payload_for(self.component_msg(), channel_uuid=str(other.uuid))
        response = self.post_stream(payload, self.jwt_headers(self.org.proj_uuid))
        self.assertEqual(response.status_code, 400)
        self.assertIn("Channel not found", response.json()["error"])
        self.assertEqual(Msg.objects.count(), before)

    def test_empty_text_without_component_keeps_current_behavior(self):
        response = self.post_stream(self.payload_for({"text": ""}), self.jwt_headers(self.org.proj_uuid))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Msg.objects.get(id=response.json()["ids"][0]).text, "")


def _list_message(**overrides):
    message = {"button_text": "Ver", "list_items": [{"uuid": "item-1", "title": "Café"}]}
    message.update(overrides)
    return message


class TestMsgStreamComponentsValidation(ModuleJWTTestMixin, TembaTest):
    def setUp(self):
        super().setUp()
        self.contact = self.create_contact("Alice", urns=["tel:+250788100311"])

    def _reject(self, msg, *path):
        before = Msg.objects.count()
        response = self.post_stream(self.payload_for(msg), self.jwt_headers(self.org.proj_uuid))
        self.assertEqual(response.status_code, 400, response.content)
        node = response.json()["msg"]
        for part in path:
            node = node[part]
        self.assertTrue(node)
        self.assertEqual(Msg.objects.count(), before)
        return response

    def test_invalid_components_are_rejected_without_a_row(self):
        cases = [
            ("empty quick replies", {"text": "a", "quick_replies": []}, ("quick_replies",)),
            ("blank label", {"text": "a", "quick_replies": [""]}, ("quick_replies", "0")),
            ("non string label", {"text": "a", "quick_replies": [1]}, ("quick_replies", "0")),
            ("object label", {"text": "a", "quick_replies": [{}]}, ("quick_replies", "0")),
            ("null label", {"text": "a", "quick_replies": [None]}, ("quick_replies", "0")),
            (
                "missing button",
                {"text": "a", "list_message": {"list_items": [{"uuid": "a", "title": "t"}]}},
                ("list_message", "button_text"),
            ),
            (
                "blank button",
                {"text": "a", "list_message": {"button_text": "", "list_items": [{"uuid": "a", "title": "t"}]}},
                ("list_message", "button_text"),
            ),
            ("missing items", {"text": "a", "list_message": {"button_text": "Ver"}}, ("list_message", "list_items")),
            (
                "empty items",
                {"text": "a", "list_message": {"button_text": "Ver", "list_items": []}},
                ("list_message", "list_items"),
            ),
            (
                "item without uuid",
                {"text": "a", "list_message": {"button_text": "Ver", "list_items": [{"title": "t"}]}},
                ("list_message", "list_items", "0", "uuid"),
            ),
            (
                "item without title",
                {"text": "a", "list_message": {"button_text": "Ver", "list_items": [{"uuid": "a"}]}},
                ("list_message", "list_items", "0", "title"),
            ),
            (
                "blank item title",
                {"text": "a", "list_message": {"button_text": "Ver", "list_items": [{"uuid": "a", "title": ""}]}},
                ("list_message", "list_items", "0", "title"),
            ),
            ("header image", {"text": "a", "header": {"type": "image"}}, ("header", "type")),
            ("header not object", {"text": "a", "header": "x"}, ("header",)),
            ("footer not text", {"text": "a", "footer": 1}, ("footer",)),
            ("null cta", {"text": "a", "cta_message": None}, ("cta_message",)),
            ("bad interaction", {"text": "a", "interaction_type": "button"}, ("interaction_type",)),
            ("interaction not text", {"text": "a", "interaction_type": 1}, ("interaction_type",)),
            (
                "extra list key",
                {"text": "a", "list_message": _list_message(foo="x")},
                ("list_message", "foo"),
            ),
            (
                "extra item key",
                {"text": "a", "list_message": _list_message(list_items=[{"uuid": "a", "title": "t", "foo": "x"}])},
                ("list_message", "list_items", "0", "foo"),
            ),
            (
                "extra cta key",
                {"text": "a", "cta_message": {"display_text": "Abrir", "url": "https://loja.example/a", "foo": "x"}},
                ("cta_message", "foo"),
            ),
            (
                "extra header key",
                {"text": "a", "header": {"type": "text", "text": "Topo", "foo": "x"}},
                ("header", "foo"),
            ),
            (
                "missing cta text",
                {"text": "a", "cta_message": {"url": "https://loja.example/a"}},
                ("cta_message", "display_text"),
            ),
            (
                "blank cta text",
                {"text": "a", "cta_message": {"display_text": "", "url": "https://loja.example/a"}},
                ("cta_message", "display_text"),
            ),
        ]
        for name, msg, path in cases:
            with self.subTest(name=name):
                self._reject(msg, *path)

        for item_count in (0, -1, 1.5, "9", True):
            with self.subTest(item_count=item_count):
                self._reject(
                    {"text": "a", "list_message": _list_message(item_count=item_count)},
                    "list_message",
                    "item_count",
                )

        urls = (
            "loja.example/x",
            "ftp://loja.example/x",
            "javascript:alert(1)",
            "https://",
            "https://loja.example/a b",
            "https://loja.example/á",
            "HTTPS://loja.example/a",
            "https://loja.example/%ZZ",
            "https://[",
        )
        for url in urls:
            with self.subTest(url=url):
                self._reject({"text": "a", "cta_message": {"display_text": "Abrir", "url": url}}, "cta_message", "url")

    def test_invalid_sibling_rejects_the_whole_request(self):
        msg = {
            "text": "a",
            "list_message": _list_message(),
            "cta_message": {"display_text": "Abrir", "url": "not-a-url"},
        }
        response = self._reject(msg, "cta_message")
        self.assertNotIn("list_message", response.json()["msg"])

    def test_invalid_component_with_two_urns_creates_nothing(self):
        self.create_contact("Bob", urns=["tel:+250788100322"])
        payload = {
            "project_uuid": str(self.org.proj_uuid),
            "direction": "out",
            "urns": ["tel:+250788100311", "tel:+250788100322"],
            "msg": {"text": "a", "quick_replies": []},
        }
        before = Msg.objects.count()
        response = self.post_stream(payload, self.jwt_headers(self.org.proj_uuid))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Msg.objects.count(), before)

    def test_validation_failure_does_not_consume_the_idempotency_key(self):
        headers = self.jwt_headers(self.org.proj_uuid)
        headers["HTTP_IDEMPOTENCY_KEY"] = "retry-key"
        rejected = self.post_stream(self.payload_for({"text": "a", "quick_replies": []}), headers)
        self.assertEqual(rejected.status_code, 400)
        created = self.post_stream(self.payload_for(self.component_msg()), headers)
        self.assertEqual(created.status_code, 201)

    def test_extra_msg_key_is_stored(self):
        msg = self.component_msg(foo="x")
        response = self.post_stream(self.payload_for(msg), self.jwt_headers(self.org.proj_uuid))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Msg.objects.get(id=response.json()["ids"][0]).metadata["foo"], "x")

    def test_values_the_contract_accepts(self):
        accepted = [
            {"text": "a", "quick_replies": ["   "]},
            {
                "text": "a",
                "list_message": _list_message(item_count=9.0, list_items=[{"uuid": "not-a-uuid", "title": "t"}]),
            },
            {"text": "a", "header": {"text": ""}, "footer": ""},
            {"text": "a", "cta_message": {"display_text": "Abrir", "url": "https://loja.example/a%20b"}},
        ]
        for msg in accepted:
            with self.subTest(msg=list(msg)):
                response = self.post_stream(self.payload_for(msg), self.jwt_headers(self.org.proj_uuid))
                self.assertEqual(response.status_code, 201, response.content)
                self.assertEqual(Msg.objects.get(id=response.json()["ids"][0]).metadata, msg)

    def test_empty_text_with_invalid_component_creates_nothing(self):
        self._reject({"text": "", "quick_replies": []}, "quick_replies")


class TestStreamMsgFieldUnit(SimpleTestCase):
    def test_strict_types_and_cta_url(self):
        field = StreamMsgField()
        with self.assertRaises(serializers.ValidationError):
            field.run_validation({"quick_replies": [True]})
        value = {"list_message": _list_message(item_count=9.0)}
        self.assertEqual(field.run_validation(value), value)
        validate_cta_url("https://loja.example/a")
        for url in (
            "HTTPS://loja.example/a",
            "https://",
            "https://loja.example/á",
            "https://loja.example/%ZZ",
            "https://[",
        ):
            with self.assertRaises(serializers.ValidationError):
                validate_cta_url(url)
        validate_cta_url("https://loja.example/a%20b")

    def test_closed_serializer_and_unknown_component(self):
        with patch.object(
            serializers.Serializer, "to_internal_value", side_effect=serializers.ValidationError(["boom"])
        ):
            with self.assertRaises(serializers.ValidationError) as caught:
                HeaderSerializer().to_internal_value({"type": "text"})
        self.assertIn("non_field_errors", caught.exception.detail)
        with self.assertRaises(KeyError):
            _validate_component("nope", "x")

    def test_scrub_stream_event_removes_content_from_every_shape(self):
        secret = "ZXCOV" + "SECRET"
        as_dict = {
            "request": {"data": {"text": secret}, "url": "/stream"},
            "exception": {"values": [{"stacktrace": {"frames": [{"vars": {"text": secret}}]}}]},
            "threads": {"values": [{"stacktrace": {"frames": [{"vars": {"url": secret}}]}}]},
            "breadcrumbs": {"values": [{"category": "query", "data": {"sql": secret}}, {"category": "info"}]},
            "spans": [{"data": {"db.params": [secret]}}, {"data": None}],
        }
        scrub_stream_event(as_dict, None)
        self.assertNotIn("data", as_dict["request"])
        self.assertNotIn("vars", as_dict["exception"]["values"][0]["stacktrace"]["frames"][0])
        self.assertNotIn("data", as_dict["breadcrumbs"]["values"][0])
        self.assertNotIn("db.params", as_dict["spans"][0]["data"])

        as_list = {"breadcrumbs": [{"category": "query", "data": {"sql": secret}}], "spans": []}
        scrub_stream_event(as_list, None)
        self.assertNotIn("data", as_list["breadcrumbs"][0])

        untouched = {"request": "raw", "breadcrumbs": None, "spans": [{"op": "http"}]}
        self.assertIs(scrub_stream_event(untouched, None), untouched)

    def test_claim_recovers_when_the_key_disappears_and_release_swallows_redis_errors(self):
        client = MagicMock()
        client.set.side_effect = [None, True]
        client.get.return_value = None
        with patch("temba.api.v2.internals.msgs.idempotency.get_client", return_value=client):
            state, ids = claim("project", "key", "hash")
        self.assertEqual((state, ids), (CLAIM_MISS, None))

        client = MagicMock()
        client.set.side_effect = [None, None]
        client.get.side_effect = [None, None]
        with patch("temba.api.v2.internals.msgs.idempotency.get_client", return_value=client):
            state, ids = claim("project", "key", "hash")
        self.assertEqual((state, ids), (CLAIM_IN_PROGRESS, None))

        client = MagicMock()
        client.delete.side_effect = RedisError("down")
        with patch("temba.api.v2.internals.msgs.idempotency.get_client", return_value=client):
            with self.assertLogs("temba.api.v2.internals.msgs.idempotency", level="WARNING"):
                release("project", "key")

    def test_normalize_uuid_rejects_blank_and_invalid_values(self):
        view = MsgStreamView()
        self.assertIsNone(view._normalize_uuid(None))
        self.assertIsNone(view._normalize_uuid(""))
        self.assertIsNone(view._normalize_uuid("not-a-uuid"))
        self.assertEqual(view._normalize_uuid(str(uuid.UUID(int=1))), str(uuid.UUID(int=1)))


class TestMsgStreamIdempotency(ModuleJWTTestMixin, TembaTest):
    def setUp(self):
        super().setUp()
        self.contact = self.create_contact("Alice", urns=["tel:+250788100411"])

    def _headers(self, key=None, project=None):
        headers = self.jwt_headers(self.org.proj_uuid if project is None else project)
        if key is not None:
            headers["HTTP_IDEMPOTENCY_KEY"] = key
        return headers

    def _stored_key(self, key, project=None):
        project_uuid = self.org.proj_uuid if project is None else project
        return _redis_key(str(uuid.UUID(str(project_uuid))), key)

    def test_replay_conflict_and_absent_header(self):
        payload = self.payload_for(self.component_msg())
        reordered = {
            "project_uuid": payload["project_uuid"],
            "contact_uuid": payload["contact_uuid"],
            "direction": payload["direction"],
            "msg": {"quick_replies": payload["msg"]["quick_replies"], "text": payload["msg"]["text"]},
        }
        created = self.post_stream(payload, self._headers("same-body"))
        self.assertEqual(created.status_code, 201)
        created_ids = created.json()["ids"]
        ttl = get_client().ttl(self._stored_key("same-body"))
        self.assertGreater(ttl, DONE_TTL_SECONDS - 5)
        self.assertLessEqual(ttl, DONE_TTL_SECONDS)

        replay = self.post_stream(reordered, self._headers("same-body"))
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["ids"], created_ids)
        self.assertEqual(Msg.objects.filter(id__in=created_ids).count(), 1)

        conflict = self.post_stream(self.payload_for(self.component_msg(text="outro")), self._headers("same-body"))
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["code"], "idempotency_conflict")
        self.assertIn("error", conflict.json())
        self.assertEqual(Msg.objects.count(), 1)
        again = self.post_stream(payload, self._headers("same-body"))
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["ids"], created_ids)

        first = self.post_stream(payload, self.jwt_headers(self.org.proj_uuid))
        second = self.post_stream(payload, self.jwt_headers(self.org.proj_uuid))
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertNotEqual(first.json()["ids"], second.json()["ids"])

    def test_key_is_scoped_to_the_project_and_this_endpoint(self):
        self.post_stream(self.payload_for(self.component_msg()), self._headers("shared"))
        other_contact = self.create_contact("Bob", urns=["tel:+250788100422"], org=self.org2, user=self.admin2)
        other_payload = {
            "project_uuid": str(self.org2.proj_uuid),
            "direction": "out",
            "contact_uuid": str(other_contact.uuid),
            "msg": self.component_msg(),
        }
        response = self.post_stream(other_payload, self._headers("shared", project=self.org2.proj_uuid))
        self.assertEqual(response.status_code, 201)
        self.assertIsNotNone(get_client().get(self._stored_key("shared")))

        broadcasts = get_redis_connection()
        foreign = f"idempotency:whatsapp_broadcasts:{self.org.proj_uuid}:shared"
        broadcasts.set(foreign, b"sentinel")
        self.addCleanup(broadcasts.delete, foreign)
        response = self.post_stream(self.payload_for(self.component_msg(text="novo")), self._headers("foreign-key"))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(broadcasts.get(foreign), b"sentinel")

    def test_in_progress_reservation_is_left_untouched(self):
        key = self._stored_key("busy")
        marker = json.dumps({"state": "inflight", "body_hash": "other"})
        get_client().set(key, marker, ex=120)
        before = Msg.objects.count()
        response = self.post_stream(self.payload_for(self.component_msg()), self._headers("busy"))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "idempotency_in_progress")
        self.assertIn("error", response.json())
        self.assertEqual(Msg.objects.count(), before)
        self.assertEqual(get_client().get(key).decode("utf-8"), marker)

    def test_expired_key_is_a_new_request(self):
        headers = self._headers("expired")
        first = self.post_stream(self.payload_for(self.component_msg()), headers)
        get_client().delete(self._stored_key("expired"))
        second = self.post_stream(self.payload_for(self.component_msg()), headers)
        self.assertEqual(second.status_code, 201)
        self.assertNotEqual(first.json()["ids"], second.json()["ids"])

    def test_blank_or_too_long_key_is_ignored(self):
        payload = self.payload_for(self.component_msg())
        for key in ("", "   ", "k" * 129):
            with self.subTest(key=len(key)):
                before = Msg.objects.count()
                first = self.post_stream(payload, self._headers(key))
                second = self.post_stream(payload, self._headers(key))
                self.assertEqual(first.status_code, 201)
                self.assertEqual(second.status_code, 201)
                self.assertNotEqual(first.json()["ids"], second.json()["ids"])
                self.assertEqual(Msg.objects.count(), before + 2)
        exact = "k" * 128
        created = self.post_stream(payload, self._headers(exact))
        replay = self.post_stream(payload, self._headers(exact))
        self.assertEqual(created.status_code, 201)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["ids"], created.json()["ids"])

    def test_failed_attempt_releases_the_key(self):
        headers = self._headers("release-me")
        with patch("temba.api.v2.internals.msgs.views.create_message_db_only", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.post_stream(self.payload_for(self.component_msg()), headers)
        self.assertEqual(self.post_stream(self.payload_for(self.component_msg()), headers).status_code, 201)

        headers = self._headers("release-value")
        with patch(
            "temba.api.v2.internals.msgs.views.create_message_db_only",
            side_effect=ValueError("Contact not found for this project"),
        ):
            rejected = self.post_stream(self.payload_for(self.component_msg()), headers)
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(self.post_stream(self.payload_for(self.component_msg()), headers).status_code, 201)

    def test_unreadable_reservation_conflicts_as_in_progress(self):
        get_client().set(self._stored_key("garbled"), b"not-json", ex=120)
        before = Msg.objects.count()
        response = self.post_stream(self.payload_for(self.component_msg()), self._headers("garbled"))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "idempotency_in_progress")
        self.assertEqual(Msg.objects.count(), before)

    def test_redis_failure_does_not_persist(self):
        before = Msg.objects.count()
        client = MagicMock()
        client.set.side_effect = RedisConnectionError("down")
        with patch("temba.api.v2.internals.msgs.idempotency.get_client", return_value=client):
            response = self.post_stream(self.payload_for(self.component_msg()), self._headers("down"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"error": SERVICE_UNAVAILABLE_ERROR})
        self.assertEqual(Msg.objects.count(), before)

        with patch("temba.api.v2.internals.msgs.idempotency.store_success", side_effect=RedisConnectionError("down")):
            response = self.post_stream(self.payload_for(self.component_msg()), self._headers("down-after"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(Msg.objects.count(), before)


class TestMsgStreamAuthz(ModuleJWTTestMixin, TembaTest):
    def setUp(self):
        super().setUp()
        self.contact = self.create_contact("Alice", urns=["tel:+250788100511"])

    def test_permission_is_explicit(self):
        self.assertEqual(MsgStreamView.permission_classes, [ModuleJWTProjectScope])
        self.assertNotIn(IsAuthenticated, MsgStreamView.permission_classes)
        self.assertNotIn(AllowAny, MsgStreamView.permission_classes)
        self.assertTrue(MsgStreamView.permission_classes)

    def test_anonymous_and_invalid_tokens_are_forbidden(self):
        payload = self.payload_for(self.component_msg())
        before = Msg.objects.count()
        anonymous = self.post_stream(payload)
        self.assertEqual(anonymous.status_code, 403)
        self.assertNotEqual(anonymous.status_code, 401)
        self.assertIn("detail", anonymous.json())
        self.assertEqual(Msg.objects.count(), before)
        self.assertFalse(list(get_redis_connection().scan_iter(f"{REDIS_KEY_PREFIX}:*")))

        cases = (
            self.jwt_headers(self.org.proj_uuid, wrong_key=True),
            self.jwt_headers(self.org.proj_uuid, expired=True),
            self.jwt_headers(),
        )
        for headers in cases:
            with self.subTest(headers=headers["HTTP_AUTHORIZATION"][:24]):
                response = self.post_stream(payload, headers)
                self.assertEqual(response.status_code, 403)
                self.assertNotEqual(response.status_code, 401)
                self.assertIn("detail", response.json())

    def test_body_project_must_match_the_token(self):
        payload = self.payload_for(self.component_msg())
        payload["project_uuid"] = str(self.org2.proj_uuid)
        before = Msg.objects.count()
        response = self.post_stream(payload, self.jwt_headers(self.org.proj_uuid))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "You do not have permission to perform this action.")
        self.assertEqual(Msg.objects.count(), before)

        response = self.post_stream(payload, self.jwt_headers(channel_uuid=self.channel.uuid))
        self.assertEqual(response.status_code, 403)

        matched = self.post_stream(
            self.payload_for(self.component_msg()), self.jwt_headers(channel_uuid=self.channel.uuid)
        )
        self.assertEqual(matched.status_code, 201)

        other = Channel.create(
            self.org2,
            self.admin2,
            "RW",
            "A",
            name="Foreign claim",
            address="+250789000299",
            device="Test",
            secret="xyz",
            config={},
        )
        denied_claim = self.post_stream(
            self.payload_for(self.component_msg()),
            self.jwt_headers(self.org.proj_uuid, channel_uuid=other.uuid),
        )
        self.assertEqual(denied_claim.status_code, 403)

        invalid_body = self.payload_for(self.component_msg())
        invalid_body["project_uuid"] = "not-a-uuid"
        response = self.post_stream(invalid_body, self.jwt_headers(self.org.proj_uuid))
        self.assertEqual(response.status_code, 403)

        both_claims = self.post_stream(
            self.payload_for(self.component_msg()),
            self.jwt_headers(self.org.proj_uuid, channel_uuid=self.channel.uuid),
        )
        self.assertEqual(both_claims.status_code, 201)

        missing_channel = self.post_stream(
            self.payload_for(self.component_msg()), self.jwt_headers(channel_uuid=uuid4())
        )
        self.assertEqual(missing_channel.status_code, 403)

        bad_project_claim = self.post_stream(
            self.payload_for(self.component_msg()), self.jwt_headers(project_uuid="not-a-uuid")
        )
        self.assertEqual(bad_project_claim.status_code, 403)

        bad_channel_claim = self.post_stream(
            self.payload_for(self.component_msg()), self.jwt_headers(channel_uuid="not-a-uuid")
        )
        self.assertEqual(bad_channel_claim.status_code, 403)

        bad_channel_with_project = self.post_stream(
            self.payload_for(self.component_msg()),
            self.jwt_headers(self.org.proj_uuid, channel_uuid="not-a-uuid"),
        )
        self.assertEqual(bad_channel_with_project.status_code, 403)

        request = MagicMock()
        request.jwt_payload = {}
        request.data = {}
        self.assertFalse(ModuleJWTProjectScope().has_permission(request, None))

        permission = ModuleJWTProjectScope()
        with patch(
            "temba.api.v2.internals.msgs.permissions.Channel.objects.filter", side_effect=ValidationError("bad uuid")
        ):
            self.assertIsNone(permission._active_channel("not-a-uuid"))
            self.assertFalse(permission._channel_belongs_to_project("not-a-uuid", self.org.proj_uuid))

        missing_project = {
            "direction": "out",
            "contact_uuid": str(self.contact.uuid),
            "text": "hi",
        }
        response = self.post_stream(missing_project, self.jwt_headers(self.org.proj_uuid))
        self.assertEqual(response.status_code, 400)

        headers = self.jwt_headers(self.org.proj_uuid)
        headers["HTTP_IDEMPOTENCY_KEY"] = "cross-tenant"
        response = self.post_stream(payload, headers)
        self.assertEqual(response.status_code, 403)
        keys = list(get_redis_connection().scan_iter(f"{REDIS_KEY_PREFIX}:*cross-tenant"))
        self.assertEqual(keys, [])

    def test_authorized_project_outcomes(self):
        missing = uuid4()
        payload = self.payload_for(self.component_msg())
        payload["project_uuid"] = str(missing)
        response = self.post_stream(payload, self.jwt_headers(missing))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"error": "Project not found"})

        response = self.post_stream(self.payload_for(self.component_msg()), self.jwt_headers(self.org.proj_uuid))
        self.assertEqual(response.status_code, 201)

        other = Channel.create(
            self.org2,
            self.admin2,
            "RW",
            "A",
            name="Other",
            address="+250789000199",
            device="Test",
            secret="xyz",
            config={},
        )
        before = Msg.objects.count()
        payload = self.payload_for(self.component_msg(), channel_uuid=str(other.uuid))
        response = self.post_stream(payload, self.jwt_headers(self.org.proj_uuid))
        self.assertEqual(response.status_code, 400)
        self.assertIn("Channel not found", response.json()["error"])
        self.assertEqual(Msg.objects.count(), before)


class _MemoryTransport(sentry_sdk.transport.Transport):
    def __init__(self, options=None):
        super().__init__(options)
        self.events = []

    def capture_event(self, event):
        self.events.append(event)

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.headers.get("type") not in (None, "event"):
                continue
            payload = item.payload
            raw = payload.get_bytes() if hasattr(payload, "get_bytes") else payload.bytes
            self.events.append(json.loads(raw))


STREAM_SCOPE_TAGS = ("caller", "account_id", "user_id", "project_uuid", "channel_uuid", "correlation_id")


def _event_tags(event):
    tags = event.get("tags") or {}
    return dict(tags) if isinstance(tags, list) else tags


class TestStreamSentryProductionScope(SimpleTestCase):
    """
    bind_request_scope writes on the current scope and relies on DjangoIntegration giving each production request its
    own: the integration runs WSGIHandler inside SentryWsgiMiddleware, which handles the request on a copy of the hub.
    """

    def test_wsgi_request_scope_is_discarded(self):
        marker = "ZXWSGI" + uuid4().hex
        transport = _MemoryTransport()
        client = sentry_sdk.Client(
            dsn="http://public@example.invalid/1",
            transport=transport,
            default_integrations=False,
            auto_session_tracking=False,
        )

        def stream_app(environ, start_response):
            bind_request_scope(project_uuid="project-1", channel_uuid="channel-1", correlation_id="corr-1")
            sentry_sdk.capture_event({"message": "inside the request", "request": {"data": {"text": marker}}})
            start_response("201 Created", [])
            return [b""]

        environ = {}
        setup_testing_defaults(environ)

        with sentry_sdk.Hub(client) as hub:
            list(SentryWsgiMiddleware(stream_app)(environ, lambda status, headers: None))
            outside_tags = dict(hub.scope._tags)
            outside_processors = list(hub.scope._event_processors)

        # the event raised in the request has the stream tags and went through the scrubbing
        self.assertEqual(1, len(transport.events))
        self.assertNotIn(marker, json.dumps(transport.events))
        self.assertEqual(
            {
                "caller": "module_jwt",
                "account_id": "none",
                "user_id": "none",
                "project_uuid": "project-1",
                "channel_uuid": "channel-1",
                "correlation_id": "corr-1",
            },
            {tag: _event_tags(transport.events[0]).get(tag) for tag in STREAM_SCOPE_TAGS},
        )

        # and nothing of it is left on the scope once the request is over
        self.assertEqual({}, outside_tags)
        self.assertNotIn(scrub_stream_event, outside_processors)


class TestMsgStreamObservability(ModuleJWTTestMixin, TembaTest):
    def setUp(self):
        super().setUp()
        self.contact = self.create_contact("Alice", urns=["tel:+250788100611"])

    def _records(self, captured):
        return [record for record in captured.records if record.getMessage() == "messages_stream outcome"]

    def _headers(self, key):
        headers = self.jwt_headers(self.org.proj_uuid)
        headers["HTTP_IDEMPOTENCY_KEY"] = key
        return headers

    def test_sentry_event_omits_message_content(self):
        marker = "ZXSTREAM" + uuid4().hex
        msg = {
            "text": marker + "TEXT",
            "quick_replies": [marker + "LABEL"],
            "list_message": {
                "button_text": marker + "BUTTON",
                "list_items": [{"uuid": "item-1", "title": marker + "ITEM", "description": marker + "DESC"}],
            },
            "cta_message": {"display_text": marker + "CTA", "url": "https://example.test/" + marker},
            "header": {"type": "text", "text": marker + "HEADER"},
            "footer": marker + "FOOTER",
        }
        transport = _MemoryTransport()
        client = sentry_sdk.Client(
            dsn="http://public@example.invalid/1", transport=transport, default_integrations=False
        )
        previous = sentry_sdk.Hub.current.client
        sentry_sdk.Hub.current.bind_client(client)
        headers = self.jwt_headers(self.org.proj_uuid)
        headers["HTTP_X_CORRELATION_ID"] = "corr-1"
        try:
            with patch("temba.api.v2.internals.msgs.views.create_message_db_only", side_effect=RuntimeError("boom")):
                with self.assertRaises(RuntimeError):
                    self.post_stream(self.payload_for(msg), headers)
        finally:
            sentry_sdk.Hub.current.bind_client(previous)

        self.assertTrue(transport.events)
        self.assertNotIn(marker, json.dumps(transport.events))
        tags = transport.events[0].get("tags") or {}
        if isinstance(tags, list):
            tags = dict(tags)
        self.assertEqual(str(tags.get("project_uuid")), str(self.org.proj_uuid))
        self.assertEqual(tags.get("correlation_id"), "corr-1")
        self.assertEqual(tags.get("caller"), "module_jwt")
        self.assertEqual(tags.get("account_id"), "none")
        self.assertEqual(tags.get("user_id"), "none")

    def test_stream_request_scope_does_not_leak(self):
        hub = sentry_sdk.Hub.current
        scope = hub.scope
        tags_before = dict(scope._tags)
        processors_before = list(scope._event_processors)
        self.addCleanup(self._restore_scope, scope, tags_before, processors_before)

        client = sentry_sdk.Client(
            dsn="http://public@example.invalid/1", transport=_MemoryTransport(), default_integrations=False
        )
        previous = hub.client
        hub.bind_client(client)
        headers = self.jwt_headers(self.org.proj_uuid)
        headers["HTTP_X_CORRELATION_ID"] = "corr-leak"
        try:
            response = self.post_stream(
                self.payload_for(self.component_msg(), channel_uuid=str(self.channel.uuid)), headers
            )
        finally:
            hub.bind_client(previous)

        self.assertEqual(response.status_code, 201, response.content)
        for tag in STREAM_SCOPE_TAGS:
            self.assertNotIn(tag, scope._tags)
        self.assertNotIn(scrub_stream_event, scope._event_processors)
        self.assertEqual(tags_before, dict(scope._tags))
        self.assertEqual(processors_before, list(scope._event_processors))

    def _restore_scope(self, scope, tags, processors):
        # puts back what this test found, so a failing run neither leaks into nor cleans up after other tests
        scope._tags = dict(tags)
        scope._event_processors = list(processors)

    def test_each_outcome_is_logged_without_content(self):
        marker = "ZXLOG" + uuid4().hex
        payload = self.payload_for(self.component_msg(text=marker))
        headers = self._headers("log-key")
        with self.assertLogs("temba.api.v2.internals.msgs", level="INFO") as captured:
            created = self.post_stream(payload, headers)
            replay = self.post_stream(payload, headers)
            conflict = self.post_stream(self.payload_for(self.component_msg(text="other")), headers)
            invalid = self.post_stream(
                self.payload_for({"text": marker, "quick_replies": []}), self.jwt_headers(self.org.proj_uuid)
            )
            anonymous = self.post_stream(payload)
            foreign = dict(payload, project_uuid=str(self.org2.proj_uuid))
            denied = self.post_stream(foreign, self.jwt_headers(self.org.proj_uuid))
            missing_project = uuid4()
            missing = dict(payload, project_uuid=str(missing_project))
            not_found = self.post_stream(missing, self.jwt_headers(missing_project))
        self.assertEqual(
            [created.status_code, replay.status_code, conflict.status_code, invalid.status_code],
            [201, 200, 409, 400],
        )
        self.assertEqual(anonymous.status_code, 403)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(not_found.status_code, 404)
        outcomes = {record.outcome for record in self._records(captured)}
        self.assertTrue(
            {
                "created",
                "replayed",
                "conflict",
                "rejected_validation",
                "rejected_auth",
                "rejected_tenant",
                "project_not_found",
            }
            <= outcomes
        )
        reasons = {getattr(record, "reason", None) for record in self._records(captured)}
        self.assertIn("idempotency_conflict", reasons)
        for record in self._records(captured):
            self.assertNotIn(marker, str(record.__dict__))

        get_client().set(
            _redis_key(str(uuid.UUID(str(self.org.proj_uuid))), "busy-log"),
            json.dumps({"state": "inflight", "body_hash": "x"}),
            ex=120,
        )
        with self.assertLogs("temba.api.v2.internals.msgs", level="INFO") as captured:
            in_progress = self.post_stream(payload, self._headers("busy-log"))
        self.assertEqual(in_progress.json()["code"], "idempotency_in_progress")
        progress_reasons = {getattr(record, "reason", None) for record in self._records(captured)}
        self.assertIn("idempotency_in_progress", progress_reasons)

        client = MagicMock()
        client.set.side_effect = RedisConnectionError("down")
        with patch("temba.api.v2.internals.msgs.idempotency.get_client", return_value=client):
            with self.assertLogs("temba.api.v2.internals.msgs", level="INFO") as captured:
                failed = self.post_stream(payload, self._headers("down-log"))
        self.assertEqual(failed.status_code, 503)
        self.assertIn("dedupe_unavailable", {getattr(record, "reason", None) for record in self._records(captured)})

    def test_correlation_id_bounds(self):
        payload = self.payload_for(self.component_msg())
        headers = self.jwt_headers(self.org.proj_uuid)
        headers["HTTP_X_CORRELATION_ID"] = "a"
        with self.assertLogs("temba.api.v2.internals.msgs", level="INFO") as captured:
            self.post_stream(payload, headers)
        self.assertEqual(self._records(captured)[-1].correlation_id, "a")

        headers["HTTP_X_CORRELATION_ID"] = "b" * 128
        with self.assertLogs("temba.api.v2.internals.msgs", level="INFO") as captured:
            self.post_stream(payload, headers)
        self.assertEqual(self._records(captured)[-1].correlation_id, "b" * 128)

        long_id = "c" * 129
        headers["HTTP_X_CORRELATION_ID"] = long_id
        with self.assertLogs("temba.api.v2.internals.msgs", level="INFO") as captured:
            response = self.post_stream(payload, headers)
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(self._records(captured)[-1].correlation_id)
        self.assertNotIn(long_id, str(self._records(captured)[-1].__dict__))

        headers["HTTP_X_CORRELATION_ID"] = ""
        with self.assertLogs("temba.api.v2.internals.msgs", level="INFO") as captured:
            response = self.post_stream(payload, headers)
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(self._records(captured)[-1].correlation_id)
