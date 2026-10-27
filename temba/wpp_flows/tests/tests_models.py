import unittest
from unittest.mock import Mock, patch

import requests

from django.conf import settings
from django.db import DatabaseError
from django.utils import timezone

from temba.wpp_flows.tasks import (
    _get_token,
    _sanitize_json_for_postgres,
    _update_assets,
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
        self,
        mock_update_whatsapp_flows,
        mock_get_whatsapp_flows,
        mock_channel_filter,
        mock_get_redis_connection,
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
        self,
        mock_get_token,
        mock_create_from_exception,
        mock_create_from_response,
        mock_requests_get,
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

    @patch("temba.wpp_flows.tasks.WhatsappFlow.trim")
    @patch("temba.wpp_flows.tasks.get_assets_data")
    @patch("temba.wpp_flows.tasks.timezone.now")
    @patch("temba.wpp_flows.tasks.WhatsappFlow.objects.filter")
    def test_update_whatsapp_flows(self, mock_filter, mock_timezone_now, mock_get_assets, mock_trim):
        mock_channel = Mock()
        mock_channel.org = Mock()
        mock_flow = Mock()
        mock_timezone_now.return_value = timezone.now()
        mock_get_assets.return_value = {}

        flows = [
            {
                "id": "flow1",
                "categories": ["cat1"],
                "status": "active",
                "name": "Flow 1",
                "validation_errors": [],
            }
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
        mock_trim.assert_called_once_with(mock_channel, ["flow1"])

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

    @patch("temba.wpp_flows.tasks.WhatsappFlow.trim")
    @patch("temba.wpp_flows.tasks.get_assets_data")
    @patch("temba.wpp_flows.tasks.WhatsappFlow.objects.filter")
    def test_update_whatsapp_flows_continues_on_save_error(self, mock_filter, mock_get_assets, mock_trim):
        mock_channel = Mock()
        mock_channel.id = 1
        mock_channel.org = Mock()
        mock_get_assets.return_value = {}

        failing_flow = Mock()
        failing_flow.save.side_effect = DatabaseError("db error")

        ok_flow = Mock()

        flows = [
            {
                "id": "flow1",
                "categories": ["cat1"],
                "status": "active",
                "name": "Flow 1",
                "validation_errors": [],
            },
            {
                "id": "flow2",
                "categories": ["cat2"],
                "status": "active",
                "name": "Flow 2",
                "validation_errors": [],
            },
        ]

        mock_query = Mock()
        mock_query.first.side_effect = [failing_flow, ok_flow]
        mock_filter.return_value = mock_query

        update_whatsapp_flows(flows, mock_channel)

        ok_flow.save.assert_called_once()
        mock_trim.assert_called_once_with(mock_channel, ["flow1", "flow2"])

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


class SanitizeJsonForPostgresTest(unittest.TestCase):
    def test_replaces_unpaired_surrogates_in_strings(self):
        # High surrogate without a following low surrogate (same class of bad data seen in Sentry).
        dirty = "^(?!.*[\ud83c-])"
        result = _sanitize_json_for_postgres(dirty)
        self.assertNotIn("\ud83c", result)
        self.assertIn("\ufffd", result)

    def test_sanitizes_nested_structures(self):
        payload = {
            "screens": [
                {
                    "id": "INICIO",
                    "layout": {
                        "type": "SingleColumnLayout",
                        "children": [{"type": "TextInput", "pattern": "^(?!.*[\ud83c-\ud83d])"}],
                    },
                }
            ]
        }

        result = _sanitize_json_for_postgres(payload)
        pattern = result["screens"][0]["layout"]["children"][0]["pattern"]
        self.assertNotIn("\ud83c", pattern)
        self.assertNotIn("\ud83d", pattern)
        self.assertEqual(result["screens"][0]["id"], "INICIO")

    def test_leaves_valid_values_unchanged(self):
        payload = {
            "screens": [{"id": "A", "data": {"name": "ok"}}],
            "count": 1,
            "active": True,
            "empty": None,
        }
        self.assertEqual(_sanitize_json_for_postgres(payload), payload)

    def test_sanitizes_dictionary_keys(self):
        dirty_key = "field_\ud83c"
        payload = {dirty_key: "value"}

        result = _sanitize_json_for_postgres(payload)

        self.assertEqual(len(result), 1)
        sanitized_key = next(iter(result))
        self.assertNotIn("\ud83c", sanitized_key)
        self.assertIn("\ufffd", sanitized_key)
        self.assertEqual(result[sanitized_key], "value")


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
        mock_requests_get.side_effect = [
            mock_resp,
            Mock(status_code=200, json=Mock(return_value={"key": "value"})),
        ]

        result = get_assets_data(mock_channel, facebook_flow_id)

        self.assertEqual(result, {"key": "value"})
        mock_get_token.assert_called_once_with(mock_channel)
        mock_requests_get.assert_any_call(
            f"{settings.WHATSAPP_API_URL}/{facebook_flow_id}/assets",
            headers={"Authorization": "Bearer test_token"},
        )
        mock_create_from_exception.assert_not_called()

    @patch("temba.wpp_flows.tasks.requests.get")
    @patch("temba.wpp_flows.tasks._get_token")
    @patch("temba.wpp_flows.tasks.HTTPLog.create_from_exception")
    def test_get_assets_data_sanitizes_surrogates(self, mock_create_from_exception, mock_get_token, mock_requests_get):
        mock_channel = Mock()
        mock_get_token.return_value = "test_token"

        dirty_payload = {"pattern": "^(?!.*[\ud83c-])"}
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"download_url": "https://example.com/download"}]}
        mock_requests_get.side_effect = [
            mock_resp,
            Mock(status_code=200, json=Mock(return_value=dirty_payload)),
        ]

        result = get_assets_data(mock_channel, "flow_id")

        self.assertNotIn("\ud83c", result["pattern"])
        self.assertIn("\ufffd", result["pattern"])
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
            f"{settings.WHATSAPP_API_URL}/{facebook_flow_id}/assets",
            headers={"Authorization": "Bearer test_token"},
        )
        mock_create_from_exception.assert_called_once()

    @patch("temba.wpp_flows.tasks.requests.get")
    @patch("temba.wpp_flows.tasks._get_token")
    @patch("temba.wpp_flows.tasks.HTTPLog.create_from_exception")
    def test_get_assets_data_invalid_json(self, mock_create_from_exception, mock_get_token, mock_requests_get):
        mock_channel = Mock()
        mock_channel.id = 1
        mock_get_token.return_value = "test_token"

        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("Invalid JSON")
        mock_requests_get.return_value = mock_resp

        result = get_assets_data(mock_channel, "flow_id")

        self.assertEqual(result, {})
        mock_create_from_exception.assert_not_called()

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
            f"{settings.WHATSAPP_API_URL}/{facebook_flow_id}/assets",
            headers={"Authorization": "Bearer test_token"},
        )


