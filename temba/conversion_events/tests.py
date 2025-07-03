import json
from unittest.mock import patch, Mock
from datetime import datetime
from uuid import uuid4

from django.test import override_settings
from django.urls import reverse

from temba.tests import TembaTest
from temba.channels.models import Channel
from temba.conversion_events.models import CTWA
from temba.conversion_events.serializers import ConversionEventSerializer


class ConversionEventSerializerTest(TembaTest):
    """Test the ConversionEventSerializer validation"""

    def test_valid_data(self):
        """Test serializer with valid data"""
        data = {
            "event_type": "lead",
            "channel_uuid": str(uuid4()),
            "contact_urn": "whatsapp:+5511999999999",
            "payload": {"custom": "data"},
        }
        serializer = ConversionEventSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_missing_required_fields(self):
        """Test serializer with missing required fields"""
        # Missing event_type
        data = {"channel_uuid": str(uuid4()), "contact_urn": "whatsapp:+5511999999999"}
        serializer = ConversionEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("event_type", serializer.errors)

        # Missing channel_uuid
        data = {"event_type": "lead", "contact_urn": "whatsapp:+5511999999999"}
        serializer = ConversionEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("channel_uuid", serializer.errors)

        # Missing contact_urn
        data = {"event_type": "lead", "channel_uuid": str(uuid4())}
        serializer = ConversionEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("contact_urn", serializer.errors)

    def test_invalid_event_type(self):
        """Test serializer with invalid event type"""
        data = {
            "event_type": "invalid_type",
            "channel_uuid": str(uuid4()),
            "contact_urn": "whatsapp:+5511999999999",
        }
        serializer = ConversionEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("event_type", serializer.errors)

    def test_invalid_channel_uuid(self):
        """Test serializer with invalid channel UUID"""
        data = {
            "event_type": "lead",
            "channel_uuid": "invalid-uuid",
            "contact_urn": "whatsapp:+5511999999999",
        }
        serializer = ConversionEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("channel_uuid", serializer.errors)

    def test_invalid_payload(self):
        """Test serializer with invalid payload"""
        data = {
            "event_type": "lead",
            "channel_uuid": str(uuid4()),
            "contact_urn": "whatsapp:+5511999999999",
            "payload": "invalid_json",
        }
        serializer = ConversionEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("payload", serializer.errors)


