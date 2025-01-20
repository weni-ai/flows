from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from django.conf import settings

from temba.api.v2.internals.channels.serializers import ChannelProjectSerializer
from temba.api.v2.internals.views import APIViewMixin
from temba.channels.models import Channel


class ChannelProjectView(APIViewMixin, APIView):
    def post(self, request: Request):
        params = request.query_params
        token = params.get("token")

        if token is None:
            raise NotAuthenticated()

        if token != settings.BILLING_FIXED_ACCESS_TOKEN:
            raise AuthenticationFailed()

        serializer = ChannelProjectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        channels_uuids = serializer.validated_data.get("channels")

        channels = (
            Channel.objects.filter(uuid__in=channels_uuids)
            .select_related("org")
            .only("uuid", "org__proj_uuid", "config")
        )

        response = {"results": []}

        for channel in channels:
            channel_data = {"channel_uuid": str(channel.uuid), "project_uuid": str(channel.org.proj_uuid)}
            if channel.channel_type == "WAC":
                channel_data["waba"] = channel.config.get("wa_waba_id") if channel.config.get("wa_waba_id") else ""
                channel_data["phone_number"] = (
                    channel.config.get("wa_number") if channel.config.get("wa_number") else ""
                )
            response["results"].append(channel_data)

        return Response(response)


class ChannelAllowedDomainsView(APIViewMixin, APIView):
    def get(self, request: Request):
        params = request.query_params
        channelUUID = params.get("channel")

        if channelUUID is None:
            return Response(status=400)
        try:
            channel = Channel.objects.get(uuid=channelUUID)
        except Channel.DoesNotExist:
            return Response(status=404)

        response = []
        allowedDomains = channel.config.get("allowed_domains")
        if allowedDomains is not None and len(allowedDomains) > 0:
            response = allowedDomains

        return Response(response)