class UpdateAssetsTest(unittest.TestCase):
    @patch("temba.wpp_flows.tasks.extract_data_keys")
    @patch("temba.wpp_flows.tasks.get_assets_data")
    def test_update_assets_success(self, mock_get_assets, mock_extract):
        mock_get_assets.return_value = {"screens": []}
        mock_extract.return_value = {"screens": [], "variables": []}
        flow = Mock()
        flow.channel = Mock()
        flow.facebook_flow_id = "fb-1"

        result = _update_assets(flow)

        flow.save.assert_called_once()
        self.assertEqual(result, flow)

    @patch("temba.wpp_flows.tasks.extract_data_keys")
    @patch("temba.wpp_flows.tasks.get_assets_data")
    def test_update_assets_swallows_save_error(self, mock_get_assets, mock_extract):
        mock_get_assets.return_value = {"screens": []}
        mock_extract.return_value = {"screens": [], "variables": []}
        flow = Mock()
        flow.id = 10
        flow.facebook_flow_id = "fb-1"
        flow.channel = Mock()
        flow.save.side_effect = DatabaseError("invalid json")

        result = _update_assets(flow)

        self.assertIsNone(result)

    @patch("temba.wpp_flows.tasks.extract_data_keys")
    @patch("temba.wpp_flows.tasks.get_assets_data")
    def test_update_assets_reraises_non_database_error(self, mock_get_assets, mock_extract):
        mock_get_assets.return_value = {"screens": []}
        mock_extract.return_value = {"screens": [], "variables": []}
        flow = Mock()
        flow.id = 10
        flow.facebook_flow_id = "fb-1"
        flow.channel = Mock()
        flow.save.side_effect = AttributeError("bug")

        with self.assertRaises(AttributeError):
            _update_assets(flow)


class ExtractDataKeysTest(unittest.TestCase):
    def test_extract_data_keys_with_dict(self):
        json_data = {"id": "screen_1", "data": {"var1": "value1", "var2": "value2"}}

        result = extract_data_keys(json_data)
        self.assertCountEqual(result, {"screens": ["screen_1"], "variables": ["var1", "var2"]})

    def test_extract_data_keys_with_list(self):
        json_data = [
            {"id": "screen_1", "data": {"var1": "value1"}},
            {"id": "screen_2", "data": {"var2": "value2"}},
        ]

        result = extract_data_keys(json_data)
        self.assertCountEqual(result, {"screens": ["screen_2", "screen_1"], "variables": ["var1", "var2"]})

    def test_extract_data_keys_empty(self):
        json_data = {}

        result = extract_data_keys(json_data)
        self.assertEqual(result, {"screens": [], "variables": []})
