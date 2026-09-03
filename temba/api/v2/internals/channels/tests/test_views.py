import uuid
from unittest.mock import patch

from weni.internal.models import Project

from django.test import override_settings

from temba.api.v2.internals.views import JWTAuthMockMixin
from temba.api.weni_jwt_test_utils import WeniJWTTestMixin
from temba.tests import TembaTest


class ChannelProjectViewTest(TembaTest):
    def test_request_without_token(self):
        url = "/api/v2/internals/channel_projects"
        response = self.client.post(url)

        self.assertEqual(response.status_code, 403)

    def test_request_with_invalid_token(self):
        url = "/api/v2/internals/channel_projects?token=invalidtoken"
        response = self.client.post(url)

        self.assertEqual(response.status_code, 403)

    def test_request_without_body(self):
        with override_settings(BILLING_FIXED_ACCESS_TOKEN="12345"):
            url = "/api/v2/internals/channel_projects?token=12345"
            response = self.client.post(url)

            self.assertEqual(response.status_code, 400)

    def test_get_channel_projects(self):
        with override_settings(BILLING_FIXED_ACCESS_TOKEN="12345"):

            project = Project.objects.create(name="Test project", created_by=self.user, modified_by=self.user)
            channel = self.create_channel("TG", "Test Channel", "test", org=project.org)
            channel_wac = self.create_channel("WAC", "Test WAC Channel", "74123456789", org=project.org)
            channel_wac.config = {
                "wa_waba_id": "12345678910",
                "wa_number": "+55 00 900001234",
            }
            channel_wac.save()

            url = "/api/v2/internals/channel_projects?token=12345"
            response = self.client.post(
                url,
                data={"channels": [str(channel.uuid), str(channel_wac.uuid)]},
                content_type="application/json",
            )
            data = response.json()

            self.assertEqual(response.status_code, 200)
            self.assertTrue("results" in data)
            self.assertEqual(len(data.get("results")), 2)

            result_wac = data.get("results")[0]
            result = data.get("results")[1]

            self.assertEqual(result.get("channel_uuid"), str(channel.uuid))
            self.assertEqual(result.get("project_uuid"), str(project.project_uuid))

            self.assertEqual(result_wac.get("channel_uuid"), str(channel_wac.uuid))
            self.assertEqual(result_wac.get("waba"), str(channel_wac.config.get("wa_waba_id")))
            self.assertEqual(result_wac.get("phone_number"), str(channel_wac.config.get("wa_number")))
            self.assertEqual(result_wac.get("project_uuid"), str(project.project_uuid))


class PatchedJWTAuthMixin(JWTAuthMockMixin):
    jwt_patch_target = "temba.api.auth.jwt.RequiredJWTAuthentication.authenticate"

    def _mock_jwt_authenticate(self, request, *args, **kwargs):
        result = super()._mock_jwt_authenticate(request, *args, **kwargs)
        payload = request.jwt_payload
        if getattr(self.org, "proj_uuid", None) and not payload.get("project_uuid"):
            payload["project_uuid"] = str(self.org.proj_uuid)
        if getattr(self, "jwt_payload_patch", None):
            payload.update(self.jwt_payload_patch)
        return result


class ChannelAllowedDomainsViewTest(PatchedJWTAuthMixin, TembaTest):
    def setUp(self):
        super().setUp()
        self.url = "/api/v2/internals/channel_allowed_domains"
        self.jwt_payload_patch = {}

    def _set_jwt_payload(self, **kwargs):
        self.jwt_payload_patch = kwargs

    def test_request_without_channel_uuid(self):
        self._set_jwt_payload(channel_uuid=None)
        response = self.client.get(self.url, **self.auth_headers)

        self.assertEqual(response.status_code, 400)

    def test_request_with_channel_uuid(self):
        wchan = self.create_channel(
            "WWC",
            "WEBCHAT TEST CHANNEL",
            "wwctest",
            config={"allowed_domains": ["dash.weni.ai", "flows.weni.ai"]},
        )

        self._set_jwt_payload(channel_uuid=str(wchan.uuid))
        response = self.client.get(self.url, **self.auth_headers)

        data = response.json()

        self.assertEqual(len(data), 2)
        self.assertEqual(data[0], "dash.weni.ai")

    def test_request_with_channel_uuid_with_no_allowed_domains(self):
        wchan = self.create_channel(
            "WWC",
            "WEBCHAT TEST CHANNEL2",
            "wwctest2",
        )

        self._set_jwt_payload(channel_uuid=str(wchan.uuid))
        response = self.client.get(self.url, **self.auth_headers)

        data = response.json()

        self.assertEqual(len(data), 0)

    def test_request_with_channel_uuid_notfound(self):
        self._set_jwt_payload(channel_uuid=str(uuid.uuid4()))
        response = self.client.get(self.url, **self.auth_headers)
        self.assertEqual(response.status_code, 404)


