from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from weni.internal.views import InternalGenericViewSet

from django.shortcuts import get_object_or_404

from temba.channels.models import Channel
from temba.request_logs.models import HTTPLog
from temba.utils.whatsapp.tasks import update_local_templates
from temba.templates.models import Template
from temba.templates.serializers import TemplateSyncSerializer


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

    @action(detail=True, methods=["POST"], url_path="template-sync")
    def template_sync(self, request, pk):
        serializer = TemplateSyncSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        channel = get_object_or_404(Channel, uuid=pk)
        template_name = validated_data.get("template_name")

        template = Template.objects.filter(name=template_name, org=channel.org).first()

        if template:
            update_template_sync(template.id, validated_data.get("webhook"))
            return Response(status=status.HTTP_200_OK)

        else:
            update_local_templates(channel, [validated_data.get("template_data")], True)
            return Response(status=status.HTTP_204_NO_CONTENT)
