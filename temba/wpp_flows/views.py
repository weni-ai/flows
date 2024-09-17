from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from temba.wpp_flows.utils import update_whatsapp_flows_status


class WhatsappFlowsViewset(viewsets.ViewSet):
    authentication_classes = []
    permission_classes = [AllowAny]

    def create(self, request):
        update_status = update_whatsapp_flows_status(request.data)
        if not update_status:
            return Response("An error occured", status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_200_OK)
