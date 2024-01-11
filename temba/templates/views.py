from rest_framework import status, viewsets
from rest_framework.response import Response
from weni.internal.views import InternalGenericViewSet

from django.shortcuts import get_object_or_404

from temba.channels.models import Channel
from temba.request_logs.models import HTTPLog
from temba.utils.whatsapp.tasks import update_local_templates


class TemplateViewSet(viewsets.ModelViewSet, InternalGenericViewSet):
    def partial_update(self, request, pk):
        channel = get_object_or_404(Channel, uuid=pk)
        waba_id = channel.config.get("wa_waba_id", None)
        if waba_id:
            HTTPLog.create_from_integrations_response(
                HTTPLog.WHATSAPP_TEMPLATES_SYNCED,
                f"https://graph.facebook.com/v16.0/{waba_id}/message_templates",
                request,
                request.data.get("status_code"),
                channel=channel,
                request_time=request.data.get("request_time"),
            )
        update_local_templates(channel, request.data.get("data"))
        return Response(status=status.HTTP_200_OK)
