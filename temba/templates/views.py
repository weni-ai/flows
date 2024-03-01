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
                request.data.get("url"),
                request.data.get("request"),
                200,
                request.data.get("response"),
                channel=channel,
            )
        update_local_templates(channel, request.data.get("data"))
        return Response(status=status.HTTP_200_OK)
