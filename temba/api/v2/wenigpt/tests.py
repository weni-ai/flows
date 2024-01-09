from unittest.mock import MagicMock, patch

from django.urls import reverse

from temba.tests.base import TembaTest


class TestIntelligencesEndpoint(TembaTest):
    @patch("temba.api.v2.wenigpt.views.requests.get")
    def test_get_intelligences(self, mock_requests_get):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "intelligence_name": "name",
                "content_bases": [
                    {"uuid": "123", "content_base_name": "1234"},
                    {"uuid": "456", "content_base_name": "4321"},
                ],
            },
            {
                "intelligence_name": "name 2",
                "content_bases": [
                    {"uuid": "789", "content_base_name": "12345"},
                    {"uuid": "012", "content_base_name": "43215"},
                ],
            },
        ]
        mock_requests_get.return_value = mock_response

        url = reverse("api.v2.intelligences") + ".json"

        self.client.force_login(self.user)

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        expected_data = [
            {
                "intelligence_name": "name",
                "content_bases": [
                    {"uuid": "123", "content_base_name": "1234"},
                    {"uuid": "456", "content_base_name": "4321"},
                ],
            },
            {
                "intelligence_name": "name 2",
                "content_bases": [
                    {"uuid": "789", "content_base_name": "12345"},
                    {"uuid": "012", "content_base_name": "43215"},
                ],
            },
        ]
        self.assertEqual(response.data, expected_data)
