import datetime as dt
import uuid
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from temba.api.auth.jwt import OptionalJWTAuthentication
from temba.flows.models import Flow
from temba.msgs.models import Broadcast, BroadcastStatistics
from temba.tests.base import TembaTest

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
    def test_trigger_flow_uuid_only_for_template_batch(self):
        mock_user = MagicMock(spec=User)
        mock_user.is_authenticated = True
        mock_user.email = "mockuser@example.com"

        with patch("rest_framework.request.Request.user", mock_user):
            url = "/api/v2/internals/whatsapp_broadcasts"
            body = {
                "project": self.org.proj_uuid,
                "queue": "wpp_broadcast_batch",
                "trigger_flow_uuid": str(uuid.uuid4()),
                "msg": {"text": "hello"},
                "urns": ["whatsapp:5561912345678"],
            }
            response = self.client.post(url, data=body, content_type="application/json")
            self.assertEqual(response.status_code, 400)
            self.assertIn(
                "trigger_flow_uuid is only allowed when queue is template_batch",
                response.json()["non_field_errors"][0],
            )

    @patch(
        "temba.mailroom.client.MailroomClient.flow_inspect",
        return_value={"results": [], "dependencies": [], "waiting_exits": [], "parent_refs": [], "issues": []},
    )
    @patch("temba.mailroom.client.MailroomClient.flow_migrate", side_effect=lambda flow, to_version=None: flow)
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_trigger_flow_uuid_not_found_and_wrong_type(self, mock_flow_migrate, mock_flow_inspect):
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

    @patch(
        "temba.mailroom.client.MailroomClient.flow_inspect",
        return_value={"results": [], "dependencies": [], "waiting_exits": [], "parent_refs": [], "issues": []},
    )
    @patch("temba.mailroom.client.MailroomClient.flow_migrate", side_effect=lambda flow, to_version=None: flow)
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.authentication_classes", [])
    @patch("temba.api.v2.internals.broadcasts.views.InternalWhatsappBroadcastsEndpoint.permission_classes", [])
    def test_trigger_flow_uuid_success(self, mock_flow_migrate, mock_flow_inspect):
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
            "temba.api.v2.internals.broadcasts.services.public_file_storage.save",
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
            "temba.api.v2.internals.broadcasts.services.public_file_storage.save",
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
            "temba.api.v2.internals.broadcasts.services.public_file_storage.save"
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
            "temba.api.v2.internals.broadcasts.services.public_file_storage.save"
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
