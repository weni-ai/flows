from rest_framework import status, viewsets
from rest_framework.response import Response
from weni.internal.views import InternalGenericViewSet

from django.shortcuts import get_object_or_404

from temba.channels.models import Channel
from temba.utils.whatsapp.tasks import update_local_templates


class TemplateViewSet(viewsets.ModelViewSet, InternalGenericViewSet):
    def partial_update(self, request, pk):
        channel = get_object_or_404(Channel, uuid=pk)
        update_local_templates(channel, request.data.get("data"))

        return Response(status=status.HTTP_200_OK)
