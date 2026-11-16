import datetime as dt
import hashlib
import inspect
import json
import uuid
from unittest.mock import MagicMock, patch

from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import ClientError, ConnectTimeoutError, ReadTimeoutError
from django_redis import get_redis_connection
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError
from rest_framework.authentication import BaseAuthentication

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import override_settings
from django.utils import timezone

from temba.api.auth.jwt import OptionalJWTAuthentication
from temba.api.v2 import serializers as api_serializers
from temba.api.v2.broadcast_media import MAX_BROADCAST_MULTIPART_BYTES, MEDIA_STORAGE_UNAVAILABLE_MESSAGE
from temba.api.v2.internals.broadcasts.context import ProjectMismatch
from temba.api.v2.internals.broadcasts.idempotency import (
    compute_body_hash,
    compute_media_body_hash,
    idempotency_lookup,
    idempotency_release,
)
from temba.api.v2.internals.broadcasts.views import InternalWhatsappBroadcastsEndpoint
from temba.api.v2.serializers import WhatsappBroadcastWriteSerializer
from temba.contacts.models import Contact
from temba.flows.models import Flow
from temba.msgs.custom_data import CUSTOM_DATA_MAX_DEPTH
from temba.msgs.models import Broadcast, BroadcastStatistics, ManagedTriggerGroup
from temba.msgs.usecases.broadcast_media import (
    ALLOWED_BROADCAST_MEDIA,
    BROADCAST_MEDIA_DEDUP_TTL_SECONDS,
    AllowedMedia,
    _dedup_redis,
)
from temba.msgs.usecases.managed_trigger_group import resolve_or_create_managed_trigger_group
from temba.orgs.models import Org
from temba.tests.base import TembaTest
from temba.tests.mailroom import mock_mailroom
from temba.tests.media import audio_only_mp4_bytes, capture_sentry_events, read_test_media
from temba.triggers.models import Trigger
from temba.utils.s3 import private_file_storage

User = get_user_model()


