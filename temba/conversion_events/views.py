import logging
from datetime import datetime

import requests
from rest_framework import viewsets
from weni.internal.views import InternalGenericViewSet

from django.conf import settings
from django.http import JsonResponse

from .models import CTWA
from .serializers import ConversionEventSerializer

logger = logging.getLogger(__name__)


class ConversionEventView(viewsets.ModelViewSet, InternalGenericViewSet):
    """
    API endpoint to receive conversion events (lead/purchase)
    and send immediately to Meta Conversion API
    """

    def create(self, request):
        """
        Receive conversion event and send immediately to Meta
        """
        try:
            # Validate JSON first
            if not hasattr(request, "data") or request.data is None:
                return JsonResponse({"error": "Invalid JSON", "detail": "Request body must be valid JSON"}, status=400)

            # Validate required data
            serializer = ConversionEventSerializer(data=request.data)
            if not serializer.is_valid():
                return JsonResponse({"error": "Validation Error", "detail": serializer.errors}, status=400)

            validated_data = serializer.validated_data
            event_type = validated_data["event_type"]
            channel_uuid = validated_data["channel_uuid"]
            contact_urn = validated_data["contact_urn"]
            payload = validated_data.get("payload", {})

            # Get CTWA data for Meta sending
            ctwa_data = self._get_ctwa_data(channel_uuid, contact_urn)
            if not ctwa_data:
                return JsonResponse(
                    {
                        "error": "CTWA Data Not Found",
                        "detail": f"No CTWA data found for channel {channel_uuid} and contact {contact_urn}",
                    },
                    status=404,
                )

            dataset_id = self._get_channel_dataset_id(channel_uuid)
            if not dataset_id:
                return JsonResponse(
                    {
                        "error": "Dataset ID Not Found",
                        "detail": f"No dataset_id configured for channel {channel_uuid}",
                    },
                    status=404,
                )

            # Build payload for Meta Conversion API
            meta_payload = self._build_meta_payload(event_type, ctwa_data, payload)

            # Send to Meta immediately
            success, error_msg = self._send_to_meta(meta_payload, dataset_id)

            if success:
                logger.info(f"Conversion event {event_type} sent successfully to Meta for channel {channel_uuid}")
                return JsonResponse({"status": "success", "message": "Event sent to Meta successfully"}, status=200)
            else:
                logger.error(f"Failed to send conversion event to Meta: {error_msg}")
                return JsonResponse({"error": "Meta API Error", "detail": error_msg}, status=500)

        except Exception as e:
            error_msg = str(e)
            if any(keyword in error_msg.lower() for keyword in ["json", "parse", "expecting value"]):
                logger.error(f"JSON parse error - {error_msg}")
                return JsonResponse({"error": "Invalid JSON", "detail": "Request body must be valid JSON"}, status=400)
            else:
                logger.error(f"Unexpected error processing conversion event: {error_msg}")
                return JsonResponse(
                    {"error": "Internal Server Error", "detail": "An unexpected error occurred"}, status=500
                )

    def _get_ctwa_data(self, channel_uuid, contact_urn):
        """Get CTWA data for lookup using both channel_uuid and contact_urn"""
        try:
            return CTWA.objects.filter(channel_uuid=channel_uuid, contact_urn=contact_urn).order_by('-timestamp').first()

        except Exception as e:
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
        event_name_map = {"lead": "Lead", "purchase": "Purchase"}

        # Payload following the specified format for Meta
        meta_event = {
            "event_name": event_name_map.get(event_type, "Lead"),
            "event_time": event_time,
            "action_source": "business_messaging",
            "messaging_channel": "whatsapp",
            "user_data": {
                "whatsapp_business_account_id": ctwa_data.waba,
                "ctwa_clid": ctwa_data.ctwa_clid,
            },
        }

        return {"data": [meta_event], "partner_agent": getattr(settings, "META_PARTNER_AGENT", "Weni by VTEX")}

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
