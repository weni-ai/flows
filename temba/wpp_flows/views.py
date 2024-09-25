from rest_framework import status, viewsets
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from django.conf import settings

from temba.wpp_flows.models import WhatsappFlow


class WhatsappFlowsViewset(viewsets.ViewSet):
    authentication_classes = []
    permission_classes = [AllowAny]

    def create(self, request):
        payload = request.data
        params = request.query_params
        token = params.get("token")

        if token is None:
            raise NotAuthenticated()

        if token != settings.COURIER_FIXED_ACCESS_TOKEN:
            raise AuthenticationFailed()

        entry_list = payload.get("entry", None)

        if entry_list is None:
            return Response("`entry` is a required field", status=status.HTTP_400_BAD_REQUEST)

        entry = entry_list[0]

        flow_id = entry.get("id")
        if flow_id is None:
            return Response("`id` is a required field", status=status.HTTP_400_BAD_REQUEST)

        new_status = entry["changes"][0]["value"]["new_status"]

        if not WhatsappFlow.is_status_valid(new_status):
            return Response("status is not valid", status=status.HTTP_400_BAD_REQUEST)

        try:
            WhatsappFlow.update_status(flow_id, new_status)
        except WhatsappFlow.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        return Response(status=status.HTTP_200_OK)