class TestInternalWhatsappBroadcast(TembaTest):
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_success(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])

            url = "/api/v2/internals/whatsapp_broadcasts"
            body = {
                "project": self.org.proj_uuid,
                "contacts": [contact.uuid],
                "msg": {
                    "text": "Essa é uma mensagem de teste para @contact.name",
                },
            }
            response = self.client.post(url, data=body, content_type="application/json")

            self.assertEqual(response.status_code, 201)
            data = response.json()
            self.assertIn("id", data)
            self.assertIn("created_on", data)
            self.assertEqual(data["contacts"][0]["uuid"], str(contact.uuid))
            self.assertEqual(data["metadata"].get("text"), body["msg"]["text"])

    def _post_internal(self, body):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"
        with patch("rest_framework.request.Request.user", mock_user):
            return self.client.post(
                "/api/v2/internals/whatsapp_broadcasts", data=body, content_type="application/json"
            )

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_custom_data_success_and_absence(self):
        contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])
        custom_data = {"order_id": "1234567890-01", "tags": ["vip"]}
        url_body = {
            "project": self.org.proj_uuid,
            "contacts": [contact.uuid],
            "msg": {"text": "Hi", "custom_data": custom_data},
        }
        response = self._post_internal(url_body)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(custom_data, Broadcast.objects.get(id=response.json()["id"]).metadata["custom_data"])

        wac = self.create_channel("WAC", "WhatsApp Cloud", "1234", org=self.org)
        response = self._post_internal(
            {
                "project": self.org.proj_uuid,
                "contacts": [contact.uuid],
                "channel": str(wac.uuid),
                "msg": {"text": "Hi", "custom_data": custom_data},
            }
        )
        self.assertEqual(response.status_code, 201)

        response = self._post_internal(
            {"project": self.org.proj_uuid, "contacts": [contact.uuid], "msg": {"text": "Hi"}}
        )
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("custom_data", Broadcast.objects.get(id=response.json()["id"]).metadata)

        response = self._post_internal(
            {"project": self.org.proj_uuid, "contacts": [contact.uuid], "msg": {"text": "Hi", "custom_data": {}}}
        )
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("custom_data", Broadcast.objects.get(id=response.json()["id"]).metadata)

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_custom_data_invalid(self):
        contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])
        before = Broadcast.objects.filter(org=self.org).count()
        nested = {}
        current = nested
        for _ in range(CUSTOM_DATA_MAX_DEPTH):
            current["x"] = {}
            current = current["x"]
        cases = [
            (None, "custom_data must be an object"),
            ("x", "custom_data must be an object"),
            ([], "custom_data must be an object"),
            (1, "custom_data must be an object"),
            ({"pad": "x" * 16385}, "custom_data must be at most 16384 bytes when serialized"),
            (nested, "custom_data must have at most 32 levels of nesting"),
            ({"$x": 1}, "custom_data keys must not start with '$' or contain '.'"),
            ({"outer": {"a.b": 1}}, "custom_data keys must not start with '$' or contain '.'"),
            ({"items": [{"bad.key": True}]}, "custom_data keys must not start with '$' or contain '.'"),
        ]
        for payload, message in cases:
            response = self._post_internal(
                {
                    "project": self.org.proj_uuid,
                    "contacts": [contact.uuid],
                    "msg": {"text": "Hi", "custom_data": payload},
                }
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["msg"], [message])
        self.assertEqual(before, Broadcast.objects.filter(org=self.org).count())

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.idempotency_release")
    @patch(
        "temba.api.v2.internals.broadcasts.views.idempotency_lookup",
        return_value=("miss", None),
    )
    @patch(
        "temba.api.v2.internals.broadcasts.views.resolve_org_and_user_internal_whatsapp",
        side_effect=ProjectMismatch("Project mismatch"),
    )
    def test_project_mismatch_returns_403(self, _resolve, _lookup, mock_release):
        url = "/api/v2/internals/whatsapp_broadcasts"
        body = {
            "project": self.org.proj_uuid,
            "contacts": [],
            "msg": {"text": "Hi"},
        }
        response = self.client.post(
            url,
            data=body,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="mismatch-key",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "Project mismatch"})
        mock_release.assert_called_once()

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    @patch(
        "temba.api.v2.internals.broadcasts.views.resolve_org_and_user_internal_whatsapp",
        side_effect=ValueError("unexpected"),
    )
    def test_unexpected_value_error_is_logged_and_returns_401(self, _resolve):
        url = "/api/v2/internals/whatsapp_broadcasts"
        body = {"project": self.org.proj_uuid, "contacts": [], "msg": {"text": "Hi"}}
        with patch("temba.api.v2.internals.broadcasts.views.logger") as mock_logger:
            response = self.client.post(url, data=body, content_type="application/json")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"error": "unexpected"})
        mock_logger.warning.assert_called_once()

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_project_not_provided(self):
        contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])

        url = "/api/v2/internals/whatsapp_broadcasts"
        body = {
            "contacts": [contact.uuid],
            "msg": {
                "text": "Essa é uma mensagem de teste para @contact.name",
            },
        }
        response = self.client.post(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"error": "Project not provided"})

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_project_not_found(self):
        contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])

        url = "/api/v2/internals/whatsapp_broadcasts"
        body = {
            "project": self.org.uuid,
            "contacts": [contact.uuid],
            "msg": {
                "text": "Essa é uma mensagem de teste para @contact.name",
            },
        }
        response = self.client.post(url, data=body, content_type="application/json")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"error": "Project not found"})

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_serializer_error(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            url = "/api/v2/internals/whatsapp_broadcasts"
            body = {
                "project": self.org.proj_uuid,
                "msg": {"text": "Essa é uma mensagem de teste para @contact.name"},
            }
            response = self.client.post(url, data=body, content_type="application/json")

            self.assertEqual(response.status_code, 400)

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_queue_invalid_value(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])

            url = "/api/v2/internals/whatsapp_broadcasts"
            body = {
                "project": self.org.proj_uuid,
                "contacts": [contact.uuid],
                "queue": "invalid",
                "msg": {"text": "hello"},
            }
            response = self.client.post(url, data=body, content_type="application/json")

            self.assertEqual(response.status_code, 400)
            error = response.json()
            self.assertIn("non_field_errors", error)
            self.assertIn("Queue must be either", error["non_field_errors"][0])

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_template_batch_requires_name_groups_and_disallows_contacts(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            group1 = self.create_group("Group 1", contacts=[])
            group2 = self.create_group("Group 2", contacts=[])

            url = "/api/v2/internals/whatsapp_broadcasts"

            # missing name
            body = {
                "project": self.org.proj_uuid,
                "queue": "TEMPLATE_BATCH",
                "groups": [str(group1.uuid)],
                "msg": {"text": "hello"},
            }
            response = self.client.post(url, data=body, content_type="application/json")
            self.assertEqual(response.status_code, 400)
            self.assertIn("Name is required for template_batch queue", response.json()["non_field_errors"][0])

            # missing groups even if urns provided
            body = {
                "project": self.org.proj_uuid,
                "queue": "TEMPLATE_BATCH",
                "name": "Batch Name",
                "urns": ["whatsapp:5561912345678"],
                "msg": {"text": "hello"},
            }
            response = self.client.post(url, data=body, content_type="application/json")
            self.assertEqual(response.status_code, 400)
            self.assertIn("Groups are required for template_batch queue", response.json()["non_field_errors"][0])

            # contacts not allowed even if groups provided
            contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])
            body = {
                "project": self.org.proj_uuid,
                "queue": "TEMPLATE_BATCH",
                "name": "Batch Name",
                "groups": [str(group1.uuid), str(group2.uuid)],
                "contacts": [str(contact.uuid)],
                "msg": {"text": "hello"},
            }
            response = self.client.post(url, data=body, content_type="application/json")
            self.assertEqual(response.status_code, 400)
            self.assertIn("Contacts are not allowed for template_batch queue", response.json()["non_field_errors"][0])

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    @mock_mailroom
    def test_trigger_flow_uuid_with_urns_creates_managed_group(self, mocks):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            flow = self.create_flow(flow_type=Flow.TYPE_MESSAGE)
            url = "/api/v2/internals/whatsapp_broadcasts"
            body = {
                "project": self.org.proj_uuid,
                "trigger_flow_uuid": str(flow.uuid),
                "msg": {"text": "hello"},
                "urns": ["whatsapp:5511999999999", "whatsapp:5511888888888"],
            }
            response = self.client.post(url, data=body, content_type="application/json")

            self.assertEqual(response.status_code, 201)
            data = response.json()
            self.assertEqual(data["groups"], [])
            self.assertIn("trigger_group", data["metadata"])
            trigger_group = data["metadata"]["trigger_group"]
            self.assertIn("uuid", trigger_group)
            self.assertTrue(trigger_group["name"].startswith("Trigger · "))

            association = ManagedTriggerGroup.objects.get(org=self.org, flow=flow)
            self.assertEqual(str(association.group.uuid), trigger_group["uuid"])
            self.assertEqual(association.group.contacts.count(), 2)
            self.assertEqual(
                Trigger.objects.filter(
                    org=self.org,
                    flow=flow,
                    trigger_type=Trigger.TYPE_CATCH_ALL,
                    is_archived=False,
                    groups=association.group,
                ).count(),
                1,
            )

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    @mock_mailroom
    def test_trigger_flow_uuid_most_recent_campaign_wins(self, mocks):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            flow_a = self.create_flow(name="Flow A", flow_type=Flow.TYPE_MESSAGE)
            flow_b = self.create_flow(name="Flow B", flow_type=Flow.TYPE_MESSAGE)
            url = "/api/v2/internals/whatsapp_broadcasts"
            urn = "whatsapp:5511999999999"

            self.client.post(
                url,
                data={
                    "project": self.org.proj_uuid,
                    "trigger_flow_uuid": str(flow_a.uuid),
                    "msg": {"text": "hello A"},
                    "urns": [urn],
                },
                content_type="application/json",
            )
            response = self.client.post(
                url,
                data={
                    "project": self.org.proj_uuid,
                    "trigger_flow_uuid": str(flow_b.uuid),
                    "msg": {"text": "hello B"},
                    "urns": [urn],
                },
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 201)

            group_a = ManagedTriggerGroup.objects.get(org=self.org, flow=flow_a).group
            group_b = ManagedTriggerGroup.objects.get(org=self.org, flow=flow_b).group
            contact = Contact.from_urn(self.org, urn)
            self.assertTrue(group_b.contacts.filter(id=contact.id).exists())
            self.assertFalse(group_a.contacts.filter(id=contact.id).exists())

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_trigger_flow_uuid_groups_only_does_not_create_managed_group(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            flow = self.create_flow(flow_type=Flow.TYPE_MESSAGE)
            group = self.create_group("Segment", contacts=[])
            url = "/api/v2/internals/whatsapp_broadcasts"
            body = {
                "project": self.org.proj_uuid,
                "groups": [str(group.uuid)],
                "trigger_flow_uuid": str(flow.uuid),
                "msg": {"text": "hello"},
            }
            response = self.client.post(url, data=body, content_type="application/json")

            self.assertEqual(response.status_code, 201)
            data = response.json()
            self.assertNotIn("trigger_group", data["metadata"])
            self.assertFalse(ManagedTriggerGroup.objects.filter(org=self.org).exists())

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    @mock_mailroom
    def test_trigger_flow_uuid_mixed_audience_does_not_copy_group_members(self, mocks):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            flow = self.create_flow(flow_type=Flow.TYPE_MESSAGE)
            segment_contact = self.create_contact("Segment", urns=["whatsapp:5511555555555"])
            segment = self.create_group("Segment", contacts=[segment_contact])
            url = "/api/v2/internals/whatsapp_broadcasts"
            body = {
                "project": self.org.proj_uuid,
                "groups": [str(segment.uuid)],
                "urns": ["whatsapp:5511999999999"],
                "trigger_flow_uuid": str(flow.uuid),
                "msg": {"text": "hello"},
            }
            response = self.client.post(url, data=body, content_type="application/json")
            self.assertEqual(response.status_code, 201)

            managed = ManagedTriggerGroup.objects.get(org=self.org, flow=flow).group
            self.assertEqual(managed.contacts.count(), 1)
            self.assertFalse(managed.contacts.filter(id=segment_contact.id).exists())

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    @mock_mailroom
    def test_trigger_flow_uuid_group_quota_exceeded(self, mocks):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            self.org.limits = {Org.LIMIT_GROUPS: 0}
            self.org.save(update_fields=("limits",))
            flow = self.create_flow(flow_type=Flow.TYPE_MESSAGE)
            response = self.client.post(
                "/api/v2/internals/whatsapp_broadcasts",
                data={
                    "project": self.org.proj_uuid,
                    "trigger_flow_uuid": str(flow.uuid),
                    "msg": {"text": "hello"},
                    "urns": ["whatsapp:5511999999999"],
                },
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("the limit is", str(response.json()))

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    @mock_mailroom
    def test_trigger_flow_uuid_contact_resolution_error(self, mocks):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            flow = self.create_flow(flow_type=Flow.TYPE_MESSAGE)
            resolve_or_create_managed_trigger_group(self.org, self.admin, flow)
            mocks.error("boom")
            response = self.client.post(
                "/api/v2/internals/whatsapp_broadcasts",
                data={
                    "project": self.org.proj_uuid,
                    "trigger_flow_uuid": str(flow.uuid),
                    "msg": {"text": "hello"},
                    "urns": ["whatsapp:5511777777777"],
                },
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("Couldn't resolve or create a contact", str(response.json()))

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_trigger_flow_uuid_not_found_and_wrong_type(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            url = "/api/v2/internals/whatsapp_broadcasts"

            # not found
            body = {
                "project": self.org.proj_uuid,
                "queue": "template_batch",
                "name": "Batch Name",
                "groups": [str(self.create_group("G", contacts=[]).uuid)],
                "trigger_flow_uuid": str(uuid.uuid4()),
                "msg": {"text": "hello"},
            }
            response = self.client.post(url, data=body, content_type="application/json")
            self.assertEqual(response.status_code, 400)
            self.assertIn("Trigger flow not found for this workspace", response.json()["non_field_errors"][0])

            # wrong type
            background_flow = self.create_flow(flow_type=Flow.TYPE_BACKGROUND)
            body["trigger_flow_uuid"] = str(background_flow.uuid)
            response = self.client.post(url, data=body, content_type="application/json")
            self.assertEqual(response.status_code, 400)
            self.assertIn("Trigger flow must be a messaging or voice flow", response.json()["non_field_errors"][0])

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_trigger_flow_uuid_success(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            url = "/api/v2/internals/whatsapp_broadcasts"
            flow = self.create_flow(flow_type=Flow.TYPE_MESSAGE)
            group = self.create_group("G", contacts=[])

            body = {
                "project": self.org.proj_uuid,
                "queue": "template_batch",
                "name": "Batch Name",
                "groups": [str(group.uuid)],
                "trigger_flow_uuid": str(flow.uuid),
                "msg": {"text": "hello"},
            }
            response = self.client.post(url, data=body, content_type="application/json")

            self.assertEqual(response.status_code, 201)
            data = response.json()
            self.assertIn("id", data)
            self.assertEqual(data["metadata"].get("text"), body["msg"]["text"])


class TestInternalBroadcastsUploadMedia(TembaTest):
    def setUp(self):
        super().setUp()
        # Ensure org has a project UUID for lookups
        if not self.org.proj_uuid:
            self.org.proj_uuid = uuid.uuid4()
            self.org.save(update_fields=("proj_uuid",))

        self.url = "/api/v2/internals/broadcasts/upload_media"

    @patch(
        "temba.api.v2.internals.broadcasts.views.InternalBroadcastsUploadMediaEndpoint.authentication_classes",
        [],
    )
    @patch(
        "temba.api.v2.internals.broadcasts.views.InternalBroadcastsUploadMediaEndpoint.permission_classes",
        [],
    )
    @override_settings(STORAGE_URL="https://bucket.example.com")
    def test_success_upload(self):
        upload = SimpleUploadedFile("file.txt", b"hello world", content_type="text/plain")

        with patch(
            "temba.api.v2.internals.broadcasts.services.private_file_storage.save",
        ) as mock_save:
            mock_save.return_value = f"attachments/{self.org.id}/broadcasts/abcd/file.txt"

            resp = self.client.post(
                self.url,
                data={"project_uuid": str(self.org.proj_uuid), "file": upload},
            )

            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["type"], "text/plain")
            self.assertEqual(
                data["url"], f"https://bucket.example.com/attachments/{self.org.id}/broadcasts/abcd/file.txt"
            )

            # Ensure path written respects convention
            called_path = mock_save.call_args[0][0]
            self.assertTrue(called_path.startswith(f"attachments/{self.org.id}/broadcasts/"))

    @patch(
        "temba.api.v2.internals.broadcasts.views.InternalBroadcastsUploadMediaEndpoint.authentication_classes",
        [],
    )
    @patch(
        "temba.api.v2.internals.broadcasts.views.InternalBroadcastsUploadMediaEndpoint.permission_classes",
        [],
    )
    @override_settings(STORAGE_URL="https://bucket.example.com")
    def test_success_upload_m4a_normalization(self):
        upload = SimpleUploadedFile("audio.m4a", b"data", content_type="audio/m4a")

        with patch(
            "temba.api.v2.internals.broadcasts.services.private_file_storage.save",
        ) as mock_save:
            mock_save.return_value = f"attachments/{self.org.id}/broadcasts/abcd/audio.m4a"

            resp = self.client.post(
                self.url,
                data={"project_uuid": str(self.org.proj_uuid), "file": upload},
            )

            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["type"], "audio/mp4")

    @patch(
        "temba.api.v2.internals.broadcasts.views.InternalBroadcastsUploadMediaEndpoint.authentication_classes",
        [],
    )
    @patch(
        "temba.api.v2.internals.broadcasts.views.InternalBroadcastsUploadMediaEndpoint.permission_classes",
        [],
    )
    def test_upload_rejects_body_project_mismatch(self):
        from rest_framework.test import APIRequestFactory

        from temba.api.v2.internals.broadcasts.views import InternalBroadcastsUploadMediaEndpoint

        view = InternalBroadcastsUploadMediaEndpoint()
        raw = APIRequestFactory().post(
            self.url,
            {"project_uuid": str(uuid.uuid4())},
            format="json",
        )
        request = view.initialize_request(raw)
        request.org = self.org
        response = view.post(request)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data, {"error": "Project mismatch"})

    @patch(
        "temba.api.v2.internals.broadcasts.views.InternalBroadcastsUploadMediaEndpoint.authentication_classes",
        [],
    )
    @patch(
        "temba.api.v2.internals.broadcasts.views.InternalBroadcastsUploadMediaEndpoint.permission_classes",
        [],
    )
    def test_missing_project_uuid_returns_400(self):
        upload = SimpleUploadedFile("file.txt", b"hello", content_type="text/plain")
        resp = self.client.post(self.url, data={"file": upload})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"error": "project_uuid is required"})

    @patch(
        "temba.api.v2.internals.broadcasts.views.InternalBroadcastsUploadMediaEndpoint.authentication_classes",
        [],
    )
    @patch(
        "temba.api.v2.internals.broadcasts.views.InternalBroadcastsUploadMediaEndpoint.permission_classes",
        [],
    )
    def test_project_not_found_returns_404(self):
        upload = SimpleUploadedFile("file.txt", b"hello", content_type="text/plain")
        random_proj = uuid.uuid4()
        resp = self.client.post(self.url, data={"project_uuid": str(random_proj), "file": upload})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {"error": "Project not found"})

    @patch(
        "temba.api.v2.internals.broadcasts.views.InternalBroadcastsUploadMediaEndpoint.authentication_classes",
        [],
    )
    @patch(
        "temba.api.v2.internals.broadcasts.views.InternalBroadcastsUploadMediaEndpoint.permission_classes",
        [],
    )
    def test_missing_file_returns_400(self):
        resp = self.client.post(self.url, data={"project_uuid": str(self.org.proj_uuid)})
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        # DRF ParseError returns {"detail": "..."}
        self.assertIn("detail", data)
        self.assertEqual(data["detail"], "file is required")


class TestUploadBroadcastMediaService(TembaTest):
    @override_settings(STORAGE_URL="https://bucket.example.com")
    def test_service_path_and_url_and_m4a(self):
        from temba.api.v2.internals.broadcasts.services import upload_broadcast_media

        # Ensure project UUID exists for completeness
        if not self.org.proj_uuid:
            self.org.proj_uuid = uuid.uuid4()
            self.org.save(update_fields=("proj_uuid",))

        upload = SimpleUploadedFile("clip.m4a", b"123", content_type="audio/m4a")

        with patch("temba.api.v2.internals.broadcasts.services.uuid4", return_value="fixeduuid"), patch(
            "temba.api.v2.internals.broadcasts.services.private_file_storage.save"
        ) as mock_save:
            mock_save.return_value = f"attachments/{self.org.id}/broadcasts/fixeduuid/clip.m4a"

            result = upload_broadcast_media(self.org, upload)
            self.assertEqual(result["type"], "audio/mp4")
            self.assertEqual(
                result["url"], f"https://bucket.example.com/attachments/{self.org.id}/broadcasts/fixeduuid/clip.m4a"
            )

            called_path = mock_save.call_args[0][0]
            self.assertEqual(called_path, f"attachments/{self.org.id}/broadcasts/fixeduuid/clip.m4a")

    @override_settings(STORAGE_URL="https://bucket.example.com")
    def test_service_plain_text(self):
        from temba.api.v2.internals.broadcasts.services import upload_broadcast_media

        upload = SimpleUploadedFile("note.txt", b"abc", content_type="text/plain")

        with patch("temba.api.v2.internals.broadcasts.services.uuid4", return_value="abc123"), patch(
            "temba.api.v2.internals.broadcasts.services.private_file_storage.save"
        ) as mock_save:
            mock_save.return_value = f"attachments/{self.org.id}/broadcasts/abc123/note.txt"

            result = upload_broadcast_media(self.org, upload)
            self.assertEqual(result["type"], "text/plain")
            self.assertEqual(
                result["url"], f"https://bucket.example.com/attachments/{self.org.id}/broadcasts/abc123/note.txt"
            )


