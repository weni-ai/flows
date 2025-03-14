from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from weni.internal.views import InternalGenericViewSet

from django.shortcuts import get_object_or_404

from temba.channels.models import Channel
from temba.templates.models import Template
from temba.templates.serializers import TemplateSyncSerializer
from temba.utils.whatsapp.tasks import update_local_templates, update_template_sync


class TemplateViewSet(viewsets.ModelViewSet, InternalGenericViewSet):
    def partial_update(self, request, pk):
        channel = get_object_or_404(Channel, uuid=pk)
        update_local_templates(channel, request.data.get("data"))

        return Response(status=status.HTTP_200_OK)

    @action(detail=True, methods=["POST"], url_path="template-sync")
    def template_sync(self, request, pk):
        """Syncs a template, updating or creating."""
        serializer = TemplateSyncSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        channel = get_object_or_404(Channel, uuid=pk)

        return self._handle_template_sync(validated_data, channel)

    def _handle_template_sync(self, validated_data, channel):
        """Handles the logic for syncing templates."""
        template_name = validated_data.get("template_name")
        template = Template.objects.filter(name=template_name, org=channel.org).first()

        if template:
            webhook = validated_data.get("webhook")
            if not webhook:
                return Response(
                    {"detail": "Webhook is required for existing templates."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            update_template_sync(template.id, webhook)
            return Response(status=status.HTTP_200_OK)

        update_local_templates(channel, [validated_data.get("template_data")], True)
        return Response(status=status.HTTP_204_NO_CONTENT)
