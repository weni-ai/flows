import unittest
from unittest.mock import Mock, patch

import requests

from django.conf import settings
from django.utils import timezone

from temba.wpp_flows.tasks import (
    _get_token,
    extract_data_keys,
    get_assets_data,
    get_whatsapp_flows,
    refresh_whatsapp_flows,
    refresh_whatsapp_flows_for_a_channel,
    update_whatsapp_flows,
)


class RefreshWhatsappFlowsTest(unittest.TestCase):
    @patch("temba.wpp_flows.tasks.get_redis_connection")
    @patch("temba.wpp_flows.tasks.Channel.objects.filter")
    @patch("temba.wpp_flows.tasks.get_whatsapp_flows")
    @patch("temba.wpp_flows.tasks.update_whatsapp_flows")
    def test_refresh_whatsapp_flows(
        self, mock_update_whatsapp_flows, mock_get_whatsapp_flows, mock_channel_filter, mock_get_redis_connection
    ):
        mock_redis = Mock()
        mock_get_redis_connection.return_value = mock_redis
        mock_redis.get.return_value = None

        mock_lock = Mock()
        mock_redis.lock.return_value = mock_lock
        mock_lock.__enter__ = Mock(return_value=True)
        mock_lock.__exit__ = Mock(return_value=False)

        mock_channel = Mock()
        mock_channel.config.get.return_value = "test_waba_id"
        mock_channel_filter.return_value = [mock_channel]
        mock_get_whatsapp_flows.return_value = ["flow1"]

        refresh_whatsapp_flows()

        mock_get_redis_connection.assert_called_once()
        mock_redis.lock.assert_called_once_with("refresh_whatsapp_flows", 1800)
        mock_channel_filter.assert_called_once_with(is_active=True, channel_type__in=["WA", "WAC"])
        mock_get_whatsapp_flows.assert_called_once_with(mock_channel)
        mock_update_whatsapp_flows.assert_called_once_with(["flow1"], mock_channel)

        refresh_whatsapp_flows_for_a_channel(mock_channel)

    @patch("requests.get")
    @patch("temba.wpp_flows.tasks.HTTPLog.create_from_response")
    @patch("temba.wpp_flows.tasks.HTTPLog.create_from_exception")
    @patch("temba.wpp_flows.tasks._get_token")
    def test_get_whatsapp_flows(
        self, mock_get_token, mock_create_from_exception, mock_create_from_response, mock_requests_get
    ):
        mock_channel = Mock()
        mock_channel.config.get.return_value = "test_waba_id"
        mock_get_token.return_value = "test_token"
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [], "paging": {"next": None}}
        mock_requests_get.return_value = mock_response

        result = get_whatsapp_flows(mock_channel)

        self.assertEqual(result, [])
        mock_get_token.assert_called_once_with(mock_channel)
        mock_requests_get.assert_called_once_with(
            f"{settings.WHATSAPP_API_URL}/test_waba_id/flows",
            params=dict(limit=255),
            headers={"Authorization": "Bearer test_token"},
        )
        mock_create_from_response.assert_called_once()
        mock_create_from_exception.assert_not_called()

        # Test exception handling
        mock_requests_get.side_effect = requests.RequestException("Error")
        result = get_whatsapp_flows(mock_channel)
        self.assertEqual(result, [])
        mock_create_from_exception.assert_called_once()

    @patch("temba.wpp_flows.tasks.timezone.now")
    @patch("temba.wpp_flows.tasks.WhatsappFlow.objects.filter")
    def test_update_whatsapp_flows(self, mock_filter, mock_timezone_now):
        mock_channel = Mock()
        mock_channel.org = Mock()
        mock_flow = Mock()
        mock_timezone_now.return_value = timezone.now()

        flows = [
            {"id": "flow1", "categories": ["cat1"], "status": "active", "name": "Flow 1", "validation_errors": []}
        ]

        mock_query = Mock()
        mock_query.first.return_value = mock_flow
        mock_filter.return_value = mock_query

        update_whatsapp_flows(flows, mock_channel)
        mock_flow.save.assert_called_once()
        self.assertEqual(mock_flow.category, ["cat1"])
        self.assertEqual(mock_flow.status, "active")
        self.assertEqual(mock_flow.name, "Flow 1")
        self.assertEqual(mock_flow.validation_errors, [])
        self.assertEqual(mock_flow.modified_on, mock_timezone_now.return_value)

        mock_query.first.return_value = None
        with patch("temba.wpp_flows.tasks.WhatsappFlow.objects.create") as mock_create:
            update_whatsapp_flows(flows, mock_channel)
            mock_create.assert_called_once_with(
                facebook_flow_id="flow1",
                category=["cat1"],
                status="active",
                name="Flow 1",
                validation_errors=[],
                screens={},
                variables={"screens": [], "variables": []},
                org=mock_channel.org,
                channel=mock_channel,
                is_active=True,
            )

    @patch("temba.wpp_flows.tasks.settings.WHATSAPP_ADMIN_SYSTEM_USER_TOKEN", "admin_token")
    def test_get_token(self):
        mock_channel = Mock()

        # Test when wa_user_token is present in the channel config
        mock_channel.config.get.return_value = "user_token"
        token = _get_token(mock_channel)
        self.assertEqual(token, "user_token")

        # Test when wa_user_token is not present in the channel config
        mock_channel.config.get.return_value = None
        token = _get_token(mock_channel)
        self.assertEqual(token, "admin_token")