class TestBroadcastsViewSet(TembaTest):
    url = "/api/v2/internals/broadcasts/"

    def _fake_user_and_project_serializer(self, user, org):
        class _Fake:
            def __init__(self, *args, **kwargs):
                self._validated = {"user": user, "project": type("P", (), {"org": org})}

            def is_valid(self, raise_exception=False):
                return True

            @property
            def validated_data(self):
                return self._validated

        return _Fake

    def test_create_missing_token_returns_403(self):
        data = {
            "text": "hello",
            "urns": ["tel:+12025550149"],
            "user": self.user.email,
            "project": str(self.org.proj_uuid),
        }
        with patch(
            "temba.api.v2.internals.broadcasts.views.UserAndProjectSerializer",
            new=self._fake_user_and_project_serializer(self.user, self.org),
        ):
            resp = self.client.post(self.url, data=data, content_type="application/json")
        self.assertEqual(resp.status_code, 403)

    @override_settings(ROUTER_FIXED_ACCESS_TOKEN="abc")
    def test_create_invalid_token_returns_403(self):
        data = {
            "text": "hello",
            "urns": ["tel:+12025550149"],
            "user": self.user.email,
            "project": str(self.org.proj_uuid),
        }
        with patch(
            "temba.api.v2.internals.broadcasts.views.UserAndProjectSerializer",
            new=self._fake_user_and_project_serializer(self.user, self.org),
        ):
            resp = self.client.post(f"{self.url}?token=wrong", data=data, content_type="application/json")
        self.assertEqual(resp.status_code, 403)

    @override_settings(ROUTER_FIXED_ACCESS_TOKEN="abc")
    def test_create_success(self):
        data = {
            "text": "hello world",
            "urns": ["tel:+12025550149"],
            "user": self.user.email,
            "project": str(self.org.proj_uuid),
        }
        with patch(
            "temba.api.v2.internals.broadcasts.views.UserAndProjectSerializer",
            new=self._fake_user_and_project_serializer(self.user, self.org),
        ):
            resp = self.client.post(f"{self.url}?token=abc", data=data, content_type="application/json")
        self.assertIn(resp.status_code, (200, 201))


class TestInternalBroadcastStatistics(TembaTest):
    stats_url = "/api/v2/internals/broadcasts-statistics"
    monthly_url = "/api/v2/internals/broadcasts-statistics-stats"

    @patch("temba.api.v2.internals.broadcasts.views.InternalBroadcastStatisticsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalBroadcastStatisticsEndpoint.permission_classes", [])
    def test_missing_and_invalid_project(self):
        resp = self.client.get(self.stats_url)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"error": "Project UUID not provided"})

        resp = self.client.get(self.stats_url, {"project_uuid": "00000000-0000-0000-0000-000000000000"})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {"error": "Project not found"})

    @patch("temba.api.v2.internals.broadcasts.views.InternalBroadcastStatisticsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalBroadcastStatisticsEndpoint.permission_classes", [])
    def test_filters_and_serializer_fields(self):
        c1 = self.create_contact("Alice", urns=["tel:+111"])
        c2 = self.create_contact("Bob", urns=["tel:+222"])

        from temba.templates.models import Template

        t = Template.objects.create(org=self.org, name="Welcome")

        b1 = Broadcast.create(self.org, self.admin, text="Hi", contacts=[c1], is_bulk_send=True)
        b1.name = "Alpha"
        b1.created_on = timezone.now() - dt.timedelta(days=10)
        b1.template_id = t.id
        b1.save(update_fields=("name", "created_on", "template_id"))
        BroadcastStatistics.objects.create(
            broadcast=b1,
            org=self.org,
            processed=5,
            sent=4,
            delivered=3,
            failed=1,
            read=2,
            contact_count=2,
            cost=1,
            template_price=0.5,
            currency="BRL",
        )

        b2 = Broadcast.create(self.org, self.admin, text="Hello", contacts=[c2], is_bulk_send=True)
        b2.name = "Beta"
        b2.created_on = timezone.now() - dt.timedelta(days=5)
        b2.template_id = 999999
        b2.save(update_fields=("name", "created_on", "template_id"))
        BroadcastStatistics.objects.create(broadcast=b2, org=self.org, sent=1)

        params = {
            "project_uuid": str(self.org.proj_uuid),
            "start_date": (timezone.now() - dt.timedelta(days=30)).isoformat(),
            "end_date": timezone.now().isoformat(),
            "name": "Beta",
            "id": str(b2.id),
            "limit": 1,
        }

        resp = self.client.get(self.stats_url, params)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["results"]
        self.assertEqual(len(data), 1)
        item = data[0]
        self.assertEqual(item["created_by"], self.admin.email)
        self.assertIn("statistics", item)
        self.assertIn("template", item)

    @patch(
        "temba.api.v2.internals.broadcasts.views.InternalBroadcastStatisticMontlyEndpoint.authentication_classes", []
    )
    @patch("temba.api.v2.internals.broadcasts.views.InternalBroadcastStatisticMontlyEndpoint.permission_classes", [])
    def test_monthly_endpoint(self):
        resp = self.client.get(self.monthly_url)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"error": "Project UUID not provided"})

        resp = self.client.get(self.monthly_url, {"project_uuid": "00000000-0000-0000-0000-000000000000"})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {"error": "Project not found"})

        resp = self.client.get(self.monthly_url, {"project_uuid": str(self.org.proj_uuid)})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("last_30_days_stats", body)
        self.assertIn("success_rate_30_days", body)


