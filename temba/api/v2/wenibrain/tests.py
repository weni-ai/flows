from unittest.mock import MagicMock, patch

from django.urls import reverse

from temba.tests.base import TembaTest


class TestBrainInfoEndpoint(TembaTest):
    @patch("temba.api.v2.wenibrain.views.requests.get")
    def test_get_brain_info(self, mock_requests_get):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "agent": {
                    "name": "Bob",
                    "role": "Auxiliar de vendas",
                    "personality": "Organizado",
                    "goal": "Realizar atendimento ao cliente"
                },
                "instructions": []
            }
        ]

        mock_requests_get.return_value = mock_response
        mock_requests_get.return_value.status_code = 200

        url = reverse("api.v2.brain_info") + ".json"

        self.client.force_login(self.user)

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        expected_data = { "name": "Bob", "occupation": "Auxiliar de vendas" }

        self.assertEqual(response.json(), expected_data)

    @patch("temba.api.v2.wenigpt.views.requests.get")
    def test_get_intelligences_error(self, mock_requests_get):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "agent": {
                    "name": "Bob",
                    "role": "Auxiliar de vendas",
                    "personality": "Organizado",
                    "goal": "Realizar atendimento ao cliente"
                },
                "instructions": []
            },
        ]

        mock_requests_get.return_value = mock_response
        mock_requests_get.return_value.status_code = 500

        url = reverse("api.v2.brain_info") + ".json"

        self.client.force_login(self.user)

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        expected_data = { "name": "", "occupation": ""}

        self.assertEqual(response.json(), expected_data)

    @patch("temba.api.v2.wenigpt.views.requests.get")
    def test_get_intelligences_missing_agent_data(self, mock_requests_get):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "agent": {},
                "instructions": []
            },
        ]

        mock_requests_get.return_value = mock_response
        mock_requests_get.return_value.status_code = 200

        url = reverse("api.v2.brain_info") + ".json"

        self.client.force_login(self.user)

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        expected_data = { "name": "", "occupation": ""}

        self.assertEqual(response.json(), expected_data)
