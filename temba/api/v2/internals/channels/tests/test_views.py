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
            channel_wac.config = {"wa_waba_id": "12345678910", "wa_number": "+55 00 900001234"}
            channel_wac.save()

            url = "/api/v2/internals/channel_projects?token=12345"
            response = self.client.post(
                url, data={"channels": [str(channel.uuid), str(channel_wac.uuid)]}, content_type="application/json"
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
