import logging
from datetime import datetime

import requests
from rest_framework import viewsets
from weni_datalake_sdk.clients.client import send_event_data
from weni_datalake_sdk.paths.events_path import EventPath

from django.conf import settings
from django.http import JsonResponse

from .courier_auth import ConversionEventAuthMixin
from .models import CTWA
from .serializers import ConversionEventSerializer
from .urns import whatsapp_urn_variants

COURIER_ONLY_EVENT_TYPES = {"conversation_started"}

CTWA_DATALAKE_VALUE_MAP = {
    "conversation_started": "conversation_started",
    "lead": "lead_qualified",
    "purchase": "purchase_completed",
}

logger = logging.getLogger(__name__)


class ConversionEventView(ConversionEventAuthMixin, viewsets.ModelViewSet):
    """
    API endpoint to receive conversion events (lead/purchase)
    and send to Meta Conversion API and/or Weni Datalake
    """

    def create(self, request):
        """
        Receive conversion event and send to appropriate destinations
        """
        try:
            # Validate JSON first
            if not hasattr(request, "data") or request.data is None:
                return JsonResponse(
                    {
                        "error": "Invalid JSON",
                        "detail": "Request body must be valid JSON",
                    },
                    status=400,
                )

            # Validate required data
            serializer = ConversionEventSerializer(data=request.data)
            if not serializer.is_valid():
                return JsonResponse(
                    {"error": "Validation Error", "detail": serializer.errors},
                    status=400,
                )

            validated_data = serializer.validated_data
            event_type = validated_data["event_type"]
            channel_uuid = validated_data["channel_uuid"]
            contact_urn = validated_data["contact_urn"]
            payload = validated_data.get("payload", {})

            if self.courier_authenticated and event_type not in COURIER_ONLY_EVENT_TYPES:
                return JsonResponse(
                    {
                        "error": "Forbidden",
                        "detail": "Fixed token authentication is only allowed for conversation_started events",
                    },
                    status=403,
                )

            # Get CTWA data for Meta sending
            ctwa_data = self._get_ctwa_data(channel_uuid, contact_urn)
            meta_success = None
            meta_error = None
            dataset_id = None

            # Meta CAPI requires ctwa_clid; conversation_started is Datalake-only
            if event_type != "conversation_started" and ctwa_data and ctwa_data.ctwa_clid:
                dataset_id = self._get_channel_dataset_id(channel_uuid)
                if dataset_id:
                    meta_payload = self._build_meta_payload(
                        event_type,
                        ctwa_data,
                        payload,
                    )
                    meta_success, meta_error = self._send_to_meta(meta_payload, dataset_id)

            # Always send to Datalake regardless of CTWA status
            datalake_success, datalake_error = self._send_to_datalake(
                event_type=event_type,
                channel_uuid=channel_uuid,
                contact_urn=contact_urn,
                ctwa_data=ctwa_data,
                payload=payload,
            )

            # Prepare response based on results
            if meta_success and datalake_success:
                logger.warning(
                    f"[SUCCESS] Both services: Meta and Datalake succeeded for event {event_type} on channel {channel_uuid}"
                )
                return JsonResponse(
                    {
                        "status": "success",
                        "message": "Event sent to Meta and Datalake successfully",
                    },
                    status=200,
                )
            elif datalake_success:  # If Datalake succeeds but Meta failed or wasn't attempted
                if ctwa_data and ctwa_data.ctwa_clid and dataset_id:  # Meta was attempted but failed
                    logger.warning(
                        f"[PARTIAL] Datalake succeeded but Meta failed for event {event_type} on channel {channel_uuid}. Meta error: {meta_error}"
                    )
                else:  # Meta wasn't attempted (no CTWA or dataset_id)
                    logger.warning(
                        f"[SUCCESS] Datalake only: Meta not attempted for event {event_type} on channel {channel_uuid}"
                    )
                return JsonResponse(
                    {
                        "status": "success",
                        "message": "Event sent to Datalake successfully",
                    },
                    status=200,
                )
            else:  # Datalake failed
                if ctwa_data and ctwa_data.ctwa_clid and dataset_id:  # Both services failed
                    logger.error(
                        f"[FAILURE] Both services failed for event {event_type} on channel {channel_uuid}. "
                        f"Meta error: {meta_error}, Datalake error: {datalake_error}"
                    )
                    error_type = "Meta and Datalake Error"
                    error_msg = f"Meta: {meta_error}, Datalake: {datalake_error}"
                else:  # Only Datalake failed (Meta wasn't attempted)
                    logger.error(
                        f"[FAILURE] Datalake failed for event {event_type} on channel {channel_uuid}. Error: {datalake_error}"
                    )
                    error_type = "Datalake Error"
                    error_msg = datalake_error

                return JsonResponse({"error": error_type, "detail": error_msg}, status=500)

        except Exception as e:
            error_msg = str(e)
            if any(keyword in error_msg.lower() for keyword in ["json", "parse", "expecting value"]):
                logger.error(f"JSON parse error - {error_msg}")
                return JsonResponse(
                    {
                        "error": "Invalid JSON",
                        "detail": "Request body must be valid JSON",
                    },
                    status=400,
                )
            else:
                logger.error(f"Unexpected error processing conversion event: {error_msg}")
                return JsonResponse(
                    {
                        "error": "Internal Server Error",
                        "detail": "An unexpected error occurred",
                    },
                    status=500,
                )

    def _get_ctwa_data(self, channel_uuid, contact_urn):
        """Get CTWA data for lookup using both channel_uuid and contact_urn"""
        try:
            return CTWA.objects.latest_for_urns(
                channel_uuids=[channel_uuid],
                contact_urns=whatsapp_urn_variants(contact_urn),
            )
        except Exception as e:
            print(f"\nERRO ao buscar CTWA: {str(e)}\n")
            logger.error(f"Error fetching CTWA data: {str(e)}")
            return None

    def _get_channel_dataset_id(self, channel_uuid):
        """Get dataset_id from channel config"""
        try:
            from temba.channels.models import Channel

            channel = Channel.objects.filter(uuid=channel_uuid, is_active=True).first()
            if not channel:
                return None

            return channel.config.get("meta_dataset_id")

        except Exception as e:
            logger.error(f"Error fetching channel dataset_id: {str(e)}")
            return None

    def _build_meta_payload(self, event_type, ctwa_data, original_payload):
        """Build payload for Meta Conversion API"""
        event_time = int(datetime.now().timestamp())

        # Map event types for Meta
        event_name_map = {"lead": "LeadSubmitted", "purchase": "Purchase", "abandoned_cart": "AbandonedCart"}

        # Payload following the specified format for Meta
        meta_event = {
            "event_name": event_name_map.get(event_type, "LeadSubmitted"),
            "event_time": event_time,
            "action_source": "business_messaging",
            "messaging_channel": "whatsapp",
            "user_data": {
                "whatsapp_business_account_id": ctwa_data.waba,
                "ctwa_clid": ctwa_data.ctwa_clid,
            },
        }

        if event_type in ("purchase", "abandoned_cart"):
            value = original_payload.get("value")
            currency = original_payload.get("currency", "BRL")  # Default to BRL if not provided
            if value:
                try:
                    # Convert value to float and keep it as float
                    value = float(value)
                    meta_event["value"] = value
                    meta_event["currency"] = currency
                except (ValueError, TypeError):
                    logger.warning(f"Invalid value format in purchase event: {value}")

        return {
            "data": [meta_event],
            "partner_agent": getattr(settings, "META_PARTNER_AGENT", "Weni by VTEX"),
        }

    def _send_to_meta(self, payload, dataset_id):
        """Send event to Meta Conversion API"""
        try:
            # Use global configuration for access token
            access_token = getattr(settings, "WHATSAPP_ADMIN_SYSTEM_USER_TOKEN", "")

            if not access_token:
                return False, "Meta access token not configured"

            if not dataset_id:
                return False, "Meta dataset ID not configured"

            # Meta Conversion API URL as specified
            url = f"{settings.WHATSAPP_API_URL}/{dataset_id}/events?access_token={access_token}"

            # Headers
            headers = {"Content-Type": "application/json"}

            response = requests.post(url, json=payload, headers=headers, timeout=30)

            if response.status_code == 200:
                return True, "Success"
            else:
                error_detail = response.json()
                return False, str(error_detail)

        except requests.RequestException as e:
            return False, f"Network error sending to Meta: {str(e)}"
        except Exception as e:
            return False, f"Error sending to Meta: {str(e)}"

    def _get_channel_and_org(self, channel_uuid):
        from temba.channels.models import Channel
        from temba.orgs.models import Org

        try:
            channel = Channel.objects.filter(uuid=channel_uuid, is_active=True).only("org_id", "config").first()
            if not channel:
                return None, None, "Channel not found"

        except Exception:
            logger.exception("Channel lookup failed")
            return None, None, "Channel not found"

        try:
            org = Org.objects.filter(id=channel.org_id).only("proj_uuid").first()
            if not org or not org.proj_uuid:
                return None, None, "Organization not found"
        except Exception:
            return None, None, "Organization not found"

        return channel, org, None

    def _resolve_waba_id(self, ctwa_data, channel):
        if ctwa_data and ctwa_data.waba:
            return ctwa_data.waba
        if channel.config and channel.config.get("wa_waba_id"):
            return channel.config["wa_waba_id"]
        return None

    def _send_to_datalake(self, event_type, channel_uuid, contact_urn, ctwa_data, payload):
        """Send event to Weni Datalake (legacy table + best-effort CTWA table)."""
        channel, org, lookup_error = self._get_channel_and_org(channel_uuid)
        if lookup_error:
            return False, lookup_error

        legacy_success, legacy_error = self._send_legacy_datalake(
            event_type=event_type,
            channel_uuid=channel_uuid,
            contact_urn=contact_urn,
            ctwa_data=ctwa_data,
            payload=payload,
            channel=channel,
            org=org,
        )
        if not legacy_success:
            return legacy_success, legacy_error

        ctwa_success, ctwa_error = self._send_ctwa_datalake(
            event_type=event_type,
            channel_uuid=channel_uuid,
            contact_urn=contact_urn,
            ctwa_data=ctwa_data,
            payload=payload,
            channel=channel,
            org=org,
        )
        if not ctwa_success and ctwa_error:
            logger.warning(
                f"[PARTIAL] Legacy Datalake succeeded but CTWA table failed for event {event_type} "
                f"on channel {channel_uuid}. CTWA error: {ctwa_error}"
            )

        return True, None

    def _send_legacy_datalake(self, event_type, channel_uuid, contact_urn, ctwa_data, payload, channel, org):
        """Send event to the legacy Weni Datalake table."""
        try:
            metadata = payload.copy() if payload else {}
            metadata["channel"] = str(channel_uuid)

            if channel.config and "wa_waba_id" in channel.config:
                metadata["waba_id"] = channel.config["wa_waba_id"]

            if ctwa_data:
                if ctwa_data.ctwa_clid:
                    metadata["ctwa_id"] = ctwa_data.ctwa_clid
                if ctwa_data.referral_source:
                    metadata["referral_source_id"] = ctwa_data.referral_source.source_id
                    metadata["referral_source_type"] = ctwa_data.referral_source.source_type
                if ctwa_data.message_id:
                    metadata["message_id"] = ctwa_data.message_id

            data = {
                "event_name": f"conversion_{event_type}",
                "key": "capi",
                "value": event_type,
                "value_type": "string",
                "date": datetime.now().timestamp(),
                "project": str(org.proj_uuid),
                "contact_urn": contact_urn,
                "metadata": metadata,
            }

            send_event_data(EventPath, data)
            return True, None

        except Exception as e:
            error_msg = f"Error sending to Datalake: {str(e)}"
            logger.error(error_msg)
            return False, error_msg

    def _can_send_ctwa_datalake(self, ctwa_data, channel, channel_uuid):
        if not ctwa_data:
            return False

        waba_id = self._resolve_waba_id(ctwa_data, channel)
        referral_source = ctwa_data.referral_source

        required_fields = {
            "ctwa_clid": ctwa_data.ctwa_clid,
            "message_id": ctwa_data.message_id,
            "campaign_source": referral_source.source_id if referral_source else None,
            "waba_id": waba_id,
            "channel": str(channel_uuid),
        }
        missing = [field for field, value in required_fields.items() if not value]
        if missing:
            logger.warning(f"Skipping CTWA Datalake event due to missing required fields: {', '.join(missing)}")
            return False

        return True

    def _build_ctwa_datalake_payload(self, event_type, channel_uuid, contact_urn, ctwa_data, channel, org, payload):
        ctwa_value = CTWA_DATALAKE_VALUE_MAP.get(event_type)
        if not ctwa_value:
            return None

        waba_id = self._resolve_waba_id(ctwa_data, channel)
        metadata = {
            "external_msg_id": ctwa_data.message_id,
            "ctwa_id": ctwa_data.ctwa_clid,
            "campaign_source": ctwa_data.referral_source.source_id,
            "waba_id": waba_id,
            "channel": str(channel_uuid),
        }

        if event_type == "purchase" and payload:
            value = payload.get("value")
            if value is not None:
                try:
                    metadata["order_value"] = float(value)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid order_value format in purchase event: {value}")

        return {
            "event_name": "ctwa",
            "key": "capi",
            "value": ctwa_value,
            "contact_urn": contact_urn,
            "project": str(org.proj_uuid),
            "date": ctwa_data.timestamp.timestamp(),
            "metadata": metadata,
        }

    def _send_ctwa_datalake(self, event_type, channel_uuid, contact_urn, ctwa_data, payload, channel, org):
        """Send event to the CTWA Weni Datalake table when required fields are available."""
        if not self._can_send_ctwa_datalake(ctwa_data, channel, channel_uuid):
            return True, None

        try:
            data = self._build_ctwa_datalake_payload(
                event_type=event_type,
                channel_uuid=channel_uuid,
                contact_urn=contact_urn,
                ctwa_data=ctwa_data,
                channel=channel,
                org=org,
                payload=payload,
            )
            if not data:
                return True, None

            send_event_data(EventPath, data)
            return True, None

        except Exception as e:
            error_msg = f"Error sending to CTWA Datalake: {str(e)}"
            logger.exception(error_msg)
            return False, error_msg
