from unittest.mock import patch

from weni.internal.models import Project

from django.test import override_settings

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


class ChannelAllowedDomainsViewTest(TembaTest):
    def test_request_without_channel_uuid(self):
        url = "/api/v2/internals/channel_allowed_domains"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 400)

    def test_request_with_channel_uuid(self):
        wchan = self.create_channel(
            "WWC",
            "WEBCHAT TEST CHANNEL",
            "wwctest",
            config={"allowed_domains": ["dash.weni.ai", "flows.weni.ai"]},
        )

        url = f"/api/v2/internals/channel_allowed_domains?channel={wchan.uuid}"

        response = self.client.get(url)

        data = response.json()

        self.assertEqual(len(data), 2)
        self.assertEqual(data[0], "dash.weni.ai")

    def test_request_with_channel_uuid_with_no_allowed_domains(self):
        wchan = self.create_channel(
            "WWC",
            "WEBCHAT TEST CHANNEL2",
            "wwctest2",
        )

        url = f"/api/v2/internals/channel_allowed_domains?channel={wchan.uuid}"

        response = self.client.get(url)

        data = response.json()

        self.assertEqual(len(data), 0)

    def test_request_with_channel_uuid_notfound(self):
        url = "/api/v2/internals/channel_allowed_domains?channel=2337712f-dcbc-48f3-9ae7-7f832445f6c9"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


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
        wac = next(c for c in data["results"] if c["uuid"] == str(channel_wac.uuid))
        self.assertEqual(wac["channel_type"], "WAC")
        self.assertEqual(wac["name"], "Test WAC Channel")
        self.assertEqual(wac["waba"], "12345678910")
        self.assertEqual(wac["phone_number"], "+55 00 900001234")
        self.assertTrue(wac["MMLite"])


class LanguageByChannelViewTest(TembaTest):
    url = "/api/v2/internals/language_by_channel"

    def test_request_without_channel_uuid(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)

    def test_request_with_channel_uuid(self):
        channel = self.create_channel("TG", "Test Channel", "test", org=self.org)
        response = self.client.get(f"{self.url}?channel={channel.uuid}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"language": self.org.language})

    def test_request_with_channel_uuid_notfound(self):
        url = f"{self.url}?channel=2337712f-dcbc-48f3-9ae7-7f832445f6c9"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
