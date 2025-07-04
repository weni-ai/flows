import json
from unittest.mock import Mock, patch
from uuid import uuid4

from django.test import override_settings

from temba.channels.types.whatsapp_cloud.type import WhatsAppCloudType
from temba.conversion_events.models import CTWA
from temba.conversion_events.serializers import ConversionEventSerializer
from temba.tests import TembaTest


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

    def test_serializer_uuid_validation_edge_case(self):
        """Test serializer UUID validation edge case - covers line 24 in serializers.py"""
        data = {"event_type": "lead", "channel_uuid": "invalid-uuid-format", "contact_urn": "tel:+1234567890"}
        serializer = ConversionEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("channel_uuid", serializer.errors)
        self.assertIn("Must be a valid UUID", str(serializer.errors["channel_uuid"]))

    def test_payload_type_validation(self):
        """Test payload must be a dictionary"""
        data = {
            "event_type": "lead",
            "channel_uuid": str(uuid4()),
            "contact_urn": "tel:+1234567890",
            "payload": "invalid-not-a-dict",
        }
        serializer = ConversionEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("payload", serializer.errors)
        self.assertIn("must be a valid JSON object", str(serializer.errors["payload"]))


class ConversionEventAPITest(TembaTest):
    """Test the ConversionEvent API endpoint following RapidPro patterns"""

    def setUp(self):
        super().setUp()
        # Patch WhatsAppCloudType.activate para evitar erro de configuração obrigatória
        self.activate_patcher = patch.object(WhatsAppCloudType, "activate", return_value=None)
        self.activate_patcher.start()
        self.addCleanup(self.activate_patcher.stop)

        # Create test channel with Meta configuration
        self.channel = self.create_channel(
            "WAC",
            "Test WhatsApp Channel",
            "+12065551212",
            country="US",
            config={"meta_dataset_id": "test_dataset_123"},
        )

        # Create CTWA data for testing
        self.ctwa_data = CTWA.objects.create(
            ctwa_clid="test_clid_123",
            channel_uuid=self.channel.uuid,
            waba="test_waba_123",
            contact_urn="whatsapp:+5511999999999",
        )

        self.endpoint_url = "/conversion/"  # Since it's included at root level
        self.valid_payload = {
            "event_type": "lead",
            "channel_uuid": str(self.channel.uuid),
            "contact_urn": "whatsapp:+5511999999999",
            "payload": {"custom": "data"},
        }

    @override_settings(
        OIDC_RP_CLIENT_ID="test-client-id",
        OIDC_RP_CLIENT_SECRET="test-client-secret",
        OIDC_OP_AUTHORIZATION_ENDPOINT="http://example.com/oauth2/auth",
        OIDC_OP_TOKEN_ENDPOINT="http://example.com/oauth2/token",
        OIDC_OP_USER_ENDPOINT="http://example.com/oauth2/userinfo",
        OIDC_OP_JWKS_ENDPOINT="http://example.com/oauth2/jwks",
    )
    def test_endpoint_requires_internal_auth(self):
        """Test that the endpoint requires internal authentication"""
        # Without authentication, should get 401
        response = self.client.post(
            self.endpoint_url,
            data=json.dumps(self.valid_payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    @patch("temba.conversion_events.views.InternalGenericViewSet.get_authenticators")
    @patch("temba.conversion_events.views.InternalGenericViewSet.get_permissions")
    def test_successful_lead_conversion(self, mock_permissions, mock_authenticators):
        """Test successful lead conversion event"""
        # Mock internal authentication
        mock_authenticators.return_value = []
        mock_permissions.return_value = []

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
                    self.endpoint_url,
                    data=json.dumps(self.valid_payload),
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 200)
                response_data = response.json()
                self.assertEqual(response_data["status"], "success")
                self.assertEqual(response_data["message"], "Event sent to Meta successfully")

                # Verify Meta API was called with correct parameters
                mock_post.assert_called_once()
                call_args = mock_post.call_args
                self.assertIn("test_dataset_123", call_args[0][0])
                self.assertIn("access_token=test_token", call_args[0][0])

    @patch("temba.conversion_events.views.InternalGenericViewSet.get_authenticators")
    @patch("temba.conversion_events.views.InternalGenericViewSet.get_permissions")
    def test_successful_purchase_conversion(self, mock_permissions, mock_authenticators):
        """Test successful purchase conversion event maps to correct event name"""
        mock_authenticators.return_value = []
        mock_permissions.return_value = []

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
            ):
                response = self.client.post(
                    self.endpoint_url, data=json.dumps(payload), content_type="application/json"
                )

                self.assertEqual(response.status_code, 200)

                # Verify the payload sent to Meta includes Purchase event
                call_kwargs = mock_post.call_args[1]
                sent_payload = call_kwargs["json"]
                self.assertEqual(sent_payload["data"][0]["event_name"], "Purchase")

    @patch("temba.conversion_events.views.InternalGenericViewSet.get_authenticators")
    @patch("temba.conversion_events.views.InternalGenericViewSet.get_permissions")
    def test_ctwa_data_not_found(self, mock_permissions, mock_authenticators):
        """Test when CTWA data is not found"""
        mock_authenticators.return_value = []
        mock_permissions.return_value = []

        payload = self.valid_payload.copy()
        payload["contact_urn"] = "whatsapp:+5511888888888"  # Non-existent contact

        response = self.client.post(self.endpoint_url, data=json.dumps(payload), content_type="application/json")

        self.assertEqual(response.status_code, 404)
        response_data = response.json()
        self.assertEqual(response_data["error"], "CTWA Data Not Found")
        self.assertIn("No CTWA data found", response_data["detail"])

    @patch("temba.conversion_events.views.InternalGenericViewSet.get_authenticators")
    @patch("temba.conversion_events.views.InternalGenericViewSet.get_permissions")
    def test_channel_missing_dataset_id(self, mock_permissions, mock_authenticators):
        """Test when channel doesn't have meta_dataset_id configured"""
        mock_authenticators.return_value = []
        mock_permissions.return_value = []

        # Create channel without dataset_id
        channel_without_dataset = self.create_channel("WAC", "No Dataset Channel", "+12065551213", config={})

        CTWA.objects.create(
            ctwa_clid="test_clid_456",
            channel_uuid=channel_without_dataset.uuid,
            waba="test_waba_456",
            contact_urn="whatsapp:+5511888888888",
        )

        payload = self.valid_payload.copy()
        payload["channel_uuid"] = str(channel_without_dataset.uuid)
        payload["contact_urn"] = "whatsapp:+5511888888888"

        response = self.client.post(self.endpoint_url, data=json.dumps(payload), content_type="application/json")

        self.assertEqual(response.status_code, 404)
        response_data = response.json()
        self.assertEqual(response_data["error"], "Dataset ID Not Found")

    @patch("temba.conversion_events.views.InternalGenericViewSet.get_authenticators")
    @patch("temba.conversion_events.views.InternalGenericViewSet.get_permissions")
    def test_missing_access_token(self, mock_permissions, mock_authenticators):
        """Test behavior when Meta access token is not configured"""
        mock_authenticators.return_value = []
        mock_permissions.return_value = []

        with override_settings(WHATSAPP_ADMIN_SYSTEM_USER_TOKEN=""):
            response = self.client.post(
                self.endpoint_url,
                data=json.dumps(self.valid_payload),
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 500)
            response_data = response.json()
            self.assertEqual(response_data["error"], "Meta API Error")
            self.assertIn("Meta access token not configured", response_data["detail"])

    @patch("temba.conversion_events.views.InternalGenericViewSet.get_authenticators")
    @patch("temba.conversion_events.views.InternalGenericViewSet.get_permissions")
    def test_meta_api_error_handling(self, mock_permissions, mock_authenticators):
        """Test Meta API error responses are handled properly"""
        mock_authenticators.return_value = []
        mock_permissions.return_value = []

        with patch("temba.conversion_events.views.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 400
            mock_response.json.return_value = {"error": "Invalid request"}
            mock_post.return_value = mock_response

            with override_settings(WHATSAPP_ADMIN_SYSTEM_USER_TOKEN="test_token"):
                response = self.client.post(
                    self.endpoint_url,
                    data=json.dumps(self.valid_payload),
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 500)
                response_data = response.json()
                self.assertEqual(response_data["error"], "Meta API Error")

    @patch("temba.conversion_events.views.InternalGenericViewSet.get_authenticators")
    @patch("temba.conversion_events.views.InternalGenericViewSet.get_permissions")
    def test_network_error_handling(self, mock_permissions, mock_authenticators):
        """Test network errors are handled gracefully"""
        mock_authenticators.return_value = []
        mock_permissions.return_value = []

        with patch("temba.conversion_events.views.requests.post") as mock_post:
            mock_post.side_effect = Exception("Network error")

            with override_settings(WHATSAPP_ADMIN_SYSTEM_USER_TOKEN="test_token"):
                response = self.client.post(
                    self.endpoint_url,
                    data=json.dumps(self.valid_payload),
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 500)
                response_data = response.json()
                self.assertEqual(response_data["error"], "Meta API Error")

    @patch("temba.conversion_events.views.InternalGenericViewSet.get_authenticators")
    @patch("temba.conversion_events.views.InternalGenericViewSet.get_permissions")
    def test_invalid_json_handling(self, mock_permissions, mock_authenticators):
        """Test invalid JSON in request body"""
        mock_authenticators.return_value = []
        mock_permissions.return_value = []

        response = self.client.post(
            self.endpoint_url,
            data="invalid json",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertEqual(response_data["error"], "Invalid JSON")

    @patch("temba.conversion_events.views.InternalGenericViewSet.get_authenticators")
    @patch("temba.conversion_events.views.InternalGenericViewSet.get_permissions")
    def test_validation_errors(self, mock_permissions, mock_authenticators):
        """Test validation errors are returned properly"""
        mock_authenticators.return_value = []
        mock_permissions.return_value = []

        invalid_payload = {"event_type": "invalid", "channel_uuid": "not-a-uuid"}

        response = self.client.post(
            self.endpoint_url,
            data=json.dumps(invalid_payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertEqual(response_data["error"], "Validation Error")
        self.assertIn("detail", response_data)

    @patch("temba.conversion_events.views.InternalGenericViewSet.get_authenticators")
    @patch("temba.conversion_events.views.InternalGenericViewSet.get_permissions")
    def test_request_with_no_data_attribute(self, mock_permissions, mock_authenticators):
        """Test edge case when request has no data attribute"""
        mock_authenticators.return_value = []
        mock_permissions.return_value = []

        from django.test import RequestFactory
        from temba.conversion_events.views import ConversionEventView

        factory = RequestFactory()
        request = factory.post("/conversion/", content_type="application/json")
        request.data = None

        view = ConversionEventView()
        response = view.create(request)

        self.assertEqual(response.status_code, 400)
        response_data = json.loads(response.content.decode())
        self.assertEqual(response_data["error"], "Invalid JSON")

    @patch("temba.conversion_events.views.InternalGenericViewSet.get_authenticators")
    @patch("temba.conversion_events.views.InternalGenericViewSet.get_permissions")
    @patch("temba.conversion_events.models.CTWA.objects.filter")
    def test_database_exception_in_ctwa_lookup(self, mock_filter, mock_permissions, mock_authenticators):
        """Test database exception during CTWA lookup"""
        mock_authenticators.return_value = []
        mock_permissions.return_value = []
        mock_filter.side_effect = Exception("Database error")

        response = self.client.post(
            self.endpoint_url,
            data=json.dumps(self.valid_payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)
        response_data = response.json()
        self.assertEqual(response_data["error"], "CTWA Data Not Found")

    @patch("temba.conversion_events.views.InternalGenericViewSet.get_authenticators")
    @patch("temba.conversion_events.views.InternalGenericViewSet.get_permissions")
    @patch("temba.channels.models.Channel.objects.filter")
    def test_database_exception_in_channel_lookup(self, mock_filter, mock_permissions, mock_authenticators):
        """Test handling of database errors when looking up channel information"""
        mock_authenticators.return_value = []
        mock_permissions.return_value = []
        mock_filter.side_effect = Exception("Database error")

        response = self.client.post(
            self.endpoint_url,
            data=json.dumps(self.valid_payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)
        response_data = response.json()
        self.assertEqual(response_data["error"], "Dataset ID Not Found")


class CTWAModelTest(TembaTest):
    """Test the CTWA model"""

    def setUp(self):
        super().setUp()

        self.channel = self.create_channel("WAC", "Test Channel", "+1234567890")

    def test_ctwa_creation(self):
        """Test basic CTWA model creation and fields"""
        ctwa = CTWA.objects.create(
            ctwa_clid="test_clid",
            channel_uuid=self.channel.uuid,
            waba="test_waba",
            contact_urn="whatsapp:+1234567890",
        )

        self.assertEqual(ctwa.ctwa_clid, "test_clid")
        self.assertEqual(ctwa.channel_uuid, self.channel.uuid)
        self.assertEqual(ctwa.waba, "test_waba")
        self.assertEqual(ctwa.contact_urn, "whatsapp:+1234567890")
        self.assertIsNotNone(ctwa.timestamp)

    def test_ctwa_str_method(self):
        """Test CTWA string representation"""
        ctwa = CTWA.objects.create(
            ctwa_clid="test_clid",
            channel_uuid=self.channel.uuid,
            waba="test_waba",
            contact_urn="whatsapp:+1234567890",
        )

        expected_str = f"CTWA Data - CLID: test_clid, Channel: {self.channel.uuid}"
        self.assertEqual(str(ctwa), expected_str)

    def test_ctwa_filtering_and_queries(self):
        """Test CTWA filtering capabilities"""
        # Create multiple CTWA records
        ctwa1 = CTWA.objects.create(
            ctwa_clid="clid1", channel_uuid=self.channel.uuid, waba="waba1", contact_urn="whatsapp:+1111111111"
        )
        ctwa2 = CTWA.objects.create(
            ctwa_clid="clid2", channel_uuid=self.channel.uuid, waba="waba2", contact_urn="whatsapp:+2222222222"
        )

        # Test filtering by channel_uuid
        channel_ctwas = CTWA.objects.filter(channel_uuid=self.channel.uuid)
        self.assertEqual(channel_ctwas.count(), 2)

        # Test filtering by contact_urn
        specific_ctwa = CTWA.objects.filter(contact_urn="whatsapp:+1111111111").first()
        self.assertEqual(specific_ctwa, ctwa1)

        # Test combined filter (as used in the view)
        lookup_ctwa = CTWA.objects.filter(channel_uuid=self.channel.uuid, contact_urn="whatsapp:+2222222222").first()
        self.assertEqual(lookup_ctwa, ctwa2)
