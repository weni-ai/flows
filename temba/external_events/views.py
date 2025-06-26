import json
import logging
import requests
from datetime import datetime

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.views import View
from temba.api.v2.internals.authentication import InternalOIDCAuthentication
from temba.api.v2.internals.permissions import CanCommunicateInternally
from django.contrib.auth.models import User, IsAuthenticated

from .models import ClickToWhatsAppData
from .serializers import ConversionEventSerializer

logger = logging.getLogger(__name__)


class ConversionEventView(View):
    """
    API endpoint to receive conversion events (lead/purchase) 
    and send immediately to Meta Conversion API
    """
    
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, CanCommunicateInternally]

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)
    
    def post(self, request):
        """
        Receive conversion event and send immediately to Meta
        """
        try:
            
            # Validate required data
            serializer = ConversionEventSerializer(data=data)
            if not serializer.is_valid():
                return JsonResponse(
                    {'error': 'Validation Error', 'detail': serializer.errors}, 
                    status=400
                )
            
            validated_data = serializer.validated_data
            event_type = validated_data['event_type']
            channel_uuid = validated_data['channel_uuid']
            payload = validated_data.get('payload', {})
            
            # Get CTWA data for Meta sending
            ctwa_data = self._get_ctwa_data(channel_uuid)
            if not ctwa_data:
                return JsonResponse(
                    {'error': 'CTWA Data Not Found', 
                     'detail': f'No CTWA data found for channel {channel_uuid}'}, 
                    status=404
                )
            
            dataset_id = self._get_channel_dataset_id(channel_uuid)
            if not dataset_id:
                return JsonResponse(
                    {'error': 'Dataset ID Not Found', 
                     'detail': f'No dataset_id configured for channel {channel_uuid}'}, 
                    status=404
                )
            
            # Build payload for Meta Conversion API
            meta_payload = self._build_meta_payload(event_type, ctwa_data, payload)
            
            # Send to Meta immediately
            success, error_msg = self._send_to_meta(meta_payload, dataset_id)
            
            if success:
                logger.info(f"Conversion event {event_type} sent successfully to Meta for channel {channel_uuid}")
                return JsonResponse(
                    {'status': 'success', 'message': 'Event sent to Meta successfully'}, 
                    status=200
                )
            else:
                logger.error(f"Failed to send conversion event to Meta: {error_msg}")
                return JsonResponse(
                    {'error': 'Meta API Error', 'detail': error_msg}, 
                    status=500
                )
                
        except Exception as e:
            logger.error(f"Unexpected error processing conversion event: {str(e)}")
            return JsonResponse(
                {'error': 'Internal Server Error', 'detail': 'An unexpected error occurred'}, 
                status=500
            )
    
    def _authenticate_request(self, request):
        """Verificar autenticação via token"""
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header.startswith('Bearer '):
            return False
        
        token = auth_header.split(' ')[1] if len(auth_header.split(' ')) > 1 else ''
        expected_token = getattr(settings, 'CONVERSION_API_TOKEN', '')
        
        return token and token == expected_token
    
    def _get_ctwa_data(self, channel_uuid):
        """Get CTWA data for lookup"""
        try:
            return ClickToWhatsAppData.objects.filter(channel_uuid=channel_uuid).first()
            
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
            
            return channel.config.get('meta_dataset_id')
            
        except Exception as e:
            logger.error(f"Error fetching channel dataset_id: {str(e)}")
            return None
    
    def _build_meta_payload(self, event_type, ctwa_data, original_payload):
        """Build payload for Meta Conversion API"""
        event_time = int(datetime.now().timestamp())
        
        # Map event types for Meta
        event_name_map = {
            'lead': 'Lead',
            'purchase': 'Purchase'
        }
        
        # Payload following the specified format for Meta
        meta_event = {
            'event_name': event_name_map.get(event_type, 'Lead'),
            'event_time': event_time,
            'action_source': 'business_messaging',
            'messaging_channel': 'whatsapp',
            'user_data': {
                'whatsapp_business_account_id': ctwa_data.waba,
                'ctwa_clid': ctwa_data.ctwa_clid,
            }
        }
        
        return {
            'data': [meta_event],
            'partner_agent': getattr(settings, 'META_PARTNER_AGENT', 'RapidPro')
        }
    
    def _send_to_meta(self, payload, dataset_id):
        """Send event to Meta Conversion API"""
        try:
            # Use global configuration for access token
            access_token = getattr(settings, 'WHATSAPP_ADMIN_SYSTEM_USER_TOKEN', '')
            
            if not access_token:
                return False, "Meta access token not configured"
            
            if not dataset_id:
                return False, "Meta dataset ID not configured"
            
            # Meta Conversion API URL as specified
            url = f"{settings.WHATSAPP_API_URL}/{dataset_id}/events?access_token={access_token}"
            
            # Headers
            headers = {
                'Content-Type': 'application/json'
            }
            
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                return result
            else:
                error_detail = response.text
                try:
                    error_json = response.json()
                    return error_json
                except:
                    pass
                return error_detail
                
        except requests.RequestException as e:
            return f"Network error sending to Meta: {str(e)}"
        except Exception as e:
            return False, f"Error sending to Meta: {str(e)}"
