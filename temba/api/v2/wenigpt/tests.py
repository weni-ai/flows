from unittest.mock import MagicMock, patch

from django.urls import reverse

from temba.tests.base import TembaTest


class TestIntelligencesEndpoint(TembaTest):
    @patch("temba.api.v2.wenigpt.views.requests.get")
    def test_get_intelligences(self, mock_requests_get):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "intelligence_name": "Test Intelligence 0",
                "content_bases": [
                    {"uuid": "123456", "content_base_name": "Test Content Base 0"},
                    {"uuid": "654321", "content_base_name": "Test Content Base 1"},
                ],
            },
        ]

        mock_requests_get.return_value = mock_response

        url = reverse("api.v2.intelligences") + ".json"

        self.client.force_login(self.user)

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        expected_data = {
            "results": [
                {"id": "123456", "name": "Test Content Base 0", "intelligence": "Test Intelligence 0"},
                {"id": "654321", "name": "Test Content Base 1", "intelligence": "Test Intelligence 0"},
            ]
        }

        self.assertEqual(response.json(), expected_data)
