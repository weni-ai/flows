from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import override_settings

from temba.channels.clients.integrations import STATUS_ERROR, STATUS_SUCCESS, IntegrationsInternalClient
from temba.tests.base import TembaTest


class IntegrationsInternalClientTest(TembaTest):
    def setUp(self):
        super().setUp()

        self.authenticator = type("Auth", (), {"headers": {"Authorization": "Bearer abc"}})()
        self.event_id = uuid4()
        self.url = f"https://integrations.example/internals/app-migrations/{self.event_id}/status"

    def _client(self, base_url="https://integrations.example"):
        return IntegrationsInternalClient(base_url=base_url, authenticator=self.authenticator)

    def test_report_success_status(self):
        client = self._client()
        with patch.object(client, "get_url", return_value=self.url) as mock_get_url:
            with patch("temba.channels.clients.integrations.requests.post") as mock_post:
                client.report_app_migration_status(self.event_id, STATUS_SUCCESS)

        mock_get_url.assert_called_once_with(f"/internals/app-migrations/{self.event_id}/status")
        mock_post.assert_called_once_with(
            self.url,
            headers=self.authenticator.headers,
            json={"module": "flows", "status": STATUS_SUCCESS},
            timeout=10,
        )
        mock_post.return_value.raise_for_status.assert_called_once()

    def test_report_error_status_includes_error(self):
        client = self._client()
        with patch.object(client, "get_url", return_value=self.url):
            with patch("temba.channels.clients.integrations.requests.post") as mock_post:
                client.report_app_migration_status(self.event_id, STATUS_ERROR, error="boom")

        self.assertEqual(
            mock_post.call_args.kwargs["json"],
            {"module": "flows", "status": STATUS_ERROR, "error": "boom"},
        )

    def test_report_raises_on_http_error(self):
        client = self._client()
        response = MagicMock()
        response.raise_for_status.side_effect = Exception("500")
        with patch.object(client, "get_url", return_value=self.url):
            with patch("temba.channels.clients.integrations.requests.post", return_value=response):
                with self.assertRaises(Exception):
                    client.report_app_migration_status(self.event_id, STATUS_SUCCESS)

    @override_settings(INTEGRATIONS_BASE_URL="https://from-settings.example")
    def test_base_url_falls_back_to_settings(self):
        client = IntegrationsInternalClient(authenticator=self.authenticator)

        self.assertEqual(client.base_url, "https://from-settings.example")

    @override_settings(INTEGRATIONS_BASE_URL="", CONNECT_BASE_URL="https://connect.example")
    def test_skips_report_when_base_url_not_configured(self):
        client = IntegrationsInternalClient(authenticator=self.authenticator)

        self.assertEqual(client.base_url, "")
        with patch("temba.channels.clients.integrations.requests.post") as mock_post:
            with self.assertLogs("temba.channels.clients.integrations", level="WARNING"):
                client.report_app_migration_status(self.event_id, STATUS_SUCCESS)

        mock_post.assert_not_called()
