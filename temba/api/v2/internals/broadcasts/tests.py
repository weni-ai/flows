import uuid
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

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

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"message": "Success"})

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