class TestInternalBroadcastGroupsStats(TembaTest):
    url = "/api/v2/internals/broadcasts/groups-stats"

    def _disable_auth(self):
        return patch(
            "temba.api.v2.internals.broadcasts.views.InternalBroadcastGroupsStatsEndpoint.authentication_classes",
            [],
        ), patch(
            "temba.api.v2.internals.broadcasts.views.InternalBroadcastGroupsStatsEndpoint.permission_classes",
            [],
        )

    def test_missing_and_invalid_project(self):
        # missing project_uuid
        with self._disable_auth()[0], self._disable_auth()[1]:
            resp = self.client.get(self.url, data={"groups": []})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"error": "Project UUID not provided"})

        # invalid project_uuid
        with self._disable_auth()[0], self._disable_auth()[1]:
            resp = self.client.get(
                self.url, data={"project_uuid": "00000000-0000-0000-0000-000000000000", "groups": []}
            )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {"error": "Project not found"})

    def test_no_groups_or_invalid_groups(self):
        # no groups provided
        with self._disable_auth()[0], self._disable_auth()[1]:
            resp = self.client.get(self.url, data={"project_uuid": str(self.org.proj_uuid)})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"error": "Groups not provided"})

        # invalid groups
        with self._disable_auth()[0], self._disable_auth()[1]:
            resp = self.client.get(
                self.url,
                data={"project_uuid": str(self.org.proj_uuid), "groups": ["00000000-0000-0000-0000-000000000000"]},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"error": "No valid groups found for this project"})

    def test_create_endpoint_with_overlapping_groups(self):
        # contacts
        alice = self.create_contact("Alice", urns=["tel:+111"])
        bob = self.create_contact("Bob", urns=["tel:+222"])
        carlos = self.create_contact("Carlos", urns=["tel:+333"])

        # groups with overlap on Bob
        g1 = self.create_group("G1", contacts=[alice, bob])
        g2 = self.create_group("G2", contacts=[bob, carlos])

        # ensure counts are populated for deterministic member_count
        from temba.contacts.models import ContactGroupCount

        ContactGroupCount.populate_for_group(g1)
        ContactGroupCount.populate_for_group(g2)

        with self._disable_auth()[0], self._disable_auth()[1]:
            resp = self.client.get(
                self.url,
                data={"project_uuid": str(self.org.proj_uuid), "groups": [str(g1.uuid), str(g2.uuid)]},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total_count"], g1.get_member_count() + g2.get_member_count())  # 2 + 2 = 4
        self.assertEqual(data["duplicates_count"], 1)  # only Bob overlaps
        self.assertEqual(data["distinct_count"], 3)  # unique across both groups

    def test_create_endpoint_single_group(self):
        # contacts
        alice = self.create_contact("Alice", urns=["tel:+111"])
        bob = self.create_contact("Bob", urns=["tel:+222"])
        g1 = self.create_group("G1", contacts=[alice, bob])

        from temba.contacts.models import ContactGroupCount

        ContactGroupCount.populate_for_group(g1)

        with self._disable_auth()[0], self._disable_auth()[1]:
            resp = self.client.get(self.url, data={"project_uuid": str(self.org.proj_uuid), "groups": [str(g1.uuid)]})

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total_count"], g1.get_member_count())
        self.assertEqual(data["duplicates_count"], 0)
        self.assertEqual(data["distinct_count"], g1.get_member_count())

    def test_accepts_comma_separated_group_ids(self):
        # contacts and groups
        a = self.create_contact("A", urns=["tel:+1"])
        b = self.create_contact("B", urns=["tel:+2"])
        c = self.create_contact("C", urns=["tel:+3"])
        g1 = self.create_group("G1", contacts=[a, b])
        g2 = self.create_group("G2", contacts=[b, c])  # overlap on B

        from temba.contacts.models import ContactGroupCount

        ContactGroupCount.populate_for_group(g1)
        ContactGroupCount.populate_for_group(g2)

        groups_param = f"{g1.id},{g2.id}"
        with self._disable_auth()[0], self._disable_auth()[1]:
            resp = self.client.get(self.url, data={"project_uuid": str(self.org.proj_uuid), "group_ids": groups_param})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total_count"], g1.get_member_count() + g2.get_member_count())
        self.assertEqual(data["duplicates_count"], 1)
        self.assertEqual(data["distinct_count"], 3)

    def test_accepts_comma_separated_group_uuids(self):
        a = self.create_contact("A", urns=["tel:+1"])
        b = self.create_contact("B", urns=["tel:+2"])
        c = self.create_contact("C", urns=["tel:+3"])
        g1 = self.create_group("G1", contacts=[a, b])
        g2 = self.create_group("G2", contacts=[b, c])

        from temba.contacts.models import ContactGroupCount

        ContactGroupCount.populate_for_group(g1)
        ContactGroupCount.populate_for_group(g2)

        groups_param = f"{g1.uuid},{g2.uuid}"
        with self._disable_auth()[0], self._disable_auth()[1]:
            resp = self.client.get(self.url, data={"project_uuid": str(self.org.proj_uuid), "groups": groups_param})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total_count"], g1.get_member_count() + g2.get_member_count())
        self.assertEqual(data["duplicates_count"], 1)
        self.assertEqual(data["distinct_count"], 3)

    def test_mixed_ids_and_uuids_and_dedupe(self):
        a = self.create_contact("A", urns=["tel:+1"])
        b = self.create_contact("B", urns=["tel:+2"])
        c = self.create_contact("C", urns=["tel:+3"])
        g1 = self.create_group("G1", contacts=[a, b])
        g2 = self.create_group("G2", contacts=[b, c])

        from temba.contacts.models import ContactGroupCount

        ContactGroupCount.populate_for_group(g1)
        ContactGroupCount.populate_for_group(g2)

        with self._disable_auth()[0], self._disable_auth()[1]:
            resp = self.client.get(
                self.url,
                data={
                    "project_uuid": str(self.org.proj_uuid),
                    "group_ids": [str(g1.id)],
                    "groups": [str(g1.uuid), str(g2.uuid)],  # g1 duplicated by id and uuid
                },
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total_count"], g1.get_member_count() + g2.get_member_count())
        self.assertEqual(data["duplicates_count"], 1)
        self.assertEqual(data["distinct_count"], 3)


class TestInternalWhatsappBroadcastJWT(TembaTest):
    url = "/api/v2/internals/whatsapp_broadcasts"

    @patch("temba.api.auth.jwt.settings")
    @patch("temba.api.auth.jwt.jwt.decode")
    @patch(
        "temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes",
        [OptionalJWTAuthentication],
    )
    def test_jwt_missing_project_returns_401(self, mock_decode, mock_settings):
        mock_settings.JWT_PUBLIC_KEY = "dummy"
        mock_decode.return_value = {}  # no project in payload
        resp = self.client.post(
            self.url,
            data={"msg": {"text": "Hi"}, "urns": ["tel:+111"]},
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token",
        )
        self.assertEqual(resp.status_code, 401)
        self.assertIn("Project not provided", resp.json().get("error", ""))

    @patch("temba.api.auth.jwt.settings")
    @patch("temba.api.auth.jwt.jwt.decode")
    @patch(
        "temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes",
        [OptionalJWTAuthentication],
    )
    def test_jwt_org_not_found_returns_404(self, mock_decode, mock_settings):
        mock_settings.JWT_PUBLIC_KEY = "dummy"
        mock_decode.return_value = {"project_uuid": "00000000-0000-0000-0000-000000000000"}
        resp = self.client.post(
            self.url,
            data={"msg": {"text": "Hi"}, "urns": ["tel:+12025550149"]},
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token",
        )
        self.assertEqual(resp.status_code, 404)
        self.assertIn("Project not found", resp.json().get("error", ""))

    @patch("temba.api.auth.jwt.settings")
    @patch("temba.api.auth.jwt.jwt.decode")
    @patch(
        "temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes",
        [OptionalJWTAuthentication],
    )
    def test_jwt_missing_email_returns_401(self, mock_decode, mock_settings):
        mock_settings.JWT_PUBLIC_KEY = "dummy"
        mock_decode.return_value = {"project_uuid": str(self.org.proj_uuid)}
        resp = self.client.post(
            self.url,
            data={"project": str(self.org.proj_uuid), "msg": {"text": "Hi"}, "urns": ["tel:+12025550149"]},
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token",
        )
        self.assertEqual(resp.status_code, 401)
        self.assertIn("User email not provided", resp.json().get("error", ""))

    @patch("temba.api.auth.jwt.settings")
    @patch("temba.api.auth.jwt.jwt.decode")
    @patch(
        "temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes",
        [OptionalJWTAuthentication],
    )
    def test_jwt_success_returns_201(self, mock_decode, mock_settings):
        mock_settings.JWT_PUBLIC_KEY = "dummy"
        mock_decode.return_value = {"project_uuid": str(self.org.proj_uuid), "email": "user@example.com"}

        resp = self.client.post(
            self.url,
            data={"project": str(self.org.proj_uuid), "msg": {"text": "Hi"}, "urns": ["tel:+12025550149"]},
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIn("id", data)
        self.assertEqual(data["metadata"].get("text"), "Hi")


class BroadcastWithStatisticsSerializerTests(TembaTest):
    def test_template_none_without_template_id(self):
        # create a broadcast with recipients but no template_id
        b = Broadcast.create(
            self.org, self.admin, text="Hello", urns=["tel:+12025550149"]
        )  # template_id defaults to None
        from temba.api.v2.internals.broadcasts.serializers import BroadcastWithStatisticsSerializer

        ser = BroadcastWithStatisticsSerializer(b)
        data = ser.data
        self.assertIn("template", data)
        self.assertIsNone(data["template"])  # covers return at line 80

    def test_template_present_when_template_exists(self):
        from temba.templates.models import Template
        from temba.api.v2.internals.broadcasts.serializers import BroadcastWithStatisticsSerializer

        b = Broadcast.create(self.org, self.admin, text="Hi", urns=["tel:+12025550149"])  # have recipients
        t = Template.objects.create(org=self.org, name="Welcome")
        b.template_id = t.id
        b.save(update_fields=("template_id",))

        ser = BroadcastWithStatisticsSerializer(b)
        data = ser.data
        self.assertEqual(data["template"], {"id": t.id, "name": "Welcome"})  # covers return at line 84


class TestInternalWhatsappBroadcastIdempotency(TembaTest):
    url = "/api/v2/internals/whatsapp_broadcasts"

    def setUp(self):
        super().setUp()
        from django_redis import get_redis_connection

        self.redis = get_redis_connection()
        self._cleanup_idempotency_keys()

    def tearDown(self):
        self._cleanup_idempotency_keys()
        super().tearDown()

    def _cleanup_idempotency_keys(self):
        for key in self.redis.scan_iter("idempotency:whatsapp_broadcasts:*"):
            self.redis.delete(key)

    def _redis_key(self, project_uuid, idem_key):
        return f"idempotency:whatsapp_broadcasts:{project_uuid}:{idem_key}"

    def _make_body(self, contact, text="Mensagem padrão"):
        return {
            "project": str(self.org.proj_uuid),
            "contacts": [str(contact.uuid)],
            "msg": {"text": text},
        }

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_no_header_processes_normally(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])
            body = self._make_body(contact)

            response = self.client.post(self.url, data=body, content_type="application/json")

            self.assertEqual(response.status_code, 201)

        existing = list(self.redis.scan_iter("idempotency:whatsapp_broadcasts:*"))
        self.assertEqual(existing, [], "No idempotency keys should be stored when the header is absent")

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_first_request_caches_response(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        idem_key = "test-key-first-request"

        with patch("rest_framework.request.Request.user", mock_user):
            contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])
            body = self._make_body(contact)

            response = self.client.post(
                self.url,
                data=body,
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=idem_key,
            )

            self.assertEqual(response.status_code, 201)

        redis_key = self._redis_key(self.org.proj_uuid, idem_key)
        raw = self.redis.get(redis_key)
        self.assertIsNotNone(raw, "Idempotency entry should be persisted after a successful request")

        from temba.utils import json as temba_json

        cached = temba_json.loads(raw)
        self.assertEqual(cached["state"], "done")
        self.assertEqual(cached["status"], 201)
        self.assertIn("body", cached)
        self.assertEqual(cached["body"]["id"], response.json()["id"])

        ttl = self.redis.ttl(redis_key)
        self.assertGreater(ttl, 86000)
        self.assertLessEqual(ttl, 86400)

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_replay_same_body_returns_cached_response(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        idem_key = "test-key-replay"

        with patch("rest_framework.request.Request.user", mock_user):
            contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])
            body = self._make_body(contact)

            initial_count = Broadcast.objects.count()

            first = self.client.post(
                self.url,
                data=body,
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=idem_key,
            )
            self.assertEqual(first.status_code, 201)
            first_data = first.json()

            second = self.client.post(
                self.url,
                data=body,
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=idem_key,
            )
            self.assertEqual(second.status_code, 201)
            second_data = second.json()

            self.assertEqual(first_data, second_data, "Replay must return identical body")
            self.assertEqual(
                Broadcast.objects.count(),
                initial_count + 1,
                "Broadcast must be created exactly once across the two requests",
            )

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_replay_different_body_returns_409(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        idem_key = "test-key-conflict"

        with patch("rest_framework.request.Request.user", mock_user):
            contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])

            first = self.client.post(
                self.url,
                data=self._make_body(contact, text="primeira mensagem"),
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=idem_key,
            )
            self.assertEqual(first.status_code, 201)

            second = self.client.post(
                self.url,
                data=self._make_body(contact, text="segunda mensagem diferente"),
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=idem_key,
            )
            self.assertEqual(second.status_code, 409)
            self.assertIn("different body", second.json()["error"])

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_replay_different_custom_data_returns_409(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        idem_key = "test-key-custom-data"

        with patch("rest_framework.request.Request.user", mock_user):
            contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])
            first_body = {
                "project": str(self.org.proj_uuid),
                "contacts": [str(contact.uuid)],
                "msg": {"text": "Hi", "custom_data": {"order_id": "1"}},
            }
            second_body = {
                "project": str(self.org.proj_uuid),
                "contacts": [str(contact.uuid)],
                "msg": {"text": "Hi", "custom_data": {"order_id": "2"}},
            }

            first = self.client.post(
                self.url, data=first_body, content_type="application/json", HTTP_IDEMPOTENCY_KEY=idem_key
            )
            self.assertEqual(first.status_code, 201)

            second = self.client.post(
                self.url, data=second_body, content_type="application/json", HTTP_IDEMPOTENCY_KEY=idem_key
            )
            self.assertEqual(second.status_code, 409)
            self.assertIn("different body", second.json()["error"])

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_concurrent_inflight_returns_409(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        from temba.utils import json as temba_json

        idem_key = "test-key-inflight"
        redis_key = self._redis_key(self.org.proj_uuid, idem_key)
        self.redis.set(
            redis_key,
            temba_json.dumps({"state": "inflight", "body_hash": "deadbeef"}),
            ex=60,
        )

        with patch("rest_framework.request.Request.user", mock_user):
            contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])
            response = self.client.post(
                self.url,
                data=self._make_body(contact),
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=idem_key,
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn("already being processed", response.json()["error"])

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_blank_header_treated_as_missing(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])
            body = self._make_body(contact)

            first = self.client.post(
                self.url,
                data=body,
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY="   ",
            )
            self.assertEqual(first.status_code, 201)

            second = self.client.post(
                self.url,
                data=body,
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY="   ",
            )
            self.assertEqual(second.status_code, 201, "Blank key must bypass dedupe entirely")

        existing = list(self.redis.scan_iter("idempotency:whatsapp_broadcasts:*"))
        self.assertEqual(existing, [], "Blank Idempotency-Key must not touch Redis")

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_validation_failure_releases_key(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        idem_key = "test-key-validation-failure"

        with patch("rest_framework.request.Request.user", mock_user):
            invalid_body = {
                "project": str(self.org.proj_uuid),
                "msg": {"text": "missing recipients"},
            }
            failure = self.client.post(
                self.url,
                data=invalid_body,
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=idem_key,
            )
            self.assertEqual(failure.status_code, 400)

            self.assertIsNone(
                self.redis.get(self._redis_key(self.org.proj_uuid, idem_key)),
                "Idempotency marker must be released after validation failures",
            )

            contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])
            valid = self.client.post(
                self.url,
                data=self._make_body(contact),
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=idem_key,
            )
            self.assertEqual(
                valid.status_code,
                201,
                "Reusing the same key after a validation failure must succeed",
            )

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_long_header_treated_as_missing(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        oversized_key = "x" * 201

        with patch("rest_framework.request.Request.user", mock_user):
            contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])
            response = self.client.post(
                self.url,
                data=self._make_body(contact),
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=oversized_key,
            )
            self.assertEqual(response.status_code, 201)

        existing = list(self.redis.scan_iter("idempotency:whatsapp_broadcasts:*"))
        self.assertEqual(existing, [], "Oversized Idempotency-Key must not be stored")

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_project_not_found_releases_key(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        idem_key = "test-key-org-not-found"

        with patch("rest_framework.request.Request.user", mock_user):
            body = {
                "project": str(self.org.uuid),  # org.uuid != org.proj_uuid -> Org.DoesNotExist
                "msg": {"text": "Test"},
            }
            response = self.client.post(
                self.url,
                data=body,
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=idem_key,
            )
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"error": "Project not found"})

        self.assertIsNone(
            self.redis.get(self._redis_key(self.org.uuid, idem_key)),
            "Idempotency marker must be released when the project is not found",
        )

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_missing_email_releases_key(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = None

        idem_key = "test-key-no-email"

        with patch("rest_framework.request.Request.user", mock_user):
            contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])
            response = self.client.post(
                self.url,
                data=self._make_body(contact),
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=idem_key,
            )
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json(), {"error": "User email not provided"})

        self.assertIsNone(
            self.redis.get(self._redis_key(self.org.proj_uuid, idem_key)),
            "Idempotency marker must be released when the user email is missing",
        )

    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_unexpected_exception_releases_key(self):
        from temba.api.v2.serializers import WhatsappBroadcastWriteSerializer

        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        idem_key = "test-key-exception"

        with patch("rest_framework.request.Request.user", mock_user), patch.object(
            WhatsappBroadcastWriteSerializer, "save", side_effect=RuntimeError("simulated downstream failure")
        ):
            contact = self.create_contact("Junior", urns=["whatsapp:5561912345678"])
            with self.assertRaises(RuntimeError):
                self.client.post(
                    self.url,
                    data=self._make_body(contact),
                    content_type="application/json",
                    HTTP_IDEMPOTENCY_KEY=idem_key,
                )

        self.assertIsNone(
            self.redis.get(self._redis_key(self.org.proj_uuid, idem_key)),
            "Idempotency marker must be released after an unexpected exception",
        )