class ChannelElevenLabsApiKeyViewTest(PatchedJWTAuthMixin, TembaTest):
    def setUp(self):
        super().setUp()
        self.url = "/api/v2/internals/elevenlabs_api_key"
        self.jwt_payload_patch = {}

    def _set_jwt_payload(self, **kwargs):
        self.jwt_payload_patch = kwargs

    def test_request_without_channel_uuid(self):
        self._set_jwt_payload(channel_uuid=None)
        response = self.client.get(self.url, **self.auth_headers)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"channel_uuid": ["This field may not be null."]})

    def test_request_with_nonexistent_channel_uuid(self):
        self._set_jwt_payload(channel_uuid=str(uuid.uuid4()))
        response = self.client.get(self.url, **self.auth_headers)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Channel not found"})

    def test_request_channel_without_voice_mode_config(self):
        channel = self.create_channel("TG", "Test Channel", "test")

        self._set_jwt_payload(channel_uuid=str(channel.uuid))
        response = self.client.get(self.url, **self.auth_headers)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "ElevenLabs API key not found"})

    def test_request_channel_with_partial_voice_mode_config(self):
        channel = self.create_channel("TG", "Test Channel", "test", config={"voice_mode": {"otherProvider": {}}})

        self._set_jwt_payload(channel_uuid=str(channel.uuid))
        response = self.client.get(self.url, **self.auth_headers)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "ElevenLabs API key not found"})

    def test_request_channel_with_elevenlabs_but_no_api_key(self):
        channel = self.create_channel("TG", "Test Channel", "test", config={"voice_mode": {"elevenLabs": {}}})

        self._set_jwt_payload(channel_uuid=str(channel.uuid))
        response = self.client.get(self.url, **self.auth_headers)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "ElevenLabs API key not found"})

    def test_request_channel_with_valid_elevenlabs_api_key(self):
        channel = self.create_channel(
            "TG",
            "Test Channel",
            "test",
            config={"voice_mode": {"elevenLabs": {"apiKey": "sk-test-key-123"}}},
        )

        self._set_jwt_payload(channel_uuid=str(channel.uuid))
        response = self.client.get(self.url, **self.auth_headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"api_key": "sk-test-key-123"})


class ChannelMarketingTagsViewTest(PatchedJWTAuthMixin, TembaTest):
    def setUp(self):
        super().setUp()
        self.url = "/api/v2/internals/channel_marketing_tags"
        self.jwt_payload_patch = {}

    def _set_jwt_payload(self, **kwargs):
        self.jwt_payload_patch = kwargs

    def test_request_without_channel_uuid(self):
        self._set_jwt_payload(channel_uuid=None)
        response = self.client.get(self.url, **self.auth_headers)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"channel_uuid": ["This field may not be null."]})

    def test_request_with_nonexistent_channel_uuid(self):
        self._set_jwt_payload(channel_uuid=str(uuid.uuid4()))
        response = self.client.get(self.url, **self.auth_headers)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Channel not found"})

    def test_request_returns_false_when_config_missing(self):
        channel = self.create_channel("WWC", "Test Channel", "test")

        self._set_jwt_payload(channel_uuid=str(channel.uuid))
        response = self.client.get(self.url, **self.auth_headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"marketing_tags": False})

    def test_request_returns_true_when_config_enabled(self):
        channel = self.create_channel("WWC", "Test Channel", "test", config={"marketing_tags": True})

        self._set_jwt_payload(channel_uuid=str(channel.uuid))
        response = self.client.get(self.url, **self.auth_headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"marketing_tags": True})


class InternalChannelViewTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.url = "/api/v2/internals/channels-by-project"

    @patch("temba.api.v2.internals.channels.views.InternalChannelView.authentication_classes", [])
    @patch("temba.api.v2.internals.channels.views.InternalChannelView.permission_classes", [])
    def test_missing_project_uuid(self):
        from temba.channels.models import Channel

        Channel.objects.all().delete()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "project_uuid is required"})

    @patch("temba.api.v2.internals.channels.views.InternalChannelView.authentication_classes", [])
    @patch("temba.api.v2.internals.channels.views.InternalChannelView.permission_classes", [])
    def test_project_not_found(self):
        from temba.channels.models import Channel

        Channel.objects.all().delete()
        response = self.client.get(f"{self.url}?project_uuid=00000000-0000-0000-0000-000000000000")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"error": "Project not found"})

    @patch("temba.api.v2.internals.channels.views.InternalChannelView.authentication_classes", [])
    @patch("temba.api.v2.internals.channels.views.InternalChannelView.permission_classes", [])
    def test_no_active_channels(self):
        from temba.channels.models import Channel

        Channel.objects.all().delete()
        response = self.client.get(f"{self.url}?project_uuid={self.org.proj_uuid}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"results": []})

    @patch("temba.api.v2.internals.channels.views.InternalChannelView.authentication_classes", [])
    @patch("temba.api.v2.internals.channels.views.InternalChannelView.permission_classes", [])
    def test_active_channels(self):
        from temba.channels.models import Channel

        Channel.objects.all().delete()
        channel = self.create_channel("TG", "Test Channel", "test", org=self.org)
        channel.is_active = True
        channel.save()
        channel_wac = self.create_channel(
            "WAC",
            "Test WAC Channel",
            "74123456789",
            org=self.org,
            config={"wa_waba_id": "12345678910", "wa_number": "+55 00 900001234", "mmlite": True},
        )
        channel_wac.is_active = True
        channel_wac.save()
        response = self.client.get(f"{self.url}?project_uuid={self.org.proj_uuid}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("results", data)
        self.assertEqual(len(data["results"]), 2)

        normal = next(c for c in data["results"] if c["uuid"] == str(channel.uuid))
        self.assertEqual(normal["channel_type"], "TG")
        self.assertEqual(normal["name"], "Test Channel")
        self.assertTrue(normal["is_active"])
        self.assertIsNone(normal["waba"])
        self.assertIsNone(normal["phone_number"])
        self.assertFalse(normal["config"]["is_demo"])
        self.assertNotIn("MMLite", normal)
        wac = next(c for c in data["results"] if c["uuid"] == str(channel_wac.uuid))
        self.assertEqual(wac["channel_type"], "WAC")
        self.assertEqual(wac["name"], "Test WAC Channel")
        self.assertEqual(wac["waba"], "12345678910")
        self.assertEqual(wac["phone_number"], "+55 00 900001234")
        self.assertTrue(wac["MMLite"])
        self.assertTrue(wac["is_active"])
        self.assertEqual(wac["config"]["wa_waba_id"], "12345678910")
        self.assertEqual(wac["config"]["wa_number"], "+55 00 900001234")
        self.assertFalse(wac["config"]["is_demo"])


@override_settings(
    OIDC_OP_TOKEN_ENDPOINT="https://example.com/token",
    OIDC_OP_USER_ENDPOINT="https://example.com/user",
    OIDC_RP_CLIENT_ID="test-client-id",
    OIDC_RP_CLIENT_SECRET="test-client-secret",
)
class InternalChannelViewJWTTest(WeniJWTTestMixin, TembaTest):
    def setUp(self):
        super().setUp()
        self.url = "/api/v2/internals/channels-by-project"

    def test_request_without_token(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_request_with_invalid_token(self):
        response = self.client.get(self.url, HTTP_X_WENI_AUTH="invalidtoken")
        self.assertEqual(response.status_code, 401)

    def test_request_without_internal_claim(self):
        project = Project.objects.create(name="Test project", created_by=self.user, modified_by=self.user)
        token = self.sign_internal_jwt(
            project_uuid=str(project.project_uuid),
            can_communicate_internally=False,
        )
        response = self.client.get(
            f"{self.url}?project_uuid={project.project_uuid}",
            HTTP_X_WENI_AUTH=token,
        )
        self.assertEqual(response.status_code, 403)

    def test_jwt_ignores_query_project_uuid(self):
        project = Project.objects.create(name="Test project", created_by=self.user, modified_by=self.user)
        other_project = Project.objects.create(name="Other project", created_by=self.user, modified_by=self.user)
        active = self.create_channel("TG", "Active Channel", "active", org=project.org)

        response = self.client.get(
            f"{self.url}?project_uuid={other_project.project_uuid}",
            **self.jwt_headers(project_uuid=str(project.project_uuid)),
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        uuids = {entry["uuid"] for entry in data["results"]}
        self.assertIn(str(active.uuid), uuids)

    def test_returns_active_channels_for_project(self):
        project = Project.objects.create(name="Test project", created_by=self.user, modified_by=self.user)
        active = self.create_channel("TG", "Active Channel", "active", org=project.org)
        wac = self.create_channel("WAC", "WAC Channel", "74123456789", org=project.org)
        wac.config = {
            "wa_waba_id": "waba-1",
            "wa_number": "+5500900001234",
            "is_demo": True,
        }
        wac.save()
        inactive = self.create_channel("TG", "Inactive Channel", "inactive", org=project.org)
        inactive.is_active = False
        inactive.save()

        response = self.client.get(self.url, **self.jwt_headers(project_uuid=str(project.project_uuid)))
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("results", data)
        uuids = {entry["uuid"] for entry in data["results"]}
        self.assertIn(str(active.uuid), uuids)
        self.assertIn(str(wac.uuid), uuids)
        self.assertNotIn(str(inactive.uuid), uuids)

        wac_entry = next(entry for entry in data["results"] if entry["uuid"] == str(wac.uuid))
        self.assertEqual(wac_entry["channel_type"], "WAC")
        self.assertEqual(wac_entry["waba"], "waba-1")
        self.assertEqual(wac_entry["phone_number"], "+5500900001234")
        self.assertTrue(wac_entry["config"]["is_demo"])


class ChannelWabaMigrationViewTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.url = "/api/v2/internals/channel_waba_migration"

    @patch("temba.api.v2.internals.channels.views.ChannelWabaMigrationView.authentication_classes", [])
    def test_request_without_auth(self):
        response = self.client.post(self.url, data={}, content_type="application/json")
        self.assertEqual(response.status_code, 403)

    @patch("temba.api.v2.internals.channels.views.ChannelWabaMigrationView.authentication_classes", [])
    @patch("temba.api.v2.internals.channels.views.ChannelWabaMigrationView.permission_classes", [])
    def test_request_without_body(self):
        response = self.client.post(self.url, data={}, content_type="application/json")
        self.assertEqual(response.status_code, 400)

    @patch("temba.api.v2.internals.channels.views.ChannelWabaMigrationView.authentication_classes", [])
    @patch("temba.api.v2.internals.channels.views.ChannelWabaMigrationView.permission_classes", [])
    def test_request_with_nonexistent_waba(self):
        response = self.client.post(
            self.url,
            data={"old_waba_id": "old-waba", "new_waba_id": "new-waba"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "No WhatsApp Cloud channel found for the provided WABA"})

    @patch("temba.api.v2.internals.channels.views.ChannelWabaMigrationView.authentication_classes", [])
    @patch("temba.api.v2.internals.channels.views.ChannelWabaMigrationView.permission_classes", [])
    @patch("temba.channels.types.whatsapp_cloud.usecases.UpdateWhatsAppCloudWabaUseCase.execute")
    def test_migrates_matching_channels(self, mock_execute):
        channel = self.create_channel(
            "WAC",
            "WAC Channel",
            "74123456789",
            config={"wa_waba_id": "old-waba", "wa_currency": "USD", "wa_business_id": "business-1"},
        )
        mock_execute.return_value = [
            {
                "channel_uuid": str(channel.uuid),
                "after": {"wa_waba_id": "new-waba", "wa_previous_waba_id": "old-waba"},
            }
        ]

        response = self.client.post(
            self.url,
            data={"old_waba_id": "old-waba", "new_waba_id": "new-waba"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        mock_execute.assert_called_once_with(old_waba_id="old-waba", new_waba_id="new-waba")
        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["after"]["wa_waba_id"], "new-waba")

    @patch("temba.api.v2.internals.channels.views.ChannelWabaMigrationView.authentication_classes", [])
    @patch("temba.api.v2.internals.channels.views.ChannelWabaMigrationView.permission_classes", [])
    @patch("temba.channels.types.whatsapp_cloud.usecases.UpdateWhatsAppCloudWabaUseCase.execute")
    def test_migrates_all_channels_with_same_waba(self, mock_execute):
        mock_execute.return_value = [{"channel_uuid": "a"}, {"channel_uuid": "b"}]

        response = self.client.post(
            self.url,
            data={"old_waba_id": "old-waba", "new_waba_id": "new-waba"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 2)