class ConversionEventViewTest(TembaTest):
    """Test the ConversionEventView API endpoint"""

    def setUp(self):
        super().setUp()

        # Create a channel
        self.channel = Channel.create(
            self.org,
            self.user,
            "US",
            "WAC",
            name="Test WhatsApp Channel",
            address="+12065551212",
            config={"meta_dataset_id": "test_dataset_123", "auth_token": "test_token"},
        )

        # Create CTWA data
        self.ctwa_data = CTWA.objects.create(
            ctwa_clid="test_clid_123",
            channel_uuid=self.channel.uuid,
            waba="test_waba_123",
            contact_urn="whatsapp:+5511999999999",
        )

        self.url = "/api/v2/conversion/"
        self.valid_payload = {
            "event_type": "lead",
            "channel_uuid": str(self.channel.uuid),
            "contact_urn": "whatsapp:+5511999999999",
            "payload": {"custom": "data"},
        }

    def test_successful_lead_conversion(self):
        """Test successful lead conversion event"""
        with patch("temba.conversion_events.views.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"success": True}
            mock_post.return_value = mock_response

            with override_settings(
                WHATSAPP_ADMIN_SYSTEM_USER_TOKEN="test_token",
                WHATSAPP_API_URL="https://graph.facebook.com/v18.0",
                META_PARTNER_AGENT="Weni by VTEX",
            ):
                response = self.client.post(
                    self.url,
                    data=json.dumps(self.valid_payload),
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "success")

                # Verify the Meta API was called
                mock_post.assert_called_once()
                call_args = mock_post.call_args
                self.assertIn("test_dataset_123", call_args[0][0])
                self.assertIn("access_token=test_token", call_args[0][0])

    def test_successful_purchase_conversion(self):
        """Test successful purchase conversion event"""
        payload = self.valid_payload.copy()
        payload["event_type"] = "purchase"

        with patch("temba.conversion_events.views.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"success": True}
            mock_post.return_value = mock_response

            with override_settings(
                WHATSAPP_ADMIN_SYSTEM_USER_TOKEN="test_token",
                WHATSAPP_API_URL="https://graph.facebook.com/v18.0",
                META_PARTNER_AGENT="Weni by VTEX",
            ):
                response = self.client.post(
                    self.url, data=json.dumps(payload), content_type="application/json"
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "success")

    def test_ctwa_data_not_found(self):
        """Test when CTWA data is not found for the channel and contact"""
        payload = self.valid_payload.copy()
        payload["contact_urn"] = "whatsapp:+5511888888888"  # Different contact

        response = self.client.post(
            self.url, data=json.dumps(payload), content_type="application/json"
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "CTWA Data Not Found")

    def test_channel_not_found(self):
        """Test when channel is not found"""
        payload = self.valid_payload.copy()
        payload["channel_uuid"] = str(uuid4())  # Non-existent channel

        response = self.client.post(
            self.url, data=json.dumps(payload), content_type="application/json"
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "CTWA Data Not Found")

    def test_missing_dataset_id(self):
        """Test when dataset_id is not configured in channel"""
        # Create channel without dataset_id
        channel_without_dataset = Channel.create(
            self.org,
            self.user,
            "US",
            "WAC",
            name="Test Channel No Dataset",
            address="+12065551213",
            config={},
        )

        CTWA.objects.create(
            ctwa_clid="test_clid_456",
            channel_uuid=channel_without_dataset.uuid,
            waba="test_waba_456",
            contact_urn="whatsapp:+5511888888888",
        )

        payload = self.valid_payload.copy()
        payload["channel_uuid"] = str(channel_without_dataset.uuid)
        payload["contact_urn"] = "whatsapp:+5511888888888"

        response = self.client.post(
            self.url, data=json.dumps(payload), content_type="application/json"
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "Dataset ID Not Found")

    def test_missing_access_token(self):
        """Test when access token is not configured"""
        with override_settings(WHATSAPP_ADMIN_SYSTEM_USER_TOKEN=""):
            response = self.client.post(
                self.url,
                data=json.dumps(self.valid_payload),
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.json()["error"], "Meta API Error")

    def test_meta_api_error(self):
        """Test when Meta API returns an error"""
        with patch("temba.conversion_events.views.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 400
            mock_response.json.return_value = {"error": "Invalid request"}
            mock_post.return_value = mock_response

            with override_settings(
                WHATSAPP_ADMIN_SYSTEM_USER_TOKEN="test_token",
                WHATSAPP_API_URL="https://graph.facebook.com/v18.0",
            ):
                response = self.client.post(
                    self.url,
                    data=json.dumps(self.valid_payload),
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.json()["error"], "Meta API Error")

    def test_meta_api_network_error(self):
        """Test when Meta API has network issues"""
        with patch("temba.conversion_events.views.requests.post") as mock_post:
            mock_post.side_effect = Exception("Network error")

            with override_settings(
                WHATSAPP_ADMIN_SYSTEM_USER_TOKEN="test_token",
                WHATSAPP_API_URL="https://graph.facebook.com/v18.0",
            ):
                response = self.client.post(
                    self.url,
                    data=json.dumps(self.valid_payload),
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.json()["error"], "Meta API Error")

    def test_invalid_json_payload(self):
        """Test with invalid JSON payload"""
        response = self.client.post(
            self.url, data="invalid json", content_type="application/json"
        )

        self.assertEqual(response.status_code, 400)

    def test_validation_error(self):
        """Test with validation errors"""
        invalid_payload = {
            "event_type": "invalid_type",
            "channel_uuid": "invalid-uuid",
            "contact_urn": "whatsapp:+5511999999999",
        }

        response = self.client.post(
            self.url, data=json.dumps(invalid_payload), content_type="application/json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Validation Error")

    def test_build_meta_payload(self):
        """Test the _build_meta_payload method"""
        from temba.conversion_events.views import ConversionEventView

        view = ConversionEventView()
        ctwa_data = self.ctwa_data

        # Test lead event
        with patch("temba.conversion_events.views.datetime") as mock_datetime:
            mock_datetime.now.return_value.timestamp.return_value = 1234567890

            payload = view._build_meta_payload("lead", ctwa_data, {})

            self.assertEqual(payload["data"][0]["event_name"], "Lead")
            self.assertEqual(payload["data"][0]["event_time"], 1234567890)
            self.assertEqual(payload["data"][0]["action_source"], "business_messaging")
            self.assertEqual(payload["data"][0]["messaging_channel"], "whatsapp")
            self.assertEqual(
                payload["data"][0]["user_data"]["whatsapp_business_account_id"],
                "test_waba_123",
            )
            self.assertEqual(
                payload["data"][0]["user_data"]["ctwa_clid"], "test_clid_123"
            )

        # Test purchase event
        with patch("temba.conversion_events.views.datetime") as mock_datetime:
            mock_datetime.now.return_value.timestamp.return_value = 1234567890

            payload = view._build_meta_payload("purchase", ctwa_data, {})

            self.assertEqual(payload["data"][0]["event_name"], "Purchase")

    def test_get_channel_dataset_id(self):
        """Test the _get_channel_dataset_id method"""
        from temba.conversion_events.views import ConversionEventView

        view = ConversionEventView()

        # Test with existing channel
        dataset_id = view._get_channel_dataset_id(self.channel.uuid)
        self.assertEqual(dataset_id, "test_dataset_123")

        # Test with non-existent channel
        dataset_id = view._get_channel_dataset_id(uuid4())
        self.assertIsNone(dataset_id)

    def test_get_ctwa_data(self):
        """Test the _get_ctwa_data method"""
        from temba.conversion_events.views import ConversionEventView

        view = ConversionEventView()

        # Test with existing CTWA data
        ctwa_data = view._get_ctwa_data(self.channel.uuid, "whatsapp:+5511999999999")
        self.assertIsNotNone(ctwa_data)
        self.assertEqual(ctwa_data.ctwa_clid, "test_clid_123")

        # Test with non-existent CTWA data
        ctwa_data = view._get_ctwa_data(self.channel.uuid, "whatsapp:+5511888888888")
        self.assertIsNone(ctwa_data)


class CTWAModelTest(TembaTest):
    """Test the CTWA model"""

    def test_ctwa_creation(self):
        """Test CTWA model creation"""
        ctwa = CTWA.objects.create(
            ctwa_clid="test_clid_123",
            channel_uuid=self.channel.uuid,
            waba="test_waba_123",
            contact_urn="whatsapp:+5511999999999",
        )

        self.assertEqual(ctwa.ctwa_clid, "test_clid_123")
        self.assertEqual(ctwa.channel_uuid, self.channel.uuid)
        self.assertEqual(ctwa.waba, "test_waba_123")
        self.assertEqual(ctwa.contact_urn, "whatsapp:+5511999999999")
        self.assertIsNotNone(ctwa.timestamp)

    def test_ctwa_str_method(self):
        """Test CTWA string representation"""
        ctwa = CTWA.objects.create(
            ctwa_clid="test_clid_123",
            channel_uuid=self.channel.uuid,
            waba="test_waba_123",
            contact_urn="whatsapp:+5511999999999",
        )

        expected_str = f"CTWA Data - CLID: test_clid_123, Channel: {self.channel.uuid}"
        self.assertEqual(str(ctwa), expected_str)

    def test_ctwa_filtering(self):
        """Test CTWA filtering by channel_uuid and contact_urn"""
        # Create multiple CTWA entries
        ctwa1 = CTWA.objects.create(
            ctwa_clid="test_clid_1",
            channel_uuid=self.channel.uuid,
            waba="test_waba_1",
            contact_urn="whatsapp:+5511999999999",
        )

        ctwa2 = CTWA.objects.create(
            ctwa_clid="test_clid_2",
            channel_uuid=self.channel.uuid,
            waba="test_waba_2",
            contact_urn="whatsapp:+5511888888888",
        )

        # Test filtering by channel_uuid and contact_urn
        result = CTWA.objects.filter(
            channel_uuid=self.channel.uuid, contact_urn="whatsapp:+5511999999999"
        ).first()

        self.assertEqual(result, ctwa1)
        self.assertEqual(result.ctwa_clid, "test_clid_1")

        # Test filtering with different contact_urn
        result = CTWA.objects.filter(
            channel_uuid=self.channel.uuid, contact_urn="whatsapp:+5511888888888"
        ).first()

        self.assertEqual(result, ctwa2)
        self.assertEqual(result.ctwa_clid, "test_clid_2")

        # Test filtering with non-existent combination
        result = CTWA.objects.filter(
            channel_uuid=self.channel.uuid, contact_urn="whatsapp:+5511777777777"
        ).first()

        self.assertIsNone(result)