class TestIdempotencyHelpers(TembaTest):
    """Unit tests for the idempotency helper module."""

    def setUp(self):
        super().setUp()
        from django_redis import get_redis_connection

        self.redis = get_redis_connection()
        self._cleanup_idempotency_keys()

    def tearDown(self):
        self._cleanup_idempotency_keys()
        super().tearDown()

    def _cleanup_idempotency_keys(self):
        for key in self.redis.scan_iter("idempotency:whatsapp_broadcasts:*"):
            self.redis.delete(key)

    def _redis_key(self, project_uuid, idem_key):
        return f"idempotency:whatsapp_broadcasts:{project_uuid}:{idem_key}"

    def test_extract_idempotency_key_strips_surrounding_whitespace(self):
        from temba.api.v2.internals.broadcasts.idempotency import extract_idempotency_key

        request = MagicMock()
        request.headers = {"Idempotency-Key": "  abc-123  "}
        self.assertEqual(extract_idempotency_key(request), "abc-123")

    def test_extract_idempotency_key_returns_none_when_header_missing(self):
        from temba.api.v2.internals.broadcasts.idempotency import extract_idempotency_key

        request = MagicMock()
        request.headers = {}
        self.assertIsNone(extract_idempotency_key(request))

    def test_compute_body_hash_is_key_order_independent(self):
        from temba.api.v2.internals.broadcasts.idempotency import compute_body_hash

        request_a = MagicMock()
        request_a.data = {"a": 1, "b": 2, "nested": {"y": 4, "x": 3}}
        request_b = MagicMock()
        request_b.data = {"nested": {"x": 3, "y": 4}, "b": 2, "a": 1}

        self.assertEqual(compute_body_hash(request_a), compute_body_hash(request_b))

    def test_compute_body_hash_is_unchanged_for_json(self):
        import hashlib

        from temba.api.v2.internals.broadcasts.idempotency import compute_body_hash
        from temba.utils import json as temba_json

        # keys stored by earlier versions must keep replaying, so the hash of a JSON body is what it always was
        data = {"project": "p1", "msg": {"text": "Hi", "attachments": ["image/png:https://example.com/a.png"]}}
        request = MagicMock()
        request.data = data

        expected = hashlib.sha256(temba_json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()
        self.assertEqual(expected, compute_body_hash(request))

    def test_compute_media_body_hash(self):
        from temba.api.v2.internals.broadcasts.idempotency import compute_body_hash, compute_media_body_hash

        payload = {"project": "p1", "msg": {"text": "Hi"}, "nested": {"y": 4, "x": 3}}
        sha_a, sha_b = "a" * 64, "b" * 64

        base = compute_media_body_hash(payload, [sha_a, sha_b])
        self.assertEqual(64, len(base))

        # the order of the keys of the payload doesn't matter
        reordered = {"nested": {"x": 3, "y": 4}, "msg": {"text": "Hi"}, "project": "p1"}
        self.assertEqual(base, compute_media_body_hash(reordered, [sha_a, sha_b]))

        # but the bytes of any file do
        self.assertNotEqual(base, compute_media_body_hash(payload, [sha_a, "c" * 64]))
        self.assertNotEqual(base, compute_media_body_hash(payload, [sha_a]))
        self.assertNotEqual(base, compute_media_body_hash(payload, []))

        # and so does their order
        self.assertNotEqual(base, compute_media_body_hash(payload, [sha_b, sha_a]))

        # and the payload
        self.assertNotEqual(base, compute_media_body_hash({**payload, "msg": {"text": "Hello"}}, [sha_a, sha_b]))

        # the files can be given as any sequence
        self.assertEqual(base, compute_media_body_hash(payload, (sha_a, sha_b)))

        # it is not the hash of a JSON body, even of the same payload
        request = MagicMock()
        request.data = payload
        self.assertNotEqual(compute_body_hash(request), compute_media_body_hash(payload, []))

    def test_compute_media_body_hash_falls_back_for_non_serializable_payload(self):
        from temba.api.v2.internals.broadcasts.idempotency import compute_media_body_hash

        class Unserializable:
            def __repr__(self):
                return "Unserializable(payload)"

        result = compute_media_body_hash(Unserializable(), ["a" * 64])
        self.assertEqual(64, len(result))
        self.assertNotEqual(result, compute_media_body_hash(Unserializable(), ["b" * 64]))

    def test_compute_body_hash_falls_back_for_non_serializable_data(self):
        from temba.api.v2.internals.broadcasts.idempotency import compute_body_hash

        class Unserializable:
            def __repr__(self):
                return "Unserializable(payload)"

        request = MagicMock()
        request.data = Unserializable()
        result = compute_body_hash(request)
        self.assertEqual(len(result), 64)  # sha256 hex digest length

    def test_idempotency_lookup_returns_miss_on_first_call(self):
        from temba.api.v2.internals.broadcasts.idempotency import LOOKUP_MISS, idempotency_lookup

        state, cached = idempotency_lookup("project-x", "fresh-key", "hash1")

        self.assertEqual(state, LOOKUP_MISS)
        self.assertIsNone(cached)
        self.assertIsNotNone(self.redis.get(self._redis_key("project-x", "fresh-key")))

    def test_idempotency_lookup_returns_hit_when_done_with_matching_hash(self):
        from temba.api.v2.internals.broadcasts.idempotency import (
            LOOKUP_HIT,
            idempotency_lookup,
            idempotency_store_success,
        )

        idempotency_store_success("project-x", "done-key", "hash1", 201, {"id": 7})

        state, cached = idempotency_lookup("project-x", "done-key", "hash1")

        self.assertEqual(state, LOOKUP_HIT)
        self.assertIsNotNone(cached)
        self.assertEqual(cached["status"], 201)
        self.assertEqual(cached["body"], {"id": 7})

    def test_idempotency_lookup_returns_conflict_when_hash_differs(self):
        from temba.api.v2.internals.broadcasts.idempotency import (
            LOOKUP_CONFLICT,
            idempotency_lookup,
            idempotency_store_success,
        )

        idempotency_store_success("project-x", "conflict-key", "hash1", 201, {"id": 7})

        state, cached = idempotency_lookup("project-x", "conflict-key", "hash2")

        self.assertEqual(state, LOOKUP_CONFLICT)
        self.assertIsNone(cached)

    def test_idempotency_lookup_returns_inflight_on_corrupted_json(self):
        from temba.api.v2.internals.broadcasts.idempotency import LOOKUP_INFLIGHT, idempotency_lookup

        self.redis.set(self._redis_key("project-x", "corrupt-key"), "not-json", ex=60)

        state, cached = idempotency_lookup("project-x", "corrupt-key", "hash1")

        self.assertEqual(state, LOOKUP_INFLIGHT)
        self.assertIsNone(cached)

    def test_idempotency_lookup_returns_inflight_for_unknown_state(self):
        from temba.api.v2.internals.broadcasts.idempotency import LOOKUP_INFLIGHT, idempotency_lookup
        from temba.utils import json as temba_json

        self.redis.set(
            self._redis_key("project-x", "weird-state-key"),
            temba_json.dumps({"state": "exploding", "body_hash": "hash1"}),
            ex=60,
        )

        state, cached = idempotency_lookup("project-x", "weird-state-key", "hash1")

        self.assertEqual(state, LOOKUP_INFLIGHT)
        self.assertIsNone(cached)

    def test_idempotency_lookup_handles_race_when_slot_expires(self):
        """SETNX loses to an existing key, but a GET right after returns None because the
        key just expired. The reclaim path retries SETNX and wins."""
        from temba.api.v2.internals.broadcasts.idempotency import LOOKUP_MISS, idempotency_lookup

        redis_mock = MagicMock()
        redis_mock.set.side_effect = [False, True]  # initial NX fails, reclaim NX wins
        redis_mock.get.return_value = None

        with patch(
            "temba.api.v2.internals.broadcasts.idempotency.get_redis_connection",
            return_value=redis_mock,
        ):
            state, cached = idempotency_lookup("project-x", "race-key", "hash1")

        self.assertEqual(state, LOOKUP_MISS)
        self.assertIsNone(cached)

    def test_idempotency_lookup_returns_inflight_when_double_race_loses(self):
        """Pathological case: both SETNX attempts fail and GETs return None. We give up
        and report inflight so the caller returns 409 instead of overwriting blindly."""
        from temba.api.v2.internals.broadcasts.idempotency import LOOKUP_INFLIGHT, idempotency_lookup

        redis_mock = MagicMock()
        redis_mock.set.side_effect = [False, False]
        redis_mock.get.return_value = None

        with patch(
            "temba.api.v2.internals.broadcasts.idempotency.get_redis_connection",
            return_value=redis_mock,
        ):
            state, cached = idempotency_lookup("project-x", "double-race-key", "hash1")

        self.assertEqual(state, LOOKUP_INFLIGHT)
        self.assertIsNone(cached)

    def test_idempotency_store_success_persists_payload_with_ttl(self):
        from temba.api.v2.internals.broadcasts.idempotency import TTL_SECONDS, idempotency_store_success
        from temba.utils import json as temba_json

        idempotency_store_success("project-x", "store-key", "hash1", 201, {"id": 42, "name": "x"})

        redis_key = self._redis_key("project-x", "store-key")
        raw = self.redis.get(redis_key)
        self.assertIsNotNone(raw)

        cached = temba_json.loads(raw)
        self.assertEqual(cached["state"], "done")
        self.assertEqual(cached["status"], 201)
        self.assertEqual(cached["body"], {"id": 42, "name": "x"})
        self.assertEqual(cached["body_hash"], "hash1")

        ttl = self.redis.ttl(redis_key)
        self.assertGreater(ttl, TTL_SECONDS - 60)
        self.assertLessEqual(ttl, TTL_SECONDS)

    def test_idempotency_release_deletes_existing_marker(self):
        from temba.api.v2.internals.broadcasts.idempotency import idempotency_release

        redis_key = self._redis_key("project-x", "release-key")
        self.redis.set(redis_key, "marker", ex=60)

        idempotency_release("project-x", "release-key")

        self.assertIsNone(self.redis.get(redis_key))

    def test_idempotency_release_is_a_noop_when_no_marker_exists(self):
        from temba.api.v2.internals.broadcasts.idempotency import idempotency_release

        # Must not raise even when the key was never set.
        idempotency_release("project-x", "never-existed")
        self.assertIsNone(self.redis.get(self._redis_key("project-x", "never-existed")))


GIF_BYTES = b"GIF89a\x01\x00\x01\x00\x00\x00\x00;"
ENDPOINT = InternalWhatsappBroadcastsEndpoint


class InlineMediaTestMixin:
    """
    Helpers to send media files with a broadcast to the internal endpoint, as multipart/form-data. S3 is stubbed where
    the files are saved, Redis is the real one, and the caller is a user of the org that is let in (as in the other
    tests of this endpoint), unless the test sets up its own authentication.
    """

    url = "/api/v2/internals/whatsapp_broadcasts"
    user_email = "mockuser@example.com"

    def setUp(self):
        super().setUp()

        # the endpoint is not atomic, but the exception handler of REST framework rolls back the transaction that the
        # test is in when it handles an error (a 400 or a 403) unless this is off, as in the other API tests
        connection.settings_dict["ATOMIC_REQUESTS"] = False
        self.addCleanup(connection.settings_dict.__setitem__, "ATOMIC_REQUESTS", True)

        _dedup_redis.cache_clear()
        self.addCleanup(_dedup_redis.cache_clear)

        # the other org of the tests has no project yet
        self.org2.proj_uuid = uuid.uuid4()
        self.org2.save(update_fields=("proj_uuid",))

        self.jpeg = read_test_media("steve.marten.jpg")
        self.jpeg_sha256 = hashlib.sha256(self.jpeg).hexdigest()
        self.mp4 = read_test_media("snow.mp4")
        self.audio = audio_only_mp4_bytes()

        patcher = patch("temba.mailroom.queue_broadcast")
        self.queue = patcher.start()
        self.addCleanup(patcher.stop)

        patcher = patch.object(private_file_storage, "save", return_value="saved")
        self.save = patcher.start()
        self.addCleanup(patcher.stop)

        self.redis = get_redis_connection()
        self.clear_idempotency_keys()
        self.addCleanup(self.clear_idempotency_keys)

    def clear_idempotency_keys(self):
        for key in self.redis.scan_iter("idempotency:whatsapp_broadcasts:*"):
            self.redis.delete(key)

    def idempotency_keys(self) -> list:
        return list(self.redis.scan_iter("idempotency:whatsapp_broadcasts:*"))

    def dedup_keys(self) -> list:
        return list(self.redis.scan_iter("broadcast_media:*"))

    def idempotency_redis_key(self, key: str) -> str:
        return f"idempotency:whatsapp_broadcasts:{self.org.proj_uuid}:{key}"

    def payload(self, **extra) -> dict:
        return {
            "project": str(self.org.proj_uuid),
            "urns": ["whatsapp:5561912345678"],
            "msg": {"text": "Hello"},
            **extra,
        }

    def key(self, org, sha256: str, extension: str) -> str:
        return f"attachments/{org.id}/broadcasts/{sha256}.{extension}"

    def attachment(self, org, sha256: str, mime: str, extension: str) -> str:
        return f"{mime}:{settings.STORAGE_URL}/{self.key(org, sha256, extension)}"

    def jpeg_attachment(self, org=None) -> str:
        return self.attachment(org or self.org, self.jpeg_sha256, "image/jpeg", "jpg")

    def upload(self, data: bytes, name: str = "file.bin", content_type: str = "application/octet-stream"):
        return SimpleUploadedFile(name, data, content_type)

    def form(self, payload=None, files=()) -> dict:
        payload = self.payload() if payload is None else payload
        fields = {"payload": payload if isinstance(payload, str) else json.dumps(payload)}
        if files:
            fields["files"] = [f if isinstance(f, SimpleUploadedFile) else self.upload(f) for f in files]
        return fields

    def post_form(self, fields: dict, key: str = None, **extra):
        """
        Posts a form as a user of the org that is let in, which is how the other tests of this endpoint call it
        """
        if key:
            extra["HTTP_IDEMPOTENCY_KEY"] = key

        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = self.user_email

        with patch.object(ENDPOINT, "authentication_classes", []), patch.object(ENDPOINT, "permission_classes", []):
            with patch("rest_framework.request.Request.user", mock_user):
                return self.client.post(self.url, fields, **extra)

    def post_multipart(self, payload=None, files=(), key: str = None, **extra):
        return self.post_form(self.form(payload, files), key=key, **extra)

    def post_json(self, payload=None, key: str = None, **extra):
        if key:
            extra["HTTP_IDEMPOTENCY_KEY"] = key

        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = self.user_email

        with patch.object(ENDPOINT, "authentication_classes", []), patch.object(ENDPOINT, "permission_classes", []):
            with patch("rest_framework.request.Request.user", mock_user):
                return self.client.post(
                    self.url,
                    json.dumps(self.payload() if payload is None else payload),
                    content_type="application/json",
                    **extra,
                )

    def spy_serializers(self):
        seen = []
        original = WhatsappBroadcastWriteSerializer.is_valid

        def is_valid(serializer, *args, **kwargs):
            seen.append(type(serializer))
            return original(serializer, *args, **kwargs)

        patcher = patch.object(WhatsappBroadcastWriteSerializer, "is_valid", autospec=True, side_effect=is_valid)
        patcher.start()
        self.addCleanup(patcher.stop)
        return seen

    def last_broadcast(self) -> Broadcast:
        return Broadcast.objects.order_by("-id").first()


class TestInternalWhatsappBroadcastInlineMedia(InlineMediaTestMixin, TembaTest):
    """
    US1 to US3: media files sent with a broadcast to POST /api/v2/internals/whatsapp_broadcasts
    """

    def test_json_request_is_unchanged(self):
        seen = self.spy_serializers()

        with patch("temba.api.v2.internals.broadcasts.views.compute_body_hash", wraps=compute_body_hash) as json_hash:
            with patch("temba.api.v2.internals.broadcasts.views.compute_media_body_hash") as media_hash:
                response = self.post_json(key="json-request")

        self.assertEqual(201, response.status_code)
        self.assertEqual([WhatsappBroadcastWriteSerializer], seen)
        self.assertEqual({"text": "Hello"}, response.json()["metadata"])
        self.assertEqual({"text": "Hello"}, self.last_broadcast().metadata)

        # the body of a JSON request is hashed as it always was, and nothing is stored or looked up for files
        json_hash.assert_called_once()
        media_hash.assert_not_called()
        self.save.assert_not_called()
        self.assertEqual([], self.dedup_keys())

        cached = json.loads(self.redis.get(self.idempotency_redis_key("json-request")))
        self.assertEqual("done", cached["state"])
        self.assertEqual(201, cached["status"])

    def test_single_image(self):
        seen = self.spy_serializers()

        response = self.post_multipart(files=[self.upload(self.jpeg, "photo.bin", "application/octet-stream")])

        self.assertEqual(201, response.status_code)
        self.assertEqual([api_serializers.WhatsappBroadcastWithMediaWriteSerializer], seen)

        expected = self.jpeg_attachment()
        self.assertEqual(
            f"image/jpeg:{settings.STORAGE_URL}/attachments/{self.org.id}/broadcasts/{self.jpeg_sha256}.jpg", expected
        )
        self.assertEqual({"text": "Hello", "attachments": [expected]}, response.json()["metadata"])
        self.assertEqual({"text": "Hello", "attachments": [expected]}, self.last_broadcast().metadata)
        self.assertNotIn("X-Amz-", expected)
        self.assertNotIn("?", expected)

        self.save.assert_called_once()
        key, file = self.save.call_args.args
        self.assertEqual(self.key(self.org, self.jpeg_sha256, "jpg"), key)
        self.assertEqual("image/jpeg", file.content_type)
        self.queue.assert_called_once_with(self.last_broadcast())

    def test_multipart_without_files_is_like_json(self):
        json_response = self.post_json()
        self.assertEqual(201, json_response.status_code)

        response = self.post_multipart()

        self.assertEqual(201, response.status_code)
        self.assertEqual(json_response.json()["metadata"], response.json()["metadata"])
        self.save.assert_not_called()

    def test_files_go_after_the_urls_in_the_payload(self):
        payload = self.payload(
            msg={
                "text": "Hi",
                "attachments": ["image/png:https://example.com/a.png", "application/pdf:https://example.com/b.pdf"],
            }
        )

        response = self.post_multipart(payload, files=[self.jpeg, self.mp4, self.audio])

        self.assertEqual(201, response.status_code)
        self.assertEqual(
            [
                "image/png:https://example.com/a.png",
                "application/pdf:https://example.com/b.pdf",
                self.jpeg_attachment(),
                self.attachment(self.org, hashlib.sha256(self.mp4).hexdigest(), "video/mp4", "mp4"),
                self.attachment(self.org, hashlib.sha256(self.audio).hexdigest(), "audio/mp4", "m4a"),
            ],
            response.json()["metadata"]["attachments"],
        )
        self.assertEqual(response.json()["metadata"]["attachments"], self.last_broadcast().metadata["attachments"])
        self.assertEqual(3, self.save.call_count)

    def test_same_file_twice_in_one_request(self):
        response = self.post_multipart(files=[self.jpeg, self.mp4, self.jpeg])

        self.assertEqual(201, response.status_code)
        attachments = response.json()["metadata"]["attachments"]
        self.assertEqual(attachments[0], attachments[2])
        self.assertNotEqual(attachments[0], attachments[1])
        self.assertEqual(2, self.save.call_count)

    def test_same_file_in_two_requests_is_stored_once(self):
        first = self.post_multipart(files=[self.jpeg])
        second = self.post_multipart(files=[self.jpeg])

        self.assertEqual(201, first.status_code)
        self.assertEqual(201, second.status_code)
        self.save.assert_called_once()
        self.assertNotEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(first.json()["metadata"]["attachments"], second.json()["metadata"]["attachments"])

        cache_key = f"broadcast_media:{self.org.id}:{self.jpeg_sha256}"
        self.assertEqual(self.jpeg_attachment().encode(), _dedup_redis().get(cache_key))
        self.assertAlmostEqual(BROADCAST_MEDIA_DEDUP_TTL_SECONDS, _dedup_redis().ttl(cache_key), delta=10)

    def test_same_file_for_another_org_is_stored_again(self):
        self.assertEqual(201, self.post_multipart(files=[self.jpeg]).status_code)

        response = self.post_multipart(self.payload(project=str(self.org2.proj_uuid)), files=[self.jpeg])

        self.assertEqual(201, response.status_code)
        self.assertEqual([self.jpeg_attachment(self.org2)], response.json()["metadata"]["attachments"])
        self.assertEqual(2, self.save.call_count)
        self.assertEqual(self.key(self.org2, self.jpeg_sha256, "jpg"), self.save.call_args.args[0])

    # --- AC-8: who the caller is and what project it acts on

    @patch("temba.api.auth.jwt.settings")
    @patch("temba.api.auth.jwt.jwt.decode")
    def post_with_jwt(self, mock_decode, mock_settings, claims: dict, fields: dict):
        mock_settings.JWT_PUBLIC_KEY = "dummy"
        mock_decode.return_value = claims

        with patch.object(ENDPOINT, "authentication_classes", [OptionalJWTAuthentication]):
            return self.client.post(self.url, fields, HTTP_AUTHORIZATION="Bearer token")

    def test_jwt_with_project_claims(self):
        claims = {"project_uuid": str(self.org.proj_uuid), "email": "user@example.com"}

        # the project can be in the payload as well, as long as it is the same one
        for name, payload in (
            ("project in the payload", self.payload()),
            ("no project in the payload", {k: v for k, v in self.payload().items() if k != "project"}),
        ):
            with self.subTest(name):
                self.save.reset_mock()
                response = self.post_with_jwt(claims=claims, fields=self.form(payload, [self.jpeg]))

                self.assertEqual(201, response.status_code, response.content)
                self.assertEqual([self.jpeg_attachment()], response.json()["metadata"]["attachments"])
                self.assertEqual(self.org, self.last_broadcast().org)

    def test_jwt_project_that_differs_from_the_payload_is_rejected(self):
        claims = {"project_uuid": str(self.org.proj_uuid), "email": "user@example.com"}
        payload = self.payload(project=str(self.org2.proj_uuid))

        response = self.post_with_jwt(claims=claims, fields=self.form(payload, [self.jpeg]))

        self.assertEqual(403, response.status_code)
        self.assertEqual({"error": "Project mismatch"}, response.json())
        self.save.assert_not_called()
        self.assertEqual(0, Broadcast.objects.count())
        self.assertEqual([], self.dedup_keys())

    def test_jwt_without_project_is_not_let_pick_one_in_the_payload(self):
        response = self.post_with_jwt(claims={"email": "user@example.com"}, fields=self.form(files=[self.jpeg]))

        self.assertEqual(401, response.status_code)
        self.assertEqual({"error": "Project not provided"}, response.json())
        self.save.assert_not_called()
        self.assertEqual(0, Broadcast.objects.count())

    def test_project_in_the_payload_of_an_internal_user(self):
        response = self.post_multipart(files=[self.jpeg])

        self.assertEqual(201, response.status_code)
        self.assertEqual(self.org, self.last_broadcast().org)
        self.assertEqual(self.user_email, self.last_broadcast().created_by.email)

    def test_project_not_found_and_not_provided(self):
        response = self.post_multipart(self.payload(project=str(uuid.uuid4())), files=[self.jpeg])
        self.assertEqual(404, response.status_code)
        self.assertEqual({"error": "Project not found"}, response.json())

        response = self.post_multipart({"urns": ["whatsapp:5561912345678"], "msg": {"text": "Hi"}}, files=[self.jpeg])
        self.assertEqual(401, response.status_code)
        self.assertEqual({"error": "Project not provided"}, response.json())

        self.save.assert_not_called()
        self.assertEqual(0, Broadcast.objects.count())


class TestInternalWhatsappBroadcastMultipartPermissions(InlineMediaTestMixin, TembaTest):
    """
    The permissions of the endpoint, which find the project to check in the body of the request, decide the same for
    a multipart request, whose body has it inside the payload.
    """

    def fixed_user(self, user):
        class FixedUserAuthentication(BaseAuthentication):
            def authenticate(self, request):
                return (user, None)

        return FixedUserAuthentication

    def post_as(self, user, fields: dict, *, as_json: dict = None, **extra):
        with patch.object(ENDPOINT, "authentication_classes", [self.fixed_user(user)]):
            if as_json is not None:
                return self.client.post(self.url, json.dumps(as_json), content_type="application/json", **extra)
            return self.client.post(self.url, fields, **extra)

    def test_member_of_the_project(self):
        payload = self.payload()

        json_response = self.post_as(self.admin, None, as_json=payload)
        response = self.post_as(self.admin, self.form(payload, [self.jpeg]))

        self.assertEqual(201, json_response.status_code)
        self.assertEqual(201, response.status_code)
        self.assertEqual(self.org, self.last_broadcast().org)
        self.assertEqual([self.jpeg_attachment()], response.json()["metadata"]["attachments"])

    def test_not_a_member_of_the_project(self):
        # admin2 is of org2, and the payload is for org
        payload = self.payload()

        json_response = self.post_as(self.admin2, None, as_json=payload)
        response = self.post_as(self.admin2, self.form(payload, [self.jpeg]), HTTP_IDEMPOTENCY_KEY="not-a-member")

        # denied as for JSON, before anything is claimed, read or stored
        self.assertEqual(403, json_response.status_code)
        self.assertEqual(403, response.status_code)
        self.assertEqual(json_response.json(), response.json())

        self.save.assert_not_called()
        self.assertEqual(0, Broadcast.objects.count())
        self.assertEqual([], self.idempotency_keys())
        self.assertEqual([], self.dedup_keys())
        self.queue.assert_not_called()

    def test_not_a_member_with_each_key_for_the_project(self):
        for key in ("project", "project_uuid"):
            with self.subTest(key):
                payload = {"urns": ["whatsapp:5561912345678"], "msg": {"text": "Hi"}, key: str(self.org.proj_uuid)}

                json_response = self.post_as(self.admin2, None, as_json=payload)
                response = self.post_as(self.admin2, self.form(payload, [self.jpeg]))

                self.assertEqual(403, json_response.status_code)
                self.assertEqual(403, response.status_code)
                self.assertEqual(json_response.json(), response.json())

        self.save.assert_not_called()
        self.assertEqual(0, Broadcast.objects.count())

    def test_unknown_project(self):
        payload = self.payload(project=str(uuid.uuid4()))

        json_response = self.post_as(self.admin, None, as_json=payload)
        response = self.post_as(self.admin, self.form(payload, [self.jpeg]))

        self.assertEqual(403, json_response.status_code)
        self.assertEqual(403, response.status_code)
        self.save.assert_not_called()

    def test_no_project_in_the_payload_is_left_to_the_view(self):
        payload = {"urns": ["whatsapp:5561912345678"], "msg": {"text": "Hi"}}

        json_response = self.post_as(self.admin, None, as_json=payload)
        response = self.post_as(self.admin, self.form(payload, [self.jpeg]))

        self.assertEqual(401, json_response.status_code)
        self.assertEqual(401, response.status_code)
        self.assertEqual(json_response.json(), response.json())

    def test_project_in_the_query_and_in_the_payload_must_agree(self):
        payload = self.payload()
        query = f"?project={self.org2.proj_uuid}"

        original_url = self.url
        self.url = original_url + query
        try:
            json_response = self.post_as(self.admin, None, as_json=payload)
            response = self.post_as(self.admin, self.form(payload, [self.jpeg]))
        finally:
            self.url = original_url

        self.assertEqual(403, json_response.status_code)
        self.assertEqual(403, response.status_code)
        self.save.assert_not_called()

    def test_trusted_internal_caller_can_act_on_any_project(self):
        # the permission trusted callers have is the one that lets them, as for JSON
        payload = self.payload(project=str(self.org2.proj_uuid))

        with patch("weni.internal.permissions.CanCommunicateInternally.has_permission", return_value=True):
            json_response = self.post_as(self.admin, None, as_json=payload)
            response = self.post_as(self.admin, self.form(payload, [self.jpeg]))

        self.assertEqual(201, json_response.status_code)
        self.assertEqual(201, response.status_code)
        self.assertEqual(self.org2, self.last_broadcast().org)
        self.assertEqual([self.jpeg_attachment(self.org2)], response.json()["metadata"]["attachments"])

    def test_not_authenticated(self):
        # nobody authenticated: no authenticator is let in, whichever they are, so the user is anonymous
        with patch.object(ENDPOINT, "authentication_classes", []):
            json_response = self.client.post(self.url, json.dumps(self.payload()), content_type="application/json")
            response = self.client.post(self.url, self.form(files=[self.jpeg]))

        self.assertIn(json_response.status_code, (401, 403))
        self.assertEqual(json_response.status_code, response.status_code)
        self.save.assert_not_called()
        self.assertEqual(0, Broadcast.objects.count())
        self.assertEqual([], self.idempotency_keys())


class TestInternalWhatsappBroadcastMediaIdempotency(InlineMediaTestMixin, TembaTest):
    """
    US4: Idempotency-Key with files. The body hash covers the payload and the files, the lookup is before any upload,
    and every way out that isn't a success gives the key back.
    """

    def test_replay_returns_the_stored_response_without_storing(self):
        first = self.post_multipart(files=[self.jpeg], key="replay")
        self.assertEqual(201, first.status_code)
        self.save.assert_called_once()

        # as if the cache of files had expired, which is the only reason a second request could store it again
        for key in self.dedup_keys():
            self.redis.delete(key)

        second = self.post_multipart(files=[self.jpeg], key="replay")

        self.assertEqual(201, second.status_code)
        self.assertEqual(first.json(), second.json())
        self.save.assert_called_once()
        self.assertEqual(1, Broadcast.objects.count())

        cached = json.loads(self.redis.get(self.idempotency_redis_key("replay")))
        self.assertEqual("done", cached["state"])
        self.assertEqual(
            compute_media_body_hash(json.loads(self.form()["payload"]), [self.jpeg_sha256]), cached["body_hash"]
        )
        self.assertGreater(self.redis.ttl(self.idempotency_redis_key("replay")), 86000)

    def test_same_key_with_a_different_file_is_a_conflict(self):
        self.assertEqual(201, self.post_multipart(files=[self.jpeg], key="changed").status_code)
        self.save.reset_mock()

        response = self.post_multipart(files=[self.mp4], key="changed")

        self.assertEqual(409, response.status_code)
        self.assertEqual({"error": "Idempotency-Key reused with different body"}, response.json())
        self.save.assert_not_called()
        self.assertEqual(1, Broadcast.objects.count())

    def test_same_key_with_the_files_in_another_order_is_a_conflict(self):
        self.assertEqual(201, self.post_multipart(files=[self.jpeg, self.mp4], key="reordered").status_code)
        self.save.reset_mock()

        response = self.post_multipart(files=[self.mp4, self.jpeg], key="reordered")

        self.assertEqual(409, response.status_code)
        self.save.assert_not_called()
        self.assertEqual(1, Broadcast.objects.count())

    def test_same_key_with_a_different_payload_is_a_conflict(self):
        self.assertEqual(201, self.post_multipart(files=[self.jpeg], key="payload").status_code)
        self.save.reset_mock()

        response = self.post_multipart(self.payload(msg={"text": "Another"}), files=[self.jpeg], key="payload")

        self.assertEqual(409, response.status_code)
        self.save.assert_not_called()

    def test_the_order_of_the_keys_of_the_payload_does_not_matter(self):
        payload = self.payload()
        reordered = dict(reversed(list(payload.items())))
        self.assertNotEqual(list(payload), list(reordered))

        first = self.post_multipart(payload, files=[self.jpeg], key="key-order")
        second = self.post_multipart(reordered, files=[self.jpeg], key="key-order")

        self.assertEqual(201, second.status_code)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(1, Broadcast.objects.count())

    def test_request_in_flight_is_a_conflict(self):
        self.redis.set(
            self.idempotency_redis_key("in-flight"), json.dumps({"state": "inflight", "body_hash": "x"}), ex=60
        )

        response = self.post_multipart(files=[self.jpeg], key="in-flight")

        self.assertEqual(409, response.status_code)
        self.assertEqual({"error": "Request with this Idempotency-Key is already being processed"}, response.json())
        self.save.assert_not_called()
        self.assertEqual(0, Broadcast.objects.count())

        # which is still there, as it is not this request's
        self.assertIsNotNone(self.redis.get(self.idempotency_redis_key("in-flight")))

    def test_key_is_claimed_before_the_upload_and_released_after_a_failure(self):
        claimed = []

        def fail(*args):
            claimed.append(self.redis.get(self.idempotency_redis_key("outage")))
            raise ClientError({"Error": {"Code": "SlowDown", "Message": "x"}}, "PutObject")

        self.save.side_effect = fail

        response = self.post_multipart(files=[self.jpeg], key="outage")

        self.assertEqual(503, response.status_code)
        self.assertEqual({"error": MEDIA_STORAGE_UNAVAILABLE_MESSAGE}, response.json())

        # the key was there while the upload was tried, and is not any more
        self.assertEqual(1, len(claimed))
        self.assertEqual("inflight", json.loads(claimed[0])["state"])
        self.assertIsNone(self.redis.get(self.idempotency_redis_key("outage")))
        self.assertEqual(0, Broadcast.objects.count())

        # so the caller can retry with the same key once S3 is back
        self.save.side_effect = None
        retry = self.post_multipart(files=[self.jpeg], key="outage")

        self.assertEqual(201, retry.status_code)
        self.assertEqual(1, Broadcast.objects.count())

    def test_key_is_released_when_the_payload_does_not_validate(self):
        payload = {"project": str(self.org.proj_uuid), "msg": {"text": "no recipients"}}

        with patch(
            "temba.api.v2.internals.broadcasts.views.idempotency_release", wraps=idempotency_release
        ) as release:
            response = self.post_multipart(payload, files=[self.jpeg], key="invalid")

        self.assertEqual(400, response.status_code)
        self.assertEqual(
            {"payload": {"non_field_errors": ["Must provide either urns, contacts or groups"]}}, response.json()
        )
        release.assert_called_once_with(str(self.org.proj_uuid), "invalid")
        self.save.assert_not_called()

        # it was given back, so the same key can be used again, for another attempt that is also invalid, and then for
        # one that is not
        self.assertIsNone(self.redis.get(self.idempotency_redis_key("invalid")))
        self.assertEqual(400, self.post_multipart(payload, files=[self.jpeg], key="invalid").status_code)
        self.assertIsNone(self.redis.get(self.idempotency_redis_key("invalid")))
        self.assertEqual(201, self.post_multipart(files=[self.jpeg], key="invalid").status_code)

    def test_key_is_released_when_attachments_is_not_a_list(self):
        payload = self.payload(msg={"text": "Hi", "attachments": "image/png:https://example.com/a.png"})

        response = self.post_multipart(payload, files=[self.jpeg], key="not-a-list")

        self.assertEqual(400, response.status_code)
        self.assertEqual({"payload": {"msg": {"attachments": ["Expected a list of items."]}}}, response.json())
        self.assertIsNone(self.redis.get(self.idempotency_redis_key("not-a-list")))
        self.save.assert_not_called()

    def test_key_is_released_after_an_unexpected_error(self):
        with patch.object(WhatsappBroadcastWriteSerializer, "save", side_effect=RuntimeError("downstream")):
            with self.assertRaises(RuntimeError):
                self.post_multipart(files=[self.jpeg], key="unexpected")

        self.assertIsNone(self.redis.get(self.idempotency_redis_key("unexpected")))

    def test_json_and_multipart_do_not_share_a_hash(self):
        # a retry that changes how the same broadcast is sent is not a replay
        self.assertEqual(201, self.post_json(key="shape").status_code)

        response = self.post_multipart(key="shape")

        self.assertEqual(409, response.status_code)


class TestInternalWhatsappBroadcastMediaFailures(InlineMediaTestMixin, TembaTest):
    """
    US5: requests that are not valid, and outages of S3 and Redis, on the internal endpoint
    """

    def test_rejections_happen_before_a_key_is_claimed(self):
        no_recipients = {"project": str(self.org.proj_uuid), "msg": {"text": "Hi"}}

        def padded(data: bytes, size: int) -> bytes:
            return data + b"\x00" * (size - len(data))

        payload = json.dumps(self.payload())
        cases = [
            ("payload missing", {"files": [self.upload(self.jpeg)]}, {"payload": ["This field is required."]}, False),
            (
                "payload twice",
                {"payload": [payload, payload], "files": [self.upload(self.jpeg)]},
                {"payload": ["Only one payload field is accepted."]},
                False,
            ),
            (
                "payload not json",
                {"payload": "{not json", "files": [self.upload(self.jpeg)]},
                {"payload": ["Payload must be valid JSON."]},
                False,
            ),
            (
                "payload is an array",
                {"payload": json.dumps([self.payload()]), "files": [self.upload(self.jpeg)]},
                {"payload": ["Payload must be a JSON object."]},
                False,
            ),
            (
                "unknown field",
                {"payload": payload, "file": self.upload(self.jpeg)},
                {"payload": ["Unexpected field 'file'. Only 'payload' and 'files' are accepted."]},
                False,
            ),
            (
                "empty file",
                {"payload": payload, "files": [self.upload(b"")]},
                {"files": {"0": ["The submitted file is empty."]}},
                False,
            ),
            (
                "gif",
                {"payload": payload, "files": [self.upload(self.jpeg), self.upload(GIF_BYTES)]},
                {"files": {"1": ["Unsupported file type: image/gif."]}},
                False,
            ),
            (
                "html",
                {"payload": payload, "files": [self.upload(b"<!DOCTYPE html><html>hi</html>")]},
                {"files": {"0": ["Unsupported file type: text/html."]}},
                False,
            ),
            (
                "wav",
                {"payload": payload, "files": [self.upload(read_test_media("allo.wav"))]},
                {"files": {"0": ["Unsupported file type: audio/x-wav."]}},
                False,
            ),
            (
                "6 MB jpeg",
                {"payload": payload, "files": [self.upload(padded(self.jpeg, 6 * 1024 * 1024))]},
                {"files": {"0": ["File is too large for image/jpeg: the limit is 5 MiB."]}},
                False,
            ),
            (
                "17 MB mp4",
                {"payload": payload, "files": [self.upload(padded(self.mp4, 17 * 1024 * 1024))]},
                {"files": {"0": ["File is too large for video/mp4: the limit is 16 MiB."]}},
                False,
            ),
            (
                "11 files",
                {"payload": payload, "files": [self.upload(self.jpeg) for _ in range(11)]},
                {"files": {"10": ["At most 10 files can be sent."]}},
                False,
            ),
            # these are only found by the serializer, once the key is claimed, and give it back
            (
                "payload fails today's rules",
                {"payload": json.dumps(no_recipients), "files": [self.upload(self.jpeg)]},
                {"payload": {"non_field_errors": ["Must provide either urns, contacts or groups"]}},
                True,
            ),
            (
                "attachments is not a list",
                {
                    "payload": json.dumps(self.payload(msg={"attachments": "x"})),
                    "files": [self.upload(self.jpeg)],
                },
                {"payload": {"msg": {"attachments": ["Expected a list of items."]}}},
                True,
            ),
        ]

        for name, fields, expected, claimed in cases:
            with self.subTest(name):
                with patch(
                    "temba.api.v2.internals.broadcasts.views.idempotency_release", wraps=idempotency_release
                ) as release:
                    with patch(
                        "temba.api.v2.internals.broadcasts.views.idempotency_lookup", wraps=idempotency_lookup
                    ) as lookup:
                        response = self.post_form(fields, key="rejected")

                self.assertEqual(400, response.status_code, response.content)
                self.assertEqual(expected, response.json())
                self.save.assert_not_called()
                self.assertEqual(0, Broadcast.objects.count())
                self.assertEqual([], self.dedup_keys())
                self.assertEqual([], self.idempotency_keys())
                self.queue.assert_not_called()

                # a request that is rejected at the boundary never looks at the key, the others give it back
                self.assertEqual(1 if claimed else 0, lookup.call_count)
                self.assertEqual(1 if claimed else 0, release.call_count)

    def test_a_document_over_its_limit(self):
        pdf = b"%PDF-1.4\n" + b"\x00" * 2000

        small = AllowedMedia("document", "pdf", 2048)
        with patch.dict(ALLOWED_BROADCAST_MEDIA, {"application/pdf": small}):
            response = self.post_multipart(files=[pdf + b"\x00" * 100], key="document")

        self.assertEqual(400, response.status_code)
        self.assertEqual(
            {"files": {"0": ["File is too large for application/pdf: the limit is 2 KiB."]}}, response.json()
        )
        self.save.assert_not_called()
        self.assertEqual([], self.idempotency_keys())

    def test_files_over_the_total(self):
        with patch("temba.msgs.usecases.broadcast_media.MAX_BROADCAST_FILES_TOTAL_BYTES", 10 * 1024):
            response = self.post_multipart(files=[self.jpeg, self.jpeg], key="total")

        self.assertEqual(400, response.status_code)
        self.assertEqual({"files": {"1": ["The files add up to more than 10 KiB."]}}, response.json())
        self.save.assert_not_called()
        self.assertEqual([], self.idempotency_keys())

    def test_request_larger_than_any_valid_one(self):
        response = self.post_multipart(
            files=[self.jpeg], key="large", CONTENT_LENGTH=str(MAX_BROADCAST_MULTIPART_BYTES + 1)
        )

        self.assertEqual(400, response.status_code)
        self.assertEqual({"files": ["The request is too large."]}, response.json())
        self.assertEqual([], self.idempotency_keys())

    def assertMediaStorageUnavailable(self, response, events, stage: str, secrets: list[str], key: str):
        self.assertEqual(503, response.status_code)
        self.assertEqual({"error": MEDIA_STORAGE_UNAVAILABLE_MESSAGE}, response.json())
        self.assertNotIn(b"Traceback", response.content)
        self.assertEqual(0, Broadcast.objects.count())
        self.queue.assert_not_called()

        # the key is given back, so that the caller can retry with it
        self.assertIsNone(self.redis.get(self.idempotency_redis_key(key)))

        self.assertEqual(1, len(events))
        user = User.objects.get(email=self.user_email)
        tags = {k: str(v) for k, v in events[0]["tags"].items() if k != "media_cause"}
        self.assertEqual(
            {
                "org_id": str(self.org.id),
                "project_uuid": str(self.org.proj_uuid),
                "user_id": str(user.id),
                "correlation_id": "req-456",
                "media_stage": stage,
            },
            tags,
        )

        report = json.dumps(events[0])
        for secret in secrets:
            self.assertNotIn(secret, report)
        self.assertNotIn("amazonaws", report)
        self.assertNotIn("Hello", report)

    def secrets(self) -> list[str]:
        return [
            "secret-photo.jpg",
            self.jpeg_sha256,
            self.key(self.org, self.jpeg_sha256, "jpg"),
            self.jpeg_attachment(),
        ]

    def post_with_secrets(self, key: str):
        return self.post_multipart(
            files=[self.upload(self.jpeg, "secret-photo.jpg", "image/jpeg")], key=key, HTTP_X_REQUEST_ID="req-456"
        )

    def test_s3_failures(self):
        url = f"https://bucket.s3.amazonaws.com/{self.key(self.org, self.jpeg_sha256, 'jpg')}"
        errors = [
            ClientError({"Error": {"Code": "AccessDenied", "Message": f"no access to {url}"}}, "PutObject"),
            S3UploadFailedError(f"Failed to upload secret-photo.jpg to {url}"),
            ReadTimeoutError(endpoint_url=url),
            ConnectTimeoutError(endpoint_url=url),
            OSError(f"cannot write secret-photo.jpg {url}"),
        ]

        for error in errors:
            with self.subTest(type(error).__name__):
                self.save.reset_mock()
                self.save.side_effect = error

                with capture_sentry_events() as events:
                    response = self.post_with_secrets("s3-outage")

                self.assertMediaStorageUnavailable(response, events, "upload", self.secrets(), "s3-outage")
                self.save.assert_called_once()
                self.assertEqual([], self.dedup_keys())

        self.save.side_effect = None
        self.assertEqual(201, self.post_with_secrets("s3-outage").status_code)

    def test_redis_failures(self):
        url = f"https://bucket.s3.amazonaws.com/{self.key(self.org, self.jpeg_sha256, 'jpg')}"

        for command, stage, saves in (("get", "dedup_lookup", 0), ("set", "dedup_record", 1)):
            for error in (
                RedisConnectionError(f"Error connecting for secret-photo.jpg {url}"),
                RedisTimeoutError("Timeout reading from socket"),
            ):
                with self.subTest(f"{command} {type(error).__name__}"):
                    self.save.reset_mock()

                    with patch.object(_dedup_redis(), command, side_effect=error):
                        with capture_sentry_events() as events:
                            response = self.post_with_secrets("redis-outage")

                    self.assertMediaStorageUnavailable(response, events, stage, self.secrets(), "redis-outage")
                    self.assertEqual(saves, self.save.call_count)

    def test_failures_without_a_key(self):
        # no Idempotency-Key, so nothing to give back
        self.save.side_effect = OSError("disk")

        response = self.post_multipart(files=[self.jpeg])

        self.assertEqual(503, response.status_code)
        self.assertEqual({"error": MEDIA_STORAGE_UNAVAILABLE_MESSAGE}, response.json())
        self.assertEqual([], self.idempotency_keys())


class TestFastAPIBridgeUnchanged(TembaTest):
    """
    The FastAPI bridge takes JSON only and keeps the serializer that it has always had. Neither it nor its tests are
    part of this change.
    """

    def test_bridge_serializer_unchanged(self):
        from fastapi.params import Depends as FastAPIDepends

        from temba.fastapi_app import broadcasts as bridge
        from temba.fastapi_app.auth import verify_jwt

        # the endpoint is still behind the JWT check, and takes the JSON body as a dict
        parameters = inspect.signature(bridge.post_internal_whatsapp_broadcast).parameters
        self.assertIsInstance(parameters["jwt_payload"].default, FastAPIDepends)
        self.assertIs(verify_jwt, parameters["jwt_payload"].default.dependency)
        self.assertIs(dict, parameters["body"].annotation)

        # and builds the serializer of the JSON contract with the JSON body
        source = inspect.getsource(bridge)
        self.assertIs(WhatsappBroadcastWriteSerializer, bridge.WhatsappBroadcastWriteSerializer)
        self.assertIn("serializer = WhatsappBroadcastWriteSerializer(\n        data=body,", source)

        # it knows nothing of files
        for name in ("WhatsappBroadcastWithMediaWriteSerializer", "BroadcastMultiPartParser", "broadcast_media"):
            self.assertNotIn(name, source)
            self.assertFalse(hasattr(bridge, name))

        # the serializer it uses is the parent, which has not been given anything of files either
        self.assertNotIn("inline_media", inspect.getsource(WhatsappBroadcastWriteSerializer))
        self.assertTrue(
            issubclass(api_serializers.WhatsappBroadcastWithMediaWriteSerializer, WhatsappBroadcastWriteSerializer)
        )
        self.assertIsNot(WhatsappBroadcastWriteSerializer, api_serializers.WhatsappBroadcastWithMediaWriteSerializer)
