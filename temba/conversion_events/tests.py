import json
from datetime import datetime, timedelta, timezone as dt_timezone
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import jwt
import requests
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory

from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from temba.channels.models import Channel
from temba.channels.types.whatsapp_cloud.type import WhatsAppCloudType
from temba.conversion_events.jwt_auth import JWTModuleAuthentication, JWTModuleAuthMixin
from temba.conversion_events.models import CTWA, CtwaReferralSource
from temba.conversion_events.serializers import ConversionEventSerializer
from temba.conversion_events.urns import whatsapp_urn_variants
from temba.conversion_events.views import format_datalake_event_date
from temba.tests import TembaTest

_backfill = import_module("temba.conversion_events.migrations.0004_backfill_ctwareferralsource_org")
apply_orgs_to_source = _backfill.apply_orgs_to_source
backfill_ctwa_referral_source_org = _backfill.backfill_ctwa_referral_source_org
delete_unresolved_sources = _backfill.delete_unresolved_sources
org_channels_by_source_id = _backfill.org_channels_by_source_id
resolve_batch_orgs = _backfill.resolve_batch_orgs

_collapse = import_module("temba.conversion_events.migrations.0006_collapse_legacy_ctwa_referral_sources")
collapse_legacy_sources_per_org = _collapse.collapse_legacy_sources_per_org
collapse_org_legacy_sources = _collapse.collapse_org_legacy_sources
legacy_sources = _collapse.legacy_sources
org_ids_with_legacy_sources = _collapse.org_ids_with_legacy_sources
preserve_seen_window = _collapse.preserve_seen_window


class FormatDatalakeEventDateTest(TestCase):
    def test_formats_aware_datetime_as_utc_z_suffix(self):
        dt = datetime(2026, 1, 15, 12, 30, 0, tzinfo=dt_timezone.utc)
        self.assertEqual(format_datalake_event_date(dt), "2026-01-15T12:30:00Z")

    def test_formats_naive_datetime_as_utc(self):
        dt = datetime(2026, 1, 15, 12, 30, 0)
        self.assertEqual(format_datalake_event_date(dt), "2026-01-15T12:30:00Z")


def create_test_ctwa(**kwargs):
    referral_source = kwargs.pop("referral_source", None)
    org = kwargs.pop("org", None)
    if referral_source is None:
        source_id = kwargs.pop("source_id", f"test-source-{uuid4()}")
        source_type = kwargs.pop("source_type", CtwaReferralSource.SOURCE_TYPE_AD)
        if org is None:
            channel_uuid = kwargs.get("channel_uuid")
            if channel_uuid is not None:
                channel = Channel.objects.filter(uuid=str(channel_uuid)).select_related("org").first()
                if channel is not None:
                    org = channel.org
        referral_source, _ = CtwaReferralSource.get_or_create_for_org(org, source_id, source_type)

    defaults = {"timestamp": timezone.now()}
    defaults.update(kwargs)
    return CTWA.objects.create(referral_source=referral_source, **defaults)


class ConversionEventSerializerTest(TembaTest):
    """Test the ConversionEventSerializer validation"""

    def test_valid_data(self):
        """Test serializer with valid data"""
        data = {
            "event_type": "lead",
            "channel_uuid": str(uuid4()),
            "contact_urn": "whatsapp:5511999999999",
            "payload": {"custom": "data"},
        }
        serializer = ConversionEventSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_missing_required_fields(self):
        """Test serializer with missing required fields"""
        # Missing event_type
        data = {"channel_uuid": str(uuid4()), "contact_urn": "whatsapp:5511999999999"}
        serializer = ConversionEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("event_type", serializer.errors)

        # Missing channel_uuid
        data = {"event_type": "lead", "contact_urn": "whatsapp:5511999999999"}
        serializer = ConversionEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("channel_uuid", serializer.errors)

        # Missing contact_urn
        data = {"event_type": "lead", "channel_uuid": str(uuid4())}
        serializer = ConversionEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("contact_urn", serializer.errors)

    def test_valid_abandoned_cart_event_type(self):
        """Test serializer accepts abandoned_cart event type"""
        data = {
            "event_type": "abandoned_cart",
            "channel_uuid": str(uuid4()),
            "contact_urn": "whatsapp:5511999999999",
            "payload": {"value": "59.90", "currency": "BRL"},
        }
        serializer = ConversionEventSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_invalid_event_type(self):
        """Test serializer with invalid event type"""
        data = {
            "event_type": "invalid_type",
            "channel_uuid": str(uuid4()),
            "contact_urn": "whatsapp:5511999999999",
        }
        serializer = ConversionEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("event_type", serializer.errors)

    def test_invalid_channel_uuid(self):
        """Test serializer with invalid channel UUID"""
        data = {
            "event_type": "lead",
            "channel_uuid": "invalid-uuid",
            "contact_urn": "whatsapp:5511999999999",
        }
        serializer = ConversionEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("channel_uuid", serializer.errors)

    def test_invalid_payload(self):
        """Test serializer with invalid payload"""
        data = {
            "event_type": "lead",
            "channel_uuid": str(uuid4()),
            "contact_urn": "whatsapp:5511999999999",
            "payload": "invalid_json",
        }
        serializer = ConversionEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("payload", serializer.errors)

    def test_serializer_uuid_validation_edge_case(self):
        """Test serializer UUID validation edge case - covers line 24 in serializers.py"""
        data = {
            "event_type": "lead",
            "channel_uuid": "invalid-uuid-format",
            "contact_urn": "tel:1234567890",
        }
        serializer = ConversionEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("channel_uuid", serializer.errors)
        self.assertIn("Must be a valid UUID", str(serializer.errors["channel_uuid"]))

    def test_payload_type_validation(self):
        """Test payload must be a dictionary"""
        data = {
            "event_type": "lead",
            "channel_uuid": str(uuid4()),
            "contact_urn": "tel:1234567890",
            "payload": "invalid-not-a-dict",
        }
        serializer = ConversionEventSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("payload", serializer.errors)
        self.assertIn("must be a valid JSON object", str(serializer.errors["payload"]))

    def test_valid_conversation_started_data(self):
        data = {
            "event_type": "conversation_started",
            "channel_uuid": str(uuid4()),
            "contact_urn": "whatsapp:5511999999999",
            "payload": {"message_id": "wamid.test"},
        }
        serializer = ConversionEventSerializer(data=data)
        self.assertTrue(serializer.is_valid())