class GetAssetsDataTest(unittest.TestCase):
    @patch("temba.wpp_flows.tasks.requests.get")
    @patch("temba.wpp_flows.tasks._get_token")
    @patch("temba.wpp_flows.tasks.HTTPLog.create_from_exception")
    def test_get_assets_data_success(self, mock_create_from_exception, mock_get_token, mock_requests_get):
        mock_channel = Mock()
        facebook_flow_id = "test_flow_id"
        mock_get_token.return_value = "test_token"

        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"download_url": "https://example.com/download"}]}
        mock_requests_get.side_effect = [mock_resp, Mock(status_code=200, json=Mock(return_value={"key": "value"}))]

        result = get_assets_data(mock_channel, facebook_flow_id)

        self.assertEqual(result, {"key": "value"})
        mock_get_token.assert_called_once_with(mock_channel)
        mock_requests_get.assert_any_call(
            f"{settings.WHATSAPP_API_URL}/{facebook_flow_id}/assets", headers={"Authorization": "Bearer test_token"}
        )
        mock_create_from_exception.assert_not_called()

    @patch("temba.wpp_flows.tasks.requests.get")
    @patch("temba.wpp_flows.tasks._get_token")
    @patch("temba.wpp_flows.tasks.HTTPLog.create_from_exception")
    def test_get_assets_data_failure(self, mock_create_from_exception, mock_get_token, mock_requests_get):
        mock_channel = Mock()
        facebook_flow_id = "test_flow_id"
        mock_get_token.return_value = "test_token"

        mock_requests_get.side_effect = requests.RequestException("Error")

        result = get_assets_data(mock_channel, facebook_flow_id)

        self.assertEqual(result, {})
        mock_get_token.assert_called_once_with(mock_channel)
        mock_requests_get.assert_called_once_with(
            f"{settings.WHATSAPP_API_URL}/{facebook_flow_id}/assets", headers={"Authorization": "Bearer test_token"}
        )
        mock_create_from_exception.assert_called_once()

    @patch("temba.wpp_flows.tasks.requests.get")
    @patch("temba.wpp_flows.tasks._get_token")
    def test_get_assets_data_no_data(self, mock_get_token, mock_requests_get):
        mock_channel = Mock()
        facebook_flow_id = "test_flow_id"
        mock_get_token.return_value = "test_token"

        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}
        mock_requests_get.return_value = mock_resp

        result = get_assets_data(mock_channel, facebook_flow_id)

        self.assertEqual(result, {})
        mock_get_token.assert_called_once_with(mock_channel)
        mock_requests_get.assert_called_once_with(
            f"{settings.WHATSAPP_API_URL}/{facebook_flow_id}/assets", headers={"Authorization": "Bearer test_token"}
        )


class ExtractDataKeysTest(unittest.TestCase):
    def test_extract_data_keys_with_dict(self):
        json_data = {"id": "screen_1", "data": {"var1": "value1", "var2": "value2"}}

        result = extract_data_keys(json_data)
        self.assertCountEqual(result, {"screens": ["screen_1"], "variables": ["var1", "var2"]})

    def test_extract_data_keys_with_list(self):
        json_data = [{"id": "screen_1", "data": {"var1": "value1"}}, {"id": "screen_2", "data": {"var2": "value2"}}]

        result = extract_data_keys(json_data)
        self.assertCountEqual(result, {"screens": ["screen_2", "screen_1"], "variables": ["var1", "var2"]})

    def test_extract_data_keys_empty(self):
        json_data = {}

        result = extract_data_keys(json_data)
        self.assertEqual(result, {"screens": [], "variables": []})