MOCK_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAuQw1Qw1Qw1Qw1Qw1Qw1Qw1Q\nw1Qw1Qw1Qw1Qw1Qw1Qw1Qw1Qw1Qw1Qw1Qw1Qw1Qw1Qw1Qw1Qw1Qw1Qw1Qw1Qw1Qw\n1Qw1Qw1Qw1Qw1Qw1Qw1Qw1Qw1Qw1QwIDAQAB\n-----END PUBLIC KEY-----"""


class ConversionEventAPITest(TembaTest):
    """Test the ConversionEvent API endpoint following RapidPro patterns"""

    def setUp(self):
        super().setUp()
        # Mock JWT authentication for all API tests
        self.jwt_auth_patcher = patch(
            "temba.conversion_events.jwt_auth.JWTModuleAuthentication.authenticate",
            return_value=(AnonymousUser(), None),
        )
        self.jwt_auth_patcher.start()
        self.addCleanup(self.jwt_auth_patcher.stop)
        # Patch WhatsAppCloudType.activate para evitar erro de configuração obrigatória
        self.activate_patcher = patch.object(WhatsAppCloudType, "activate", return_value=None)
        self.activate_patcher.start()
        self.addCleanup(self.activate_patcher.stop)
        # Create test channel with Meta configuration
        self.channel = self.create_channel(
            "WAC",
            "Test WhatsApp Channel",
            "12065551212",
            country="US",
            config={
                "meta_dataset_id": "test_dataset_123",
                "wa_waba_id": "test_waba_123",
            },
        )
        # Create CTWA data for testing
        self.ctwa_data = create_test_ctwa(
            ctwa_clid="test_clid_123",
            channel_uuid=self.channel.uuid,
            waba="test_waba_123",
            contact_urn="whatsapp:5511999999999",
        )
        self.endpoint_url = "/conversion/"  # Since it's included at root level
        self.valid_payload = {
            "event_type": "lead",
            "channel_uuid": str(self.channel.uuid),
            "contact_urn": "whatsapp:5511999999999",
            "payload": {"custom": "data"},
        }

    def test_successful_lead_conversion(self):
        with patch("temba.conversion_events.views.requests.post") as mock_post, patch(
            "temba.conversion_events.views.send_event_data"
        ) as mock_send_event:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"success": True}
            mock_post.return_value = mock_response

            # Set proj_uuid for the org
            self.org.proj_uuid = uuid4()
            self.org.save(update_fields=["proj_uuid"])

            # Add custom data to payload
            payload = self.valid_payload.copy()
            payload["payload"] = {
                "custom_field": "custom_value",
                "order_form_id": "12345",
                "value": "100.00",
                "another_field": "another_value",
            }

            with override_settings(
                WHATSAPP_ADMIN_SYSTEM_USER_TOKEN="test_token",
                WHATSAPP_API_URL="https://graph.facebook.com/v18.0",
                META_PARTNER_AGENT="Weni by VTEX",
            ):
                response = self.client.post(
                    self.endpoint_url,
                    data=json.dumps(payload),
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 200)
                response_data = response.json()
                self.assertEqual(response_data["status"], "success")
                self.assertEqual(
                    response_data["message"],
                    "Event sent to Meta and Datalake successfully",
                )

                # Verify Meta API call
                mock_post.assert_called_once()
                call_args = mock_post.call_args
                self.assertIn("test_dataset_123", call_args[0][0])
                self.assertIn("access_token=test_token", call_args[0][0])

                # Verify Datalake call
                mock_send_event.assert_called_once()
                datalake_call = mock_send_event.call_args
                event_data = datalake_call[0][1]
                self.assertEqual(event_data["event_name"], "conversion_lead")
                self.assertEqual(event_data["key"], "capi")
                self.assertEqual(event_data["value"], "lead")
                self.assertEqual(event_data["project"], str(self.org.proj_uuid))
                # Verify all payload data is in metadata
                self.assertEqual(event_data["metadata"]["channel"], str(self.channel.uuid))
                self.assertEqual(event_data["metadata"]["ctwa_id"], "test_clid_123")
                self.assertEqual(event_data["metadata"]["waba_id"], "test_waba_123")
                self.assertEqual(event_data["metadata"]["custom_field"], "custom_value")
                self.assertEqual(event_data["metadata"]["order_form_id"], "12345")
                self.assertEqual(event_data["metadata"]["value"], "100.00")
                self.assertEqual(event_data["metadata"]["another_field"], "another_value")
                self.assertNotIn("ctwa_id", event_data)  # Verify ctwa_id is not in main payload

    def test_successful_conversion_without_ctwa(self):
        """Test successful conversion event without CTWA data - should only send to Datalake"""
        with patch("temba.conversion_events.views.send_event_data") as mock_send_event:
            # Set proj_uuid for the org
            self.org.proj_uuid = uuid4()
            self.org.save(update_fields=["proj_uuid"])

            # Use a different contact URN that doesn't have CTWA data
            payload = self.valid_payload.copy()
            payload["contact_urn"] = "whatsapp:5511888888888"
            payload["payload"] = {
                "custom_field": "custom_value",
                "order_form_id": "12345",
                "value": "100.00",
            }

            response = self.client.post(
                self.endpoint_url,
                data=json.dumps(payload),
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 200)
            response_data = response.json()
            self.assertEqual(response_data["status"], "success")
            self.assertEqual(response_data["message"], "Event sent to Datalake successfully")

            # Verify Datalake call
            mock_send_event.assert_called_once()
            datalake_call = mock_send_event.call_args
            event_data = datalake_call[0][1]
            self.assertEqual(event_data["event_name"], "conversion_lead")
            self.assertEqual(event_data["project"], str(self.org.proj_uuid))
            # Verify all payload data is in metadata
            self.assertEqual(event_data["metadata"]["channel"], str(self.channel.uuid))
            self.assertEqual(event_data["metadata"]["custom_field"], "custom_value")
            self.assertEqual(event_data["metadata"]["order_form_id"], "12345")
            self.assertEqual(event_data["metadata"]["value"], "100.00")
            self.assertNotIn("ctwa_id", event_data)  # Verify ctwa_id is not in main payload

    def test_datalake_error_handling(self):
        """Test handling of Datalake API errors"""
        self.org.proj_uuid = uuid4()
        self.org.save(update_fields=["proj_uuid"])

        with patch("temba.conversion_events.views.send_event_data") as mock_send_event:
            mock_send_event.side_effect = Exception("API error")

            # Use a different contact URN that doesn't have CTWA data
            payload = self.valid_payload.copy()
            payload["contact_urn"] = "whatsapp:5511888888888"  # Non-existent contact

            response = self.client.post(
                self.endpoint_url,
                data=json.dumps(payload),
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 500)
            response_data = response.json()
            self.assertEqual(response_data["error"], "Datalake Error")
            self.assertIn("Error sending to Datalake", response_data["detail"])
            self.assertIn("API error", response_data["detail"])

    def test_successful_purchase_conversion(self):
        """Test successful purchase conversion with value and currency"""
        payload = self.valid_payload.copy()
        payload["event_type"] = "purchase"
        payload["payload"] = {
            "value": "123.45",
            "currency": "USD",
            "custom_field": "custom_value",
        }

        with patch("temba.conversion_events.views.requests.post") as mock_post, patch(
            "temba.conversion_events.views.send_event_data"
        ) as mock_send_event:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"success": True}
            mock_post.return_value = mock_response

            # Set proj_uuid for the org
            self.org.proj_uuid = uuid4()
            self.org.save(update_fields=["proj_uuid"])

            with override_settings(
                WHATSAPP_ADMIN_SYSTEM_USER_TOKEN="test_token",
                WHATSAPP_API_URL="https://graph.facebook.com/v18.0",
                META_PARTNER_AGENT="Weni by VTEX",
            ):
                response = self.client.post(
                    self.endpoint_url,
                    data=json.dumps(payload),
                    content_type="application/json",
                )

                # Should succeed since we have both CTWA data and dataset_id
                self.assertEqual(response.status_code, 200)
                response_data = response.json()
                self.assertEqual(response_data["status"], "success")
                self.assertEqual(
                    response_data["message"],
                    "Event sent to Meta and Datalake successfully",
                )

                # Verify Meta API call
                mock_post.assert_called_once()
                meta_payload = mock_post.call_args[1]["json"]
                meta_event = meta_payload["data"][0]

                # Value should be float and currency should be string
                self.assertEqual(meta_event["value"], 123.45)
                self.assertEqual(meta_event["currency"], "USD")
                self.assertEqual(meta_event["event_name"], "Purchase")

                # Verify Datalake API call
                mock_send_event.assert_called_once()
                event_data = mock_send_event.call_args[0][1]
                self.assertEqual(event_data["event_name"], "conversion_purchase")
                self.assertEqual(event_data["key"], "capi")
                self.assertEqual(event_data["value"], "purchase")
                self.assertEqual(event_data["value_type"], "string")
                self.assertEqual(event_data["project"], str(self.org.proj_uuid))
                self.assertEqual(event_data["contact_urn"], self.valid_payload["contact_urn"])
                self.assertEqual(event_data["metadata"]["value"], "123.45")
                self.assertEqual(event_data["metadata"]["currency"], "USD")
                self.assertEqual(event_data["metadata"]["custom_field"], "custom_value")

    def test_purchase_conversion_invalid_value(self):
        """Test purchase conversion with invalid value format"""
        payload = self.valid_payload.copy()
        payload["event_type"] = "purchase"
        payload["payload"] = {
            "value": "invalid",
            "currency": "USD",
        }

        with patch("temba.conversion_events.views.requests.post") as mock_post, patch(
            "temba.conversion_events.views.send_event_data"
        ) as mock_send_event:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"success": True}
            mock_post.return_value = mock_response

            # Set proj_uuid for the org
            self.org.proj_uuid = uuid4()
            self.org.save(update_fields=["proj_uuid"])

            with override_settings(
                WHATSAPP_ADMIN_SYSTEM_USER_TOKEN="test_token",
                WHATSAPP_API_URL="https://graph.facebook.com/v18.0",
            ):
                response = self.client.post(
                    self.endpoint_url,
                    data=json.dumps(payload),
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 200)

                # Verify Meta API call
                mock_post.assert_called_once()
                call_kwargs = mock_post.call_args[1]
                sent_payload = call_kwargs["json"]
                meta_event = sent_payload["data"][0]

                # Verify event name
                self.assertEqual(meta_event["event_name"], "Purchase")

                # Verify value and currency are not present due to invalid value
                self.assertNotIn("value", meta_event)
                self.assertNotIn("currency", meta_event)

                # Verify Datalake call still includes the original payload
                mock_send_event.assert_called_once()
                datalake_call = mock_send_event.call_args
                event_data = datalake_call[0][1]
                self.assertEqual(event_data["metadata"]["value"], "invalid")
                self.assertEqual(event_data["metadata"]["currency"], "USD")

    def test_ctwa_data_not_found(self):
        """Test that event is still sent to Datalake when CTWA data is not found"""
        with patch("temba.conversion_events.views.send_event_data") as mock_send_event:
            # Set proj_uuid for the org
            self.org.proj_uuid = uuid4()
            self.org.save(update_fields=["proj_uuid"])

            payload = self.valid_payload.copy()
            payload["contact_urn"] = "whatsapp:5511888888888"  # Non-existent contact
            response = self.client.post(
                self.endpoint_url,
                data=json.dumps(payload),
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 200)
            response_data = response.json()
            self.assertEqual(response_data["status"], "success")
            self.assertEqual(response_data["message"], "Event sent to Datalake successfully")

            # Verify Datalake call
            mock_send_event.assert_called_once()
            datalake_call = mock_send_event.call_args
            event_data = datalake_call[0][1]
            self.assertNotIn("ctwa_id", event_data["metadata"])

    def test_channel_missing_dataset_id(self):
        """Test that event is still sent to Datalake when channel has no dataset_id"""
        with patch("temba.conversion_events.views.send_event_data") as mock_send_event:
            # Set proj_uuid for the org
            self.org.proj_uuid = uuid4()
            self.org.save(update_fields=["proj_uuid"])

            channel_without_dataset = self.create_channel("WAC", "No Dataset Channel", "12065551213", config={})
            create_test_ctwa(
                ctwa_clid="test_clid_456",
                channel_uuid=channel_without_dataset.uuid,
                waba="test_waba_456",
                contact_urn="whatsapp:5511888888888",
            )
            payload = self.valid_payload.copy()
            payload["channel_uuid"] = str(channel_without_dataset.uuid)
            payload["contact_urn"] = "whatsapp:5511888888888"

            response = self.client.post(
                self.endpoint_url,
                data=json.dumps(payload),
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 200)
            response_data = response.json()
            self.assertEqual(response_data["status"], "success")
            self.assertEqual(response_data["message"], "Event sent to Datalake successfully")

            # Verify Datalake call
            mock_send_event.assert_called_once()
            datalake_call = mock_send_event.call_args
            event_data = datalake_call[0][1]
            self.assertEqual(event_data["metadata"]["channel"], str(channel_without_dataset.uuid))

    def test_missing_access_token(self):
        with override_settings(WHATSAPP_ADMIN_SYSTEM_USER_TOKEN=""):
            response = self.client.post(
                self.endpoint_url,
                data=json.dumps(self.valid_payload),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 500)
            response_data = response.json()
            self.assertEqual(response_data["error"], "Meta and Datalake Error")
            self.assertIn("Meta: Meta access token not configured", response_data["detail"])

    def test_meta_api_error_handling(self):
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
                self.assertEqual(response_data["error"], "Meta and Datalake Error")
                self.assertIn("Meta:", response_data["detail"])
                self.assertIn("Datalake:", response_data["detail"])

    def test_network_error_handling(self):
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
                self.assertEqual(response_data["error"], "Meta and Datalake Error")
                self.assertIn(
                    "Meta: Error sending to Meta: Network error",
                    response_data["detail"],
                )

    def test_invalid_json_handling(self):
        response = self.client.post(
            self.endpoint_url,
            data="invalid json",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertEqual(response_data["error"], "Invalid JSON")

    def test_validation_errors(self):
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

    def test_request_with_no_data_attribute(self):
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

    @patch("temba.conversion_events.models.CTWA.objects.filter")
    def test_database_exception_in_ctwa_lookup(self, mock_filter):
        """Test that event is still sent to Datalake when CTWA lookup fails"""
        mock_filter.side_effect = Exception("Database error")

        with patch("temba.conversion_events.views.send_event_data") as mock_send_event:
            # Set proj_uuid for the org
            self.org.proj_uuid = uuid4()
            self.org.save(update_fields=["proj_uuid"])

            response = self.client.post(
                self.endpoint_url,
                data=json.dumps(self.valid_payload),
                content_type="application/json",
            )

            # Should still succeed since we can send to Datalake
            self.assertEqual(response.status_code, 200)
            response_data = response.json()
            self.assertEqual(response_data["status"], "success")
            self.assertEqual(response_data["message"], "Event sent to Datalake successfully")

            # Verify Datalake call
            mock_send_event.assert_called_once()
            datalake_call = mock_send_event.call_args
            event_data = datalake_call[0][1]
            self.assertEqual(event_data["event_name"], "conversion_lead")
            self.assertEqual(event_data["metadata"]["channel"], str(self.channel.uuid))

    def test_database_exception_in_channel_lookup(self):
        """Test that event fails when channel lookup fails"""
        with patch("temba.channels.models.Channel.objects.filter") as mock_filter:
            mock_filter.side_effect = Exception("Database error")

            # Set proj_uuid for the org
            self.org.proj_uuid = uuid4()
            self.org.save(update_fields=["proj_uuid"])

            response = self.client.post(
                self.endpoint_url,
                data=json.dumps(self.valid_payload),
                content_type="application/json",
            )

            # Should fail since we need the channel to send to Datalake
            self.assertEqual(response.status_code, 500)
            response_data = response.json()
            self.assertEqual(response_data["error"], "Datalake Error")
            self.assertIn("Channel not found", response_data["detail"])

    def test_unexpected_error(self):
        """Test handling of unexpected errors in the main try-except block"""
        with patch("temba.conversion_events.views.ConversionEventSerializer") as mock_serializer:
            # Simulate an unexpected error that's not JSON related
            mock_serializer.side_effect = Exception("Unexpected internal error")

            response = self.client.post(
                self.endpoint_url,
                data=json.dumps(self.valid_payload),
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 500)
            response_data = response.json()
            self.assertEqual(response_data["error"], "Internal Server Error")
            self.assertEqual(response_data["detail"], "An unexpected error occurred")

    def test_meta_missing_dataset_id(self):
        """Test handling when Meta dataset_id is not configured but we try to send to Meta"""
        with patch("temba.conversion_events.views.requests.post") as mock_post, patch(
            "temba.conversion_events.views.send_event_data"
        ) as mock_send_event:
            # Set proj_uuid for the org
            self.org.proj_uuid = uuid4()
            self.org.save(update_fields=["proj_uuid"])

            # Create a channel without dataset_id but with CTWA data
            channel_without_dataset = self.create_channel(
                "WAC",
                "No Dataset Channel",
                "12065551213",
                config={},  # Empty config means no dataset_id
            )
            # Create CTWA data for this channel
            ctwa = create_test_ctwa(
                ctwa_clid="test_clid_456",
                channel_uuid=channel_without_dataset.uuid,
                waba="test_waba_456",
                contact_urn="whatsapp:5511888888888",
            )

            # Use the channel without dataset_id
            payload = self.valid_payload.copy()
            payload["channel_uuid"] = str(channel_without_dataset.uuid)
            payload["contact_urn"] = ctwa.contact_urn

            # Configure mock for successful Datalake send
            mock_send_event.return_value = None  # Successful send returns None

            with override_settings(WHATSAPP_ADMIN_SYSTEM_USER_TOKEN="test_token"):
                response = self.client.post(
                    self.endpoint_url,
                    data=json.dumps(payload),
                    content_type="application/json",
                )

                # Since we have CTWA data but no dataset_id, it should succeed with Datalake only
                self.assertEqual(response.status_code, 200)
                response_data = response.json()
                self.assertEqual(response_data["status"], "success")
                self.assertEqual(response_data["message"], "Event sent to Datalake successfully")

                # Verify Meta API was not called
                mock_post.assert_not_called()
                # Verify Datalake was called
                mock_send_event.assert_called_once()

    def test_get_channel_dataset_id_no_channel(self):
        """Test _get_channel_dataset_id when channel is not found"""
        # Create a view instance to test the method directly
        from temba.conversion_events.views import ConversionEventView

        view = ConversionEventView()

        # Test with non-existent channel UUID
        result = view._get_channel_dataset_id("non-existent-uuid")
        self.assertIsNone(result)

    def test_meta_dataset_id_not_configured(self):
        """Test handling when Meta dataset_id is not configured"""
        with patch("temba.conversion_events.views.requests.post") as mock_post, patch(
            "temba.conversion_events.views.send_event_data"
        ) as mock_send_event:

            # Configure mocks
            mock_send_event.return_value = None  # Successful Datalake send

            # Test the _send_to_meta method directly
            from temba.conversion_events.views import ConversionEventView

            view = ConversionEventView()

            with override_settings(WHATSAPP_ADMIN_SYSTEM_USER_TOKEN="test_token"):
                success, error = view._send_to_meta({}, None)  # dataset_id is None

                self.assertFalse(success)
                self.assertEqual(error, "Meta dataset ID not configured")
                mock_post.assert_not_called()

    def test_meta_network_error_direct(self):
        """Test _send_to_meta when network error occurs"""
        with patch("temba.conversion_events.views.requests.post") as mock_post:
            # Simulate a network error
            mock_post.side_effect = requests.RequestException("Network timeout")

            # Test the _send_to_meta method directly
            from temba.conversion_events.views import ConversionEventView

            view = ConversionEventView()

            with override_settings(WHATSAPP_ADMIN_SYSTEM_USER_TOKEN="test_token"):
                success, error = view._send_to_meta({}, "test_dataset")

                self.assertFalse(success)
                self.assertEqual(error, "Network error sending to Meta: Network timeout")

    def test_channel_and_org_not_found_direct(self):
        """Test _send_to_datalake when channel and org are not found"""
        # Test the _send_to_datalake method directly
        from temba.conversion_events.views import ConversionEventView

        view = ConversionEventView()

        # Test with non-existent channel
        success, error = view._send_to_datalake("lead", "non-existent-uuid", "whatsapp:1234567890", None, {})
        self.assertFalse(success)
        self.assertEqual(error, "Channel not found")

        # Test with non-existent org
        with patch("temba.channels.models.Channel.objects.filter") as mock_channel_filter:
            mock_channel = Mock()
            mock_channel.org_id = 999999  # Non-existent org ID
            mock_channel_filter.return_value.only.return_value.first.return_value = mock_channel

            success, error = view._send_to_datalake("lead", "some-uuid", "whatsapp:1234567890", None, {})
            self.assertFalse(success)
            self.assertEqual(error, "Organization not found")

    def test_org_lookup_exception_direct(self):
        """Test _send_to_datalake when org lookup raises an exception"""
        from temba.conversion_events.views import ConversionEventView

        view = ConversionEventView()

        with patch("temba.channels.models.Channel.objects.filter") as mock_channel_filter, patch(
            "temba.orgs.models.Org.objects.filter"
        ) as mock_org_filter:
            # Setup channel mock to return a valid channel
            mock_channel = Mock()
            mock_channel.org_id = 123
            mock_channel_filter.return_value.only.return_value.first.return_value = mock_channel

            # Setup org filter to raise an exception
            mock_org_filter.side_effect = Exception("Database error during org lookup")

            success, error = view._send_to_datalake("lead", "some-uuid", "whatsapp:1234567890", None, {})
            self.assertFalse(success)
            self.assertEqual(error, "Organization not found")

    def test_meta_failure_datalake_success(self):
        """Test when Meta fails but Datalake succeeds"""
        with patch("temba.conversion_events.views.requests.post") as mock_post, patch(
            "temba.conversion_events.views.send_event_data"
        ) as mock_send_event:
            # Configure Meta to fail
            mock_response = Mock()
            mock_response.status_code = 400
            mock_response.json.return_value = {"error": "Invalid request"}
            mock_post.return_value = mock_response

            # Configure Datalake to succeed
            mock_send_event.return_value = None

            # Set proj_uuid for the org
            self.org.proj_uuid = uuid4()
            self.org.save(update_fields=["proj_uuid"])

            # Use the valid payload that has CTWA data (from setUp)
            with override_settings(
                WHATSAPP_ADMIN_SYSTEM_USER_TOKEN="test_token",
                WHATSAPP_API_URL="https://graph.facebook.com/v18.0",
                META_PARTNER_AGENT="Weni by VTEX",
            ):
                # Make the request
                response = self.client.post(
                    self.endpoint_url,
                    data=json.dumps(self.valid_payload),
                    content_type="application/json",
                )

                # Should succeed overall since Datalake succeeded
                self.assertEqual(response.status_code, 200)
                response_data = response.json()
                self.assertEqual(response_data["status"], "success")
                self.assertEqual(response_data["message"], "Event sent to Datalake successfully")

                # Verify Meta API was called and failed
                mock_post.assert_called_once()
                call_args = mock_post.call_args
                self.assertIn("test_dataset_123", call_args[0][0])
                self.assertIn("access_token=test_token", call_args[0][0])

                # Verify Datalake was called and succeeded
                mock_send_event.assert_called_once()

    def test_successful_abandoned_cart_conversion(self):
        """Test successful abandoned_cart conversion with value and currency"""
        payload = self.valid_payload.copy()
        payload["event_type"] = "abandoned_cart"
        payload["payload"] = {
            "value": "249.90",
            "currency": "BRL",
            "cart_id": "cart_abc_123",
        }

        with patch("temba.conversion_events.views.requests.post") as mock_post, patch(
            "temba.conversion_events.views.send_event_data"
        ) as mock_send_event:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"success": True}
            mock_post.return_value = mock_response

            self.org.proj_uuid = uuid4()
            self.org.save(update_fields=["proj_uuid"])

            with override_settings(
                WHATSAPP_ADMIN_SYSTEM_USER_TOKEN="test_token",
                WHATSAPP_API_URL="https://graph.facebook.com/v18.0",
                META_PARTNER_AGENT="Weni by VTEX",
            ):
                response = self.client.post(
                    self.endpoint_url,
                    data=json.dumps(payload),
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 200)
                response_data = response.json()
                self.assertEqual(response_data["status"], "success")
                self.assertEqual(
                    response_data["message"],
                    "Event sent to Meta and Datalake successfully",
                )

                # Verify Meta API call
                mock_post.assert_called_once()
                meta_payload = mock_post.call_args[1]["json"]
                meta_event = meta_payload["data"][0]

                self.assertEqual(meta_event["event_name"], "AbandonedCart")
                self.assertEqual(meta_event["value"], 249.90)
                self.assertEqual(meta_event["currency"], "BRL")

                # Verify Datalake API call
                mock_send_event.assert_called_once()
                event_data = mock_send_event.call_args[0][1]
                self.assertEqual(event_data["event_name"], "conversion_abandoned_cart")
                self.assertEqual(event_data["key"], "capi")
                self.assertEqual(event_data["value"], "abandoned_cart")
                self.assertEqual(event_data["value_type"], "string")
                self.assertEqual(event_data["project"], str(self.org.proj_uuid))
                self.assertEqual(event_data["contact_urn"], self.valid_payload["contact_urn"])
                self.assertEqual(event_data["metadata"]["value"], "249.90")
                self.assertEqual(event_data["metadata"]["currency"], "BRL")
                self.assertEqual(event_data["metadata"]["cart_id"], "cart_abc_123")

    def test_abandoned_cart_conversion_without_ctwa(self):
        """Test abandoned_cart event is sent to Datalake only when no CTWA data exists"""
        with patch("temba.conversion_events.views.send_event_data") as mock_send_event:
            self.org.proj_uuid = uuid4()
            self.org.save(update_fields=["proj_uuid"])

            payload = self.valid_payload.copy()
            payload["event_type"] = "abandoned_cart"
            payload["contact_urn"] = "whatsapp:5511888888888"
            payload["payload"] = {"value": "99.99", "currency": "BRL"}

            response = self.client.post(
                self.endpoint_url,
                data=json.dumps(payload),
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 200)
            response_data = response.json()
            self.assertEqual(response_data["status"], "success")
            self.assertEqual(response_data["message"], "Event sent to Datalake successfully")

            mock_send_event.assert_called_once()
            event_data = mock_send_event.call_args[0][1]
            self.assertEqual(event_data["event_name"], "conversion_abandoned_cart")
            self.assertEqual(event_data["metadata"]["value"], "99.99")
            self.assertNotIn("ctwa_id", event_data["metadata"])

    def test_abandoned_cart_conversion_invalid_value(self):
        """Test abandoned_cart conversion with invalid value format"""
        payload = self.valid_payload.copy()
        payload["event_type"] = "abandoned_cart"
        payload["payload"] = {"value": "not_a_number", "currency": "BRL"}

        with patch("temba.conversion_events.views.requests.post") as mock_post, patch(
            "temba.conversion_events.views.send_event_data"
        ) as mock_send_event:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"success": True}
            mock_post.return_value = mock_response

            self.org.proj_uuid = uuid4()
            self.org.save(update_fields=["proj_uuid"])

            with override_settings(
                WHATSAPP_ADMIN_SYSTEM_USER_TOKEN="test_token",
                WHATSAPP_API_URL="https://graph.facebook.com/v18.0",
            ):
                response = self.client.post(
                    self.endpoint_url,
                    data=json.dumps(payload),
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 200)

                mock_post.assert_called_once()
                meta_event = mock_post.call_args[1]["json"]["data"][0]

                self.assertEqual(meta_event["event_name"], "AbandonedCart")
                self.assertNotIn("value", meta_event)
                self.assertNotIn("currency", meta_event)

                mock_send_event.assert_called_once()
                event_data = mock_send_event.call_args[0][1]
                self.assertEqual(event_data["metadata"]["value"], "not_a_number")
                self.assertEqual(event_data["metadata"]["currency"], "BRL")


class WhatsappUrnVariantsTest(TestCase):
    def test_brazilian_with_extra_nine(self):
        self.assertEqual(
            whatsapp_urn_variants("whatsapp:5511912345678"),
            ["whatsapp:5511912345678", "whatsapp:551112345678"],
        )

    def test_brazilian_without_extra_nine(self):
        self.assertEqual(
            whatsapp_urn_variants("whatsapp:551112345678"),
            ["whatsapp:551112345678", "whatsapp:5511912345678"],
        )

    def test_non_brazilian_whatsapp(self):
        self.assertEqual(whatsapp_urn_variants("whatsapp:14155551212"), ["whatsapp:14155551212"])

    def test_non_whatsapp(self):
        self.assertEqual(whatsapp_urn_variants("tel:+250781111111"), ["tel:+250781111111"])


class CTWAModelTest(TembaTest):
    """Test the CTWA model"""

    def setUp(self):
        super().setUp()

        self.channel = self.create_channel("WAC", "Test Channel", "1234567890")

    def test_ctwa_creation(self):
        """Test basic CTWA model creation and fields"""
        ctwa = create_test_ctwa(
            ctwa_clid="test_clid",
            channel_uuid=self.channel.uuid,
            waba="test_waba",
            contact_urn="whatsapp:1234567890",
        )

        self.assertEqual(ctwa.ctwa_clid, "test_clid")
        self.assertEqual(ctwa.channel_uuid, self.channel.uuid)
        self.assertEqual(ctwa.waba, "test_waba")
        self.assertEqual(ctwa.contact_urn, "whatsapp:1234567890")
        self.assertIsNotNone(ctwa.timestamp)
        self.assertIsNotNone(ctwa.referral_source)
        self.assertEqual(ctwa.referral_source.org, self.org)

    def test_ctwa_without_clid(self):
        ctwa = create_test_ctwa(
            ctwa_clid=None,
            channel_uuid=self.channel.uuid,
            waba="test_waba",
            contact_urn="whatsapp:9999999999",
        )
        self.assertIsNone(ctwa.ctwa_clid)
        self.assertEqual(str(ctwa), f"CTWA Data - CLID: no-clid, Channel: {self.channel.uuid}")

    def test_ctwa_str_method(self):
        """Test CTWA string representation"""
        ctwa = create_test_ctwa(
            ctwa_clid="test_clid",
            channel_uuid=self.channel.uuid,
            waba="test_waba",
            contact_urn="whatsapp:1234567890",
        )

        expected_str = f"CTWA Data - CLID: test_clid, Channel: {self.channel.uuid}"
        self.assertEqual(str(ctwa), expected_str)

    def test_ctwa_filtering_and_queries(self):
        """Test CTWA filtering capabilities"""
        # Create multiple CTWA records
        ctwa1 = create_test_ctwa(
            ctwa_clid="clid1",
            channel_uuid=self.channel.uuid,
            waba="waba1",
            contact_urn="whatsapp:1111111111",
        )
        ctwa2 = create_test_ctwa(
            ctwa_clid="clid2",
            channel_uuid=self.channel.uuid,
            waba="waba2",
            contact_urn="whatsapp:2222222222",
        )

        # Test filtering by channel_uuid
        channel_ctwas = CTWA.objects.filter(channel_uuid=self.channel.uuid)
        self.assertEqual(channel_ctwas.count(), 2)

        # Test filtering by contact_urn
        specific_ctwa = CTWA.objects.filter(contact_urn="whatsapp:1111111111").first()
        self.assertEqual(specific_ctwa, ctwa1)

        # Test combined filter (as used in the view)
        lookup_ctwa = CTWA.objects.filter(channel_uuid=self.channel.uuid, contact_urn="whatsapp:2222222222").first()
        self.assertEqual(lookup_ctwa, ctwa2)

    def test_whatsapp_urn_format_handling(self):
        """Test handling of WhatsApp URNs with and without extra 9 digit"""
        from temba.conversion_events.views import ConversionEventView

        view = ConversionEventView()

        # Create CTWA with number containing extra 9
        ctwa_with_9 = create_test_ctwa(
            ctwa_clid="clid_with_9",
            channel_uuid=self.channel.uuid,
            waba="waba_test",
            contact_urn="whatsapp:5511912345678",  # With extra 9
        )

        # Test finding CTWA when searching with the same format (with 9)
        result = view._get_ctwa_data(self.channel.uuid, "whatsapp:5511912345678")
        self.assertEqual(result, ctwa_with_9)

        # Test finding CTWA when searching without the 9
        result = view._get_ctwa_data(self.channel.uuid, "whatsapp:551112345678")
        self.assertEqual(result, ctwa_with_9)

        # Create CTWA with number without extra 9
        ctwa_without_9 = create_test_ctwa(
            ctwa_clid="clid_without_9",
            channel_uuid=self.channel.uuid,
            waba="waba_test2",
            contact_urn="whatsapp:551112345678",  # Without extra 9
        )

        # Test finding CTWA when searching with extra 9
        result = view._get_ctwa_data(self.channel.uuid, "whatsapp:5511912345678")
        # Should return the most recent one due to order_by("-timestamp")
        self.assertEqual(result, ctwa_without_9)

        # Test with non-WhatsApp URN (should use exact match)
        ctwa_other = create_test_ctwa(
            ctwa_clid="clid_other",
            channel_uuid=self.channel.uuid,
            waba="waba_test3",
            contact_urn="tel:1234567890",
        )

        result = view._get_ctwa_data(self.channel.uuid, "tel:1234567890")
        self.assertEqual(result, ctwa_other)

        # Test with invalid WhatsApp URN format
        result = view._get_ctwa_data(self.channel.uuid, "whatsapp:invalid")
        self.assertIsNone(result)

        # Test with empty URN
        result = view._get_ctwa_data(self.channel.uuid, "")
        self.assertIsNone(result)

    def test_latest_for_contact_returns_newest_event(self):
        contact = self.create_contact(name="WA", urns=["whatsapp:5511912345678"])
        create_test_ctwa(
            ctwa_clid="old-clid",
            channel_uuid=self.channel.uuid,
            waba="waba",
            contact_urn="whatsapp:5511912345678",
            timestamp=timezone.now() - timedelta(hours=1),
        )
        newer = create_test_ctwa(
            ctwa_clid="new-clid",
            channel_uuid=self.channel.uuid,
            waba="waba",
            contact_urn="whatsapp:5511912345678",
            timestamp=timezone.now(),
        )

        self.assertEqual(CTWA.objects.latest_for_contact(contact), newer)

    def test_latest_for_contact_matches_brazilian_urn_variant(self):
        contact = self.create_contact(name="WA", urns=["whatsapp:5511912345678"])
        ctwa = create_test_ctwa(
            ctwa_clid="br-clid",
            channel_uuid=self.channel.uuid,
            waba="waba",
            contact_urn="whatsapp:551112345678",
        )

        self.assertEqual(CTWA.objects.latest_for_contact(contact), ctwa)

    def test_latest_for_contact_returns_none_without_urns(self):
        contact = self.create_contact(name="No URN")
        self.assertIsNone(CTWA.objects.latest_for_contact(contact))

    def test_latest_for_contact_returns_none_without_channels(self):
        contact = self.create_contact(name="Org2", urns=["whatsapp:5511999999999"], org=self.org2)
        create_test_ctwa(
            org=self.org2,
            ctwa_clid="org2-clid",
            channel_uuid=uuid4(),
            waba="waba",
            contact_urn="whatsapp:5511999999999",
        )

        self.assertIsNone(CTWA.objects.latest_for_contact(contact))

    def test_latest_for_contact_does_not_return_other_org_event(self):
        contact = self.create_contact(name="WA", urns=["whatsapp:5511912345678"])
        channel2 = self.create_channel("WAC", "Org2 Channel", "9999999999", org=self.org2)
        create_test_ctwa(
            org=self.org2,
            ctwa_clid="other-org",
            channel_uuid=channel2.uuid,
            waba="waba",
            contact_urn="whatsapp:5511912345678",
        )

        self.assertIsNone(CTWA.objects.latest_for_contact(contact))


class CtwaDatalakeDualWriteTest(TembaTest):
    """Tests for dual-write to legacy and CTWA Datalake tables."""

    def setUp(self):
        super().setUp()
        self.jwt_auth_patcher = patch(
            "temba.conversion_events.jwt_auth.JWTModuleAuthentication.authenticate",
            return_value=(AnonymousUser(), None),
        )
        self.jwt_auth_patcher.start()
        self.addCleanup(self.jwt_auth_patcher.stop)
        self.activate_patcher = patch.object(WhatsAppCloudType, "activate", return_value=None)
        self.activate_patcher.start()
        self.addCleanup(self.activate_patcher.stop)
        self.channel = self.create_channel(
            "WAC",
            "Test WhatsApp Channel",
            "12065551212",
            country="US",
            config={"meta_dataset_id": "test_dataset_123", "wa_waba_id": "test_waba_123"},
        )
        self.org.proj_uuid = uuid4()
        self.org.save(update_fields=["proj_uuid"])
        self.endpoint_url = "/conversion/"
        self.ctwa_timestamp = datetime(2026, 1, 15, 12, 30, 0, tzinfo=dt_timezone.utc)
        self.ctwa_data = create_test_ctwa(
            ctwa_clid="test_clid_dual_write",
            channel_uuid=self.channel.uuid,
            waba="test_waba_123",
            contact_urn="whatsapp:5511999999999",
            message_id="wamid.dual.write",
            timestamp=self.ctwa_timestamp,
        )
        self.valid_payload = {
            "event_type": "lead",
            "channel_uuid": str(self.channel.uuid),
            "contact_urn": "whatsapp:5511999999999",
            "payload": {"custom_field": "custom_value"},
        }

    def test_dual_write_lead_with_complete_ctwa(self):
        with patch("temba.conversion_events.views.requests.post") as mock_post, patch(
            "temba.conversion_events.views.send_event_data"
        ) as mock_send_event, patch("temba.conversion_events.views.datetime") as mock_datetime:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"success": True}
            mock_post.return_value = mock_response
            mock_datetime.now.return_value = datetime(2023, 11, 14, 22, 13, 20, tzinfo=dt_timezone.utc)

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
            self.assertEqual(mock_send_event.call_count, 2)

            legacy_event = mock_send_event.call_args_list[0][0][1]
            ctwa_event = mock_send_event.call_args_list[1][0][1]

            self.assertEqual(legacy_event["event_name"], "conversion_lead")
            self.assertEqual(legacy_event["value"], "lead")
            self.assertEqual(legacy_event["date"], "2023-11-14T22:13:20Z")
            self.assertEqual(legacy_event["metadata"]["message_id"], "wamid.dual.write")

            self.assertEqual(ctwa_event["event_name"], "ctwa")
            self.assertEqual(ctwa_event["value"], "lead_qualified")
            self.assertEqual(ctwa_event["date"], "2026-01-15T12:30:00Z")
            self.assertEqual(ctwa_event["metadata"]["external_msg_id"], "wamid.dual.write")
            self.assertEqual(ctwa_event["metadata"]["campaign_source"], self.ctwa_data.referral_source.source_id)
            self.assertNotIn("referral_source_id", ctwa_event["metadata"])
            self.assertNotIn("message_id", ctwa_event["metadata"])

    def test_dual_write_purchase_includes_order_value(self):
        payload = self.valid_payload.copy()
        payload["event_type"] = "purchase"
        payload["payload"] = {"value": "456.78", "currency": "BRL"}

        with patch("temba.conversion_events.views.requests.post") as mock_post, patch(
            "temba.conversion_events.views.send_event_data"
        ) as mock_send_event:
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
                    data=json.dumps(payload),
                    content_type="application/json",
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(mock_send_event.call_count, 2)

            ctwa_event = mock_send_event.call_args_list[1][0][1]
            self.assertEqual(ctwa_event["value"], "purchase_completed")
            self.assertEqual(ctwa_event["metadata"]["order_value"], 456.78)

    def test_lead_without_ctwa_sends_legacy_only(self):
        payload = self.valid_payload.copy()
        payload["contact_urn"] = "whatsapp:5511888888888"

        with patch("temba.conversion_events.views.send_event_data") as mock_send_event:
            response = self.client.post(
                self.endpoint_url,
                data=json.dumps(payload),
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 200)
            mock_send_event.assert_called_once()
            event_data = mock_send_event.call_args[0][1]
            self.assertEqual(event_data["event_name"], "conversion_lead")
            self.assertNotIn("ctwa_id", event_data["metadata"])

    def test_ctwa_without_message_id_sends_legacy_only(self):
        create_test_ctwa(
            ctwa_clid="test_clid_no_message",
            channel_uuid=self.channel.uuid,
            waba="test_waba_123",
            contact_urn="whatsapp:5511777777777",
            message_id=None,
        )
        payload = self.valid_payload.copy()
        payload["contact_urn"] = "whatsapp:5511777777777"

        with patch("temba.conversion_events.views.send_event_data") as mock_send_event:
            response = self.client.post(
                self.endpoint_url,
                data=json.dumps(payload),
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 200)
            mock_send_event.assert_called_once()
            event_data = mock_send_event.call_args[0][1]
            self.assertEqual(event_data["event_name"], "conversion_lead")

    def test_ctwa_datalake_failure_does_not_fail_request(self):
        with patch("temba.conversion_events.views.requests.post") as mock_post, patch(
            "temba.conversion_events.views.send_event_data"
        ) as mock_send_event:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"success": True}
            mock_post.return_value = mock_response
            mock_send_event.side_effect = [None, Exception("CTWA table unavailable")]

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
            self.assertEqual(mock_send_event.call_count, 2)

    def test_dual_write_conversation_started(self):
        payload = {
            "event_type": "conversation_started",
            "channel_uuid": str(self.channel.uuid),
            "contact_urn": "whatsapp:5511999999999",
            "payload": {},
        }

        with patch("temba.conversion_events.views.send_event_data") as mock_send_event, patch(
            "temba.conversion_events.views.datetime"
        ) as mock_datetime:
            mock_datetime.now.return_value = datetime(2023, 11, 14, 22, 13, 20, tzinfo=dt_timezone.utc)

            response = self.client.post(
                self.endpoint_url,
                data=json.dumps(payload),
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(mock_send_event.call_count, 2)

            legacy_event = mock_send_event.call_args_list[0][0][1]
            ctwa_event = mock_send_event.call_args_list[1][0][1]

            self.assertEqual(legacy_event["event_name"], "conversion_conversation_started")
            self.assertEqual(legacy_event["date"], "2023-11-14T22:13:20Z")
            self.assertEqual(ctwa_event["event_name"], "ctwa")
            self.assertEqual(ctwa_event["value"], "conversation_started")
            self.assertEqual(ctwa_event["date"], "2026-01-15T12:30:00Z")


class ConversationStartedConversionEventAPITest(TembaTest):
    """Tests for conversation_started events triggered by Courier fixed token auth"""

    def setUp(self):
        super().setUp()
        self.activate_patcher = patch.object(WhatsAppCloudType, "activate", return_value=None)
        self.activate_patcher.start()
        self.addCleanup(self.activate_patcher.stop)
        self.channel = self.create_channel(
            "WAC",
            "Test WhatsApp Channel",
            "12065551212",
            country="US",
            config={"meta_dataset_id": "test_dataset_123", "wa_waba_id": "test_waba_123"},
        )
        self.ctwa_data = create_test_ctwa(
            ctwa_clid="test_clid_conv_started",
            channel_uuid=self.channel.uuid,
            waba="test_waba_123",
            contact_urn="whatsapp:5511999999999",
        )
        self.org.proj_uuid = uuid4()
        self.org.save(update_fields=["proj_uuid"])
        self.endpoint_url = "/conversion/"
        self.courier_token = "courier-test-token"

    def test_conversation_started_with_courier_token_sends_datalake_only(self):
        payload = {
            "event_type": "conversation_started",
            "channel_uuid": str(self.channel.uuid),
            "contact_urn": "whatsapp:5511999999999",
            "payload": {
                "message_id": "wamid.test",
                "source_id": "ad_source_1",
                "source_type": "ad",
            },
        }

        with patch("temba.conversion_events.views.requests.post") as mock_post, patch(
            "temba.conversion_events.views.send_event_data"
        ) as mock_send_event, override_settings(COURIER_FIXED_ACCESS_TOKEN=self.courier_token):
            response = self.client.post(
                f"{self.endpoint_url}?token={self.courier_token}",
                data=json.dumps(payload),
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 200)
            response_data = response.json()
            self.assertEqual(response_data["status"], "success")
            self.assertEqual(response_data["message"], "Event sent to Datalake successfully")

            mock_post.assert_not_called()
            mock_send_event.assert_called_once()
            event_data = mock_send_event.call_args[0][1]
            self.assertEqual(event_data["event_name"], "conversion_conversation_started")
            self.assertEqual(event_data["value"], "conversation_started")
            self.assertEqual(event_data["metadata"]["ctwa_id"], "test_clid_conv_started")
            self.assertEqual(event_data["metadata"]["message_id"], "wamid.test")
            self.assertEqual(event_data["metadata"]["referral_source_id"], self.ctwa_data.referral_source.source_id)

    def test_courier_token_rejects_lead_event(self):
        payload = {
            "event_type": "lead",
            "channel_uuid": str(self.channel.uuid),
            "contact_urn": "whatsapp:5511999999999",
            "payload": {},
        }

        with override_settings(COURIER_FIXED_ACCESS_TOKEN=self.courier_token):
            response = self.client.post(
                f"{self.endpoint_url}?token={self.courier_token}",
                data=json.dumps(payload),
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["error"], "Forbidden")

    def test_courier_token_invalid(self):
        payload = {
            "event_type": "conversation_started",
            "channel_uuid": str(self.channel.uuid),
            "contact_urn": "whatsapp:5511999999999",
            "payload": {},
        }

        with override_settings(COURIER_FIXED_ACCESS_TOKEN=self.courier_token):
            response = self.client.post(
                f"{self.endpoint_url}?token=wrong-token",
                data=json.dumps(payload),
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 403)


class JWTModuleAuthenticationTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.auth = JWTModuleAuthentication()
        self.mock_public_key = (
            "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...\n-----END PUBLIC KEY-----"
        )
        self.sample_payload = {
            "project_uuid": "test-project-123",
            "exp": 9999999999,
        }

    @patch("temba.conversion_events.jwt_auth.settings")
    def test_authenticate_missing_public_key(self, mock_settings):
        mock_settings.JWT_PUBLIC_KEY = None
        request = self.factory.get("/")
        request.headers = {}
        with self.assertRaises(AuthenticationFailed) as context:
            self.auth.authenticate(request)
        self.assertIn("JWT_PUBLIC_KEY not configured", str(context.exception))

    def test_authenticate_missing_authorization_header(self):
        with patch("temba.conversion_events.jwt_auth.settings") as mock_settings:
            mock_settings.JWT_PUBLIC_KEY = self.mock_public_key
            request = self.factory.get("/")
            request.headers = {}
            with self.assertRaises(AuthenticationFailed) as context:
                self.auth.authenticate(request)
            self.assertIn("Missing or invalid Authorization header", str(context.exception))

    def test_authenticate_invalid_authorization_header(self):
        with patch("temba.conversion_events.jwt_auth.settings") as mock_settings:
            mock_settings.JWT_PUBLIC_KEY = self.mock_public_key
            request = self.factory.get("/")
            request.headers = {"Authorization": "InvalidFormat"}
            with self.assertRaises(AuthenticationFailed) as context:
                self.auth.authenticate(request)
            self.assertIn("Missing or invalid Authorization header", str(context.exception))

    @patch("temba.conversion_events.jwt_auth.jwt.decode")
    @patch("temba.conversion_events.jwt_auth.settings")
    def test_authenticate_missing_project_uuid(self, mock_settings, mock_jwt_decode):
        mock_settings.JWT_PUBLIC_KEY = self.mock_public_key
        mock_jwt_decode.return_value = {"some_other_field": "value"}
        request = self.factory.get("/")
        request.headers = {"Authorization": "Bearer valid-token"}
        with self.assertRaises(AuthenticationFailed) as context:
            self.auth.authenticate(request)
        self.assertIn(
            "project_uuid or channel_uuid must be present in token payload.",
            str(context.exception),
        )

    @patch("temba.conversion_events.jwt_auth.jwt.decode")
    @patch("temba.conversion_events.jwt_auth.settings")
    def test_authenticate_success(self, mock_settings, mock_jwt_decode):
        mock_settings.JWT_PUBLIC_KEY = self.mock_public_key
        mock_jwt_decode.return_value = self.sample_payload
        request = self.factory.get("/")
        request.headers = {"Authorization": "Bearer valid-token"}
        result = self.auth.authenticate(request)
        from django.contrib.auth.models import AnonymousUser

        self.assertEqual(result, (AnonymousUser(), None))
        self.assertEqual(request.project_uuid, "test-project-123")
        self.assertEqual(request.jwt_payload, self.sample_payload)

    @patch("temba.conversion_events.jwt_auth.jwt.decode")
    @patch("temba.conversion_events.jwt_auth.settings")
    def test_authenticate_expired_token(self, mock_settings, mock_jwt_decode):
        mock_settings.JWT_PUBLIC_KEY = self.mock_public_key
        mock_jwt_decode.side_effect = jwt.ExpiredSignatureError("Token expired")
        request = self.factory.get("/")
        request.headers = {"Authorization": "Bearer expired-token"}
        with self.assertRaises(AuthenticationFailed) as context:
            self.auth.authenticate(request)
        self.assertIn("Token expired", str(context.exception))

    @patch("temba.conversion_events.jwt_auth.jwt.decode")
    @patch("temba.conversion_events.jwt_auth.settings")
    def test_authenticate_invalid_token(self, mock_settings, mock_jwt_decode):
        mock_settings.JWT_PUBLIC_KEY = self.mock_public_key
        mock_jwt_decode.side_effect = jwt.InvalidTokenError("Invalid token")
        request = self.factory.get("/")
        request.headers = {"Authorization": "Bearer invalid-token"}
        with self.assertRaises(AuthenticationFailed) as context:
            self.auth.authenticate(request)
        self.assertIn("Invalid token", str(context.exception))

    def test_authenticate_verify_jwt_decode_called_correctly(self):
        with patch("temba.conversion_events.jwt_auth.jwt.decode") as mock_jwt_decode, patch(
            "temba.conversion_events.jwt_auth.settings"
        ) as mock_settings:
            mock_settings.JWT_PUBLIC_KEY = self.mock_public_key
            mock_jwt_decode.return_value = self.sample_payload
            request = self.factory.get("/")
            request.headers = {"Authorization": "Bearer test-token"}
            self.auth.authenticate(request)
            mock_jwt_decode.assert_called_once_with(
                "test-token",
                self.mock_public_key,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )


class DummyView(JWTModuleAuthMixin):
    def __init__(self, request):
        self.request = request


class JWTModuleAuthMixinTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def test_project_uuid_property(self):
        request = self.factory.get("/")
        request.project_uuid = "uuid-123"
        view = DummyView(request)
        self.assertEqual(view.project_uuid, "uuid-123")

    def test_jwt_payload_property(self):
        request = self.factory.get("/")
        request.jwt_payload = {"foo": "bar"}
        view = DummyView(request)
        self.assertEqual(view.jwt_payload, {"foo": "bar"})

    def test_project_uuid_property_none(self):
        request = self.factory.get("/")
        view = DummyView(request)
        self.assertIsNone(view.project_uuid)

    def test_jwt_payload_property_none(self):
        request = self.factory.get("/")
        view = DummyView(request)
        self.assertIsNone(view.jwt_payload)


class CtwaReferralSourceModelTest(TembaTest):
    def test_create_without_org_raises_integrity_error(self):
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                CtwaReferralSource.objects.create(
                    source_id="no-org",
                    source_type=CtwaReferralSource.SOURCE_TYPE_AD,
                )

    def test_get_or_create_for_org_requires_org(self):
        with self.assertRaises(ValueError):
            CtwaReferralSource.get_or_create_for_org(None, "ad-1", CtwaReferralSource.SOURCE_TYPE_AD)

    def test_same_source_allowed_for_different_orgs(self):
        source_id = "shared-ad"
        source_a, created_a = CtwaReferralSource.get_or_create_for_org(
            self.org, source_id, CtwaReferralSource.SOURCE_TYPE_AD
        )
        source_b, created_b = CtwaReferralSource.get_or_create_for_org(
            self.org2, source_id, CtwaReferralSource.SOURCE_TYPE_AD
        )

        self.assertTrue(created_a)
        self.assertTrue(created_b)
        self.assertNotEqual(source_a.id, source_b.id)
        self.assertEqual(source_a.source_id, source_b.source_id)
        self.assertEqual(source_a.org, self.org)
        self.assertEqual(source_b.org, self.org2)

    def test_same_org_source_id_and_type_is_rejected(self):
        source_id = "dup-ad"
        CtwaReferralSource.get_or_create_for_org(self.org, source_id, CtwaReferralSource.SOURCE_TYPE_AD)

        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                CtwaReferralSource.objects.create(
                    org=self.org,
                    source_id=source_id,
                    source_type=CtwaReferralSource.SOURCE_TYPE_AD,
                )

    def test_get_or_create_for_org_returns_existing(self):
        source, created = CtwaReferralSource.get_or_create_for_org(
            self.org, "existing-ad", CtwaReferralSource.SOURCE_TYPE_POST
        )
        again, created_again = CtwaReferralSource.get_or_create_for_org(
            self.org, "existing-ad", CtwaReferralSource.SOURCE_TYPE_POST
        )

        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(source.id, again.id)


class CtwaReferralSourceBackfillTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.channel = self.create_channel("WAC", "Org1 Channel", "1111111111")
        self.channel2 = self.create_channel("WAC", "Org2 Channel", "2222222222", org=self.org2)

    def _null_org_standin(self, source):
        return SimpleNamespace(
            id=source.id,
            org_id=None,
            source_id=source.source_id,
            source_type=source.source_type,
            source_url=source.source_url,
            headline=source.headline,
            body=source.body,
        )

    def test_null_org_source_is_assigned_from_ctwa_channel(self):
        source, _ = CtwaReferralSource.get_or_create_for_org(
            self.org2, "ad-from-channel", CtwaReferralSource.SOURCE_TYPE_AD
        )
        create_test_ctwa(
            ctwa_clid="clid-inherit",
            channel_uuid=self.channel.uuid,
            waba="waba",
            contact_urn="whatsapp:1111111111",
            referral_source=source,
        )

        org_map = org_channels_by_source_id([source.id], CTWA, Channel)
        self.assertEqual(list(org_map[source.id]), [self.org.id])

        apply_orgs_to_source(self._null_org_standin(source), org_map[source.id], CtwaReferralSource, CTWA)
        source.refresh_from_db()
        self.assertEqual(source.org_id, self.org.id)

    def test_shared_source_is_cloned_and_ctwas_retargeted(self):
        source, _ = CtwaReferralSource.get_or_create_for_org(
            self.org, "shared-ad", CtwaReferralSource.SOURCE_TYPE_AD, headline="Hello"
        )
        ctwa_org1 = create_test_ctwa(
            ctwa_clid="clid-org1",
            channel_uuid=self.channel.uuid,
            waba="waba1",
            contact_urn="whatsapp:1111111111",
            referral_source=source,
        )
        ctwa_org2 = create_test_ctwa(
            ctwa_clid="clid-org2",
            channel_uuid=self.channel2.uuid,
            waba="waba2",
            contact_urn="whatsapp:2222222222",
            referral_source=source,
        )

        org_map = org_channels_by_source_id([source.id], CTWA, Channel)
        self.assertEqual(set(org_map[source.id]), {self.org.id, self.org2.id})

        apply_orgs_to_source(source, org_map[source.id], CtwaReferralSource, CTWA)

        source.refresh_from_db()
        ctwa_org1.refresh_from_db()
        ctwa_org2.refresh_from_db()

        clone = CtwaReferralSource.objects.exclude(id=source.id).get(
            source_id="shared-ad", source_type=CtwaReferralSource.SOURCE_TYPE_AD
        )
        self.assertEqual(source.org_id, self.org.id)
        self.assertEqual(clone.org_id, self.org2.id)
        self.assertEqual(clone.headline, "Hello")
        self.assertEqual(ctwa_org1.referral_source_id, source.id)
        self.assertEqual(ctwa_org2.referral_source_id, clone.id)

    def test_existing_org_is_preserved_when_ctwas_resolve_to_a_different_org(self):
        source, _ = CtwaReferralSource.get_or_create_for_org(
            self.org, "mismatch-ad", CtwaReferralSource.SOURCE_TYPE_AD
        )
        ctwa = create_test_ctwa(
            ctwa_clid="clid-mismatch",
            channel_uuid=self.channel2.uuid,
            waba="waba2",
            contact_urn="whatsapp:2222222222",
            referral_source=source,
        )

        with patch.object(_backfill.logger, "warning") as mock_warning:
            backfill_ctwa_referral_source_org(CtwaReferralSource, CTWA, Channel, source_ids=[source.id])

        mock_warning.assert_called_once()
        warning = mock_warning.call_args[0][0]
        self.assertIn(f"id={source.id}", warning)
        self.assertIn(f"org_id={self.org.id}", warning)

        source.refresh_from_db()
        ctwa.refresh_from_db()
        clone = CtwaReferralSource.objects.exclude(id=source.id).get(
            source_id="mismatch-ad", source_type=CtwaReferralSource.SOURCE_TYPE_AD
        )
        self.assertEqual(source.org_id, self.org.id)
        self.assertEqual(clone.org_id, self.org2.id)
        self.assertEqual(ctwa.referral_source_id, clone.id)

    def test_apply_orgs_to_source_does_not_query_channels(self):
        source, _ = CtwaReferralSource.get_or_create_for_org(
            self.org, "no-channel-query-ad", CtwaReferralSource.SOURCE_TYPE_AD
        )
        create_test_ctwa(
            ctwa_clid="clid-no-channel-query",
            channel_uuid=self.channel2.uuid,
            waba="waba2",
            contact_urn="whatsapp:2222222222",
            referral_source=source,
        )
        org_map = org_channels_by_source_id([source.id], CTWA, Channel)

        with CaptureQueriesContext(connection) as captured:
            apply_orgs_to_source(source, org_map[source.id], CtwaReferralSource, CTWA)

        channel_queries = [query["sql"] for query in captured.captured_queries if "channels_channel" in query["sql"]]
        self.assertEqual(channel_queries, [])

    def test_backfill_processes_sources_and_clones_shared_orgs(self):
        source, _ = CtwaReferralSource.get_or_create_for_org(self.org, "batched-ad", CtwaReferralSource.SOURCE_TYPE_AD)
        create_test_ctwa(
            ctwa_clid="clid-batch-1",
            channel_uuid=self.channel.uuid,
            waba="waba1",
            contact_urn="whatsapp:1111111111",
            referral_source=source,
        )
        create_test_ctwa(
            ctwa_clid="clid-batch-2",
            channel_uuid=self.channel2.uuid,
            waba="waba2",
            contact_urn="whatsapp:2222222222",
            referral_source=source,
        )

        backfill_ctwa_referral_source_org(CtwaReferralSource, CTWA, Channel, source_ids=[source.id])

        self.assertEqual(
            CtwaReferralSource.objects.filter(source_id="batched-ad").count(),
            2,
        )
        self.assertEqual(
            set(CtwaReferralSource.objects.filter(source_id="batched-ad").values_list("org_id", flat=True)),
            {self.org.id, self.org2.id},
        )

    def test_backfill_logs_when_org_cannot_be_resolved(self):
        source, _ = CtwaReferralSource.get_or_create_for_org(
            self.org, f"orphan-ad-{uuid4()}", CtwaReferralSource.SOURCE_TYPE_AD
        )

        with patch.object(_backfill.logger, "warning") as mock_warning:
            backfill_ctwa_referral_source_org(CtwaReferralSource, CTWA, Channel, source_ids=[source.id])

        mock_warning.assert_called_once()
        self.assertIn(f"id={source.id}", mock_warning.call_args[0][0])
        source.refresh_from_db()
        self.assertEqual(source.org_id, self.org.id)
        self.assertTrue(CtwaReferralSource.objects.filter(id=source.id).exists())

    def test_backfill_is_noop_when_all_sources_have_org(self):
        CtwaReferralSource.get_or_create_for_org(self.org, "has-org", CtwaReferralSource.SOURCE_TYPE_AD)
        backfill_ctwa_referral_source_org(CtwaReferralSource, CTWA, Channel)
        self.assertEqual(
            CtwaReferralSource.objects.filter(source_id="has-org", org=self.org).count(),
            1,
        )

    def test_org_channels_by_source_id_returns_empty_for_no_ids(self):
        self.assertEqual(org_channels_by_source_id([], CTWA, Channel), {})

    def test_apply_orgs_to_source_skips_empty_org_ids(self):
        source, _ = CtwaReferralSource.get_or_create_for_org(
            self.org, "unchanged-ad", CtwaReferralSource.SOURCE_TYPE_AD
        )
        apply_orgs_to_source(source, {}, CtwaReferralSource, CTWA)
        source.refresh_from_db()
        self.assertEqual(source.org_id, self.org.id)

    def test_resolve_batch_orgs_reports_unresolved_null_org_sources(self):
        source, _ = CtwaReferralSource.get_or_create_for_org(
            self.org, "unresolved-null-org", CtwaReferralSource.SOURCE_TYPE_AD
        )
        standin = self._null_org_standin(source)

        with patch.object(_backfill.logger, "warning") as mock_warning:
            unresolved_ids = resolve_batch_orgs([standin], {}, CtwaReferralSource, CTWA)

        self.assertEqual(unresolved_ids, [source.id])
        mock_warning.assert_called_once()
        self.assertIn(f"id={source.id}", mock_warning.call_args[0][0])

    def test_delete_unresolved_sources_removes_source_and_its_ctwas(self):
        source, _ = CtwaReferralSource.get_or_create_for_org(
            self.org, "deletable-ad", CtwaReferralSource.SOURCE_TYPE_AD
        )
        ctwa = create_test_ctwa(
            ctwa_clid="clid-deletable",
            channel_uuid=self.channel.uuid,
            waba="waba",
            contact_urn="whatsapp:1111111111",
            referral_source=source,
        )

        delete_unresolved_sources([source.id], CtwaReferralSource, CTWA)

        self.assertFalse(CtwaReferralSource.objects.filter(id=source.id).exists())
        self.assertFalse(CTWA.objects.filter(id=ctwa.id).exists())

    def test_forwards_loads_models_and_runs_backfill(self):
        apps = Mock()
        models = {
            ("conversion_events", "CtwaReferralSource"): CtwaReferralSource,
            ("conversion_events", "CTWA"): CTWA,
            ("channels", "Channel"): Channel,
        }
        apps.get_model.side_effect = lambda app, model: models[(app, model)]

        with patch.object(_backfill, "backfill_ctwa_referral_source_org") as mock_backfill:
            _backfill.forwards(apps, schema_editor=None)

        mock_backfill.assert_called_once_with(CtwaReferralSource, CTWA, Channel)


class CtwaReferralSourceCollapseTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.channel = self.create_channel("WAC", "Org1 Channel", "1111111111")
        self.channel2 = self.create_channel("WAC", "Org2 Channel", "2222222222", org=self.org2)

    def _create_legacy_source(self, org, ctwa_id, first_seen_at=None, last_seen_at=None):
        source = CtwaReferralSource.objects.create(
            org=org,
            source_id=f"legacy-{ctwa_id}",
            source_type=CtwaReferralSource.SOURCE_TYPE_AD,
        )
        updates = {}
        if first_seen_at is not None:
            updates["first_seen_at"] = first_seen_at
        if last_seen_at is not None:
            updates["last_seen_at"] = last_seen_at
        if updates:
            CtwaReferralSource.objects.filter(id=source.id).update(**updates)
            source.refresh_from_db()
        return source

    def _create_legacy_ctwa(self, *, org, channel, ctwa_id, clid):
        source = self._create_legacy_source(org, ctwa_id)
        ctwa = create_test_ctwa(
            ctwa_clid=clid,
            channel_uuid=channel.uuid,
            waba="waba",
            contact_urn="whatsapp:1111111111",
            referral_source=source,
        )
        return source, ctwa

    def test_collapse_merges_legacy_sources_in_one_org(self):
        source_a, ctwa_a = self._create_legacy_ctwa(org=self.org, channel=self.channel, ctwa_id=11, clid="clid-a")
        source_b, ctwa_b = self._create_legacy_ctwa(org=self.org, channel=self.channel, ctwa_id=12, clid="clid-b")

        collapse_legacy_sources_per_org(CtwaReferralSource, CTWA)

        canonical = CtwaReferralSource.objects.get(
            org=self.org, source_id="legacy", source_type=CtwaReferralSource.SOURCE_TYPE_AD
        )
        ctwa_a.refresh_from_db()
        ctwa_b.refresh_from_db()

        self.assertEqual(ctwa_a.referral_source_id, canonical.id)
        self.assertEqual(ctwa_b.referral_source_id, canonical.id)
        self.assertFalse(CtwaReferralSource.objects.filter(id__in=[source_a.id, source_b.id]).exists())
        self.assertEqual(
            CtwaReferralSource.objects.filter(org=self.org, source_id="legacy").count(),
            1,
        )

    def test_collapse_keeps_a_canonical_source_per_org(self):
        _, ctwa_org1 = self._create_legacy_ctwa(org=self.org, channel=self.channel, ctwa_id=21, clid="clid-org1")
        _, ctwa_org2 = self._create_legacy_ctwa(org=self.org2, channel=self.channel2, ctwa_id=22, clid="clid-org2")

        collapse_legacy_sources_per_org(CtwaReferralSource, CTWA)

        canonical_org1 = CtwaReferralSource.objects.get(org=self.org, source_id="legacy")
        canonical_org2 = CtwaReferralSource.objects.get(org=self.org2, source_id="legacy")
        ctwa_org1.refresh_from_db()
        ctwa_org2.refresh_from_db()

        self.assertNotEqual(canonical_org1.id, canonical_org2.id)
        self.assertEqual(ctwa_org1.referral_source_id, canonical_org1.id)
        self.assertEqual(ctwa_org2.referral_source_id, canonical_org2.id)

    def test_collapse_leaves_non_legacy_and_near_miss_sources(self):
        real, _ = CtwaReferralSource.get_or_create_for_org(self.org, "real-ad-123", CtwaReferralSource.SOURCE_TYPE_AD)
        near_miss, _ = CtwaReferralSource.get_or_create_for_org(
            self.org, "legacy-abc", CtwaReferralSource.SOURCE_TYPE_AD
        )
        post_legacy, _ = CtwaReferralSource.get_or_create_for_org(
            self.org, "legacy-99", CtwaReferralSource.SOURCE_TYPE_POST
        )
        self._create_legacy_ctwa(org=self.org, channel=self.channel, ctwa_id=31, clid="clid-keep")

        collapse_legacy_sources_per_org(CtwaReferralSource, CTWA)

        self.assertTrue(CtwaReferralSource.objects.filter(id=real.id).exists())
        self.assertTrue(CtwaReferralSource.objects.filter(id=near_miss.id).exists())
        self.assertTrue(CtwaReferralSource.objects.filter(id=post_legacy.id).exists())
        self.assertTrue(CtwaReferralSource.objects.filter(org=self.org, source_id="legacy", source_type="ad").exists())

    def test_canonical_inherits_earliest_first_seen_and_latest_last_seen(self):
        early = timezone.now() - timedelta(days=10)
        middle = timezone.now() - timedelta(days=5)
        late = timezone.now() - timedelta(days=1)

        source_early = self._create_legacy_source(self.org, 41, first_seen_at=early, last_seen_at=middle)
        source_late = self._create_legacy_source(self.org, 42, first_seen_at=middle, last_seen_at=late)
        create_test_ctwa(
            ctwa_clid="clid-window-early",
            channel_uuid=self.channel.uuid,
            waba="waba",
            contact_urn="whatsapp:1111111111",
            referral_source=source_early,
        )
        create_test_ctwa(
            ctwa_clid="clid-window-late",
            channel_uuid=self.channel.uuid,
            waba="waba",
            contact_urn="whatsapp:1111111111",
            referral_source=source_late,
        )

        collapse_legacy_sources_per_org(CtwaReferralSource, CTWA)

        canonical = CtwaReferralSource.objects.get(org=self.org, source_id="legacy")
        self.assertEqual(canonical.first_seen_at, early)
        self.assertEqual(canonical.last_seen_at, late)

    def test_collapse_merges_window_into_existing_canonical(self):
        existing_first = timezone.now() - timedelta(days=20)
        existing_last = timezone.now() - timedelta(days=8)
        leftover_first = timezone.now() - timedelta(days=3)
        leftover_last = timezone.now() - timedelta(days=1)

        canonical, _ = CtwaReferralSource.get_or_create_for_org(self.org, "legacy", CtwaReferralSource.SOURCE_TYPE_AD)
        CtwaReferralSource.objects.filter(id=canonical.id).update(
            first_seen_at=existing_first, last_seen_at=existing_last
        )

        leftover = self._create_legacy_source(self.org, 51, first_seen_at=leftover_first, last_seen_at=leftover_last)
        create_test_ctwa(
            ctwa_clid="clid-existing-canonical",
            channel_uuid=self.channel.uuid,
            waba="waba",
            contact_urn="whatsapp:1111111111",
            referral_source=leftover,
        )

        collapse_legacy_sources_per_org(CtwaReferralSource, CTWA, org_ids=[self.org.id])

        canonical.refresh_from_db()
        self.assertEqual(canonical.first_seen_at, existing_first)
        self.assertEqual(canonical.last_seen_at, leftover_last)

    def test_collapse_is_idempotent(self):
        _, ctwa = self._create_legacy_ctwa(org=self.org, channel=self.channel, ctwa_id=61, clid="clid-once")

        collapse_legacy_sources_per_org(CtwaReferralSource, CTWA)
        canonical_id = CtwaReferralSource.objects.get(org=self.org, source_id="legacy").id
        collapse_legacy_sources_per_org(CtwaReferralSource, CTWA)

        ctwa.refresh_from_db()
        self.assertEqual(
            CtwaReferralSource.objects.filter(org=self.org, source_id="legacy").count(),
            1,
        )
        self.assertEqual(ctwa.referral_source_id, canonical_id)

    def test_collapse_with_batch_size_one_processes_all_chunks(self):
        created = [
            self._create_legacy_ctwa(org=self.org, channel=self.channel, ctwa_id=ctwa_id, clid=f"clid-batch-{ctwa_id}")
            for ctwa_id in (71, 72, 73)
        ]

        collapse_legacy_sources_per_org(CtwaReferralSource, CTWA, batch_size=1)

        canonical = CtwaReferralSource.objects.get(org=self.org, source_id="legacy")
        for source, ctwa in created:
            ctwa.refresh_from_db()
            self.assertEqual(ctwa.referral_source_id, canonical.id)
            self.assertFalse(CtwaReferralSource.objects.filter(id=source.id).exists())

    def test_collapse_skips_org_without_legacy_sources(self):
        collapse_org_legacy_sources(self.org.id, CtwaReferralSource, CTWA, batch_size=1000)
        self.assertFalse(CtwaReferralSource.objects.filter(org=self.org, source_id="legacy").exists())

    def test_org_ids_narrowing_collapses_only_the_requested_org(self):
        self._create_legacy_ctwa(org=self.org, channel=self.channel, ctwa_id=81, clid="clid-narrow-1")
        source_org2, _ = self._create_legacy_ctwa(
            org=self.org2, channel=self.channel2, ctwa_id=82, clid="clid-narrow-2"
        )

        collapse_legacy_sources_per_org(CtwaReferralSource, CTWA, org_ids=[self.org.id])

        self.assertTrue(CtwaReferralSource.objects.filter(org=self.org, source_id="legacy").exists())
        self.assertTrue(CtwaReferralSource.objects.filter(id=source_org2.id).exists())
        self.assertFalse(CtwaReferralSource.objects.filter(org=self.org2, source_id="legacy").exists())

    def test_preserve_seen_window_skips_when_both_values_are_none(self):
        canonical, _ = CtwaReferralSource.get_or_create_for_org(self.org, "legacy", CtwaReferralSource.SOURCE_TYPE_AD)
        original_first = canonical.first_seen_at
        original_last = canonical.last_seen_at

        preserve_seen_window(canonical.id, None, None, CtwaReferralSource)

        canonical.refresh_from_db()
        self.assertEqual(canonical.first_seen_at, original_first)
        self.assertEqual(canonical.last_seen_at, original_last)

    def test_preserve_seen_window_updates_only_provided_fields(self):
        canonical, _ = CtwaReferralSource.get_or_create_for_org(self.org, "legacy", CtwaReferralSource.SOURCE_TYPE_AD)
        original_last = canonical.last_seen_at
        new_first = timezone.now() - timedelta(days=15)

        preserve_seen_window(canonical.id, new_first, None, CtwaReferralSource)

        canonical.refresh_from_db()
        self.assertEqual(canonical.first_seen_at, new_first)
        self.assertEqual(canonical.last_seen_at, original_last)

    def test_merged_seen_window_picks_earliest_first_and_latest_last(self):
        earlier = timezone.now() - timedelta(days=10)
        later = timezone.now() - timedelta(days=1)
        canonical = SimpleNamespace(first_seen_at=earlier, last_seen_at=later)

        first_seen_at, last_seen_at = _collapse._merged_seen_window(canonical, later, earlier)

        self.assertEqual(first_seen_at, earlier)
        self.assertEqual(last_seen_at, later)

    def test_merged_seen_window_keeps_aggregated_values_when_canonical_has_none(self):
        stamp = timezone.now() - timedelta(days=2)
        canonical = SimpleNamespace(first_seen_at=None, last_seen_at=None)

        first_seen_at, last_seen_at = _collapse._merged_seen_window(canonical, stamp, stamp)

        self.assertEqual(first_seen_at, stamp)
        self.assertEqual(last_seen_at, stamp)

    def test_merged_seen_window_uses_canonical_when_aggregated_is_none(self):
        stamp = timezone.now() - timedelta(days=2)
        canonical = SimpleNamespace(first_seen_at=stamp, last_seen_at=stamp)

        first_seen_at, last_seen_at = _collapse._merged_seen_window(canonical, None, None)

        self.assertEqual(first_seen_at, stamp)
        self.assertEqual(last_seen_at, stamp)

    def test_org_ids_with_legacy_sources_returns_distinct_orgs(self):
        self._create_legacy_source(self.org, 91)
        self._create_legacy_source(self.org, 92)
        self._create_legacy_source(self.org2, 93)

        self.assertEqual(org_ids_with_legacy_sources(CtwaReferralSource), [self.org.id, self.org2.id])
        self.assertEqual(legacy_sources(CtwaReferralSource).count(), 3)

    def test_forwards_loads_models_and_runs_collapse(self):
        apps = Mock()
        models = {
            ("conversion_events", "CtwaReferralSource"): CtwaReferralSource,
            ("conversion_events", "CTWA"): CTWA,
        }
        apps.get_model.side_effect = lambda app, model: models[(app, model)]

        with patch.object(_collapse, "collapse_legacy_sources_per_org") as mock_collapse:
            _collapse.forwards(apps, schema_editor=None)

        mock_collapse.assert_called_once_with(CtwaReferralSource, CTWA)
