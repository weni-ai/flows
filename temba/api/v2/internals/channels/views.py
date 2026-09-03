from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication
from weni.internal.permissions import CanCommunicateInternally as OIDCCanCommunicateInternally
from weni_commons.auth import CanCommunicateInternally, WeniAuthentication
from weni_commons.auth.helpers import get_auth_context

from django.core import exceptions as django_exceptions

from temba.api.auth.billing import BillingFixedAccessTokenViewMixin
from temba.orgs.models import Org
from temba.api.auth.jwt import RequiredJWTAuthentication
from temba.api.v2.internals.channels.serializers import (
    ChannelElevenLabsApiKeySerializer,
    ChannelMarketingTagsSerializer,
    ChannelProjectSerializer,
    ChannelWabaMigrationSerializer,
)
from temba.api.v2.internals.channels.usecases import GetChannelMarketingTagsUseCase, GetElevenLabsApiKeyUseCase
from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.permissions import HasValidJWT, IsUserInOrg
from temba.channels.models import Channel
from temba.channels.types.whatsapp_cloud.usecases import UpdateWhatsAppCloudWabaUseCase, WabaChannelNotFound


class ChannelProjectView(BillingFixedAccessTokenViewMixin, APIViewMixin, APIView):
    def post(self, request: Request):
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
            channel_data = {
                "channel_uuid": str(channel.uuid),
                "project_uuid": str(channel.org.proj_uuid),
            }
            if channel.channel_type == "WAC":
                channel_data["waba"] = channel.config.get("wa_waba_id") if channel.config.get("wa_waba_id") else ""
                channel_data["phone_number"] = (
                    channel.config.get("wa_number") if channel.config.get("wa_number") else ""
                )
            response["results"].append(channel_data)

        return Response(response)


class InternalChannelView(APIViewMixin, APIView):
    authentication_classes = [WeniAuthentication, InternalOIDCAuthentication]
    permission_classes = [CanCommunicateInternally | (IsAuthenticated & IsUserInOrg)]

    def get(self, request: Request):
        auth = get_auth_context(request)
        if auth is not None and auth.is_jwt:
            org = self._get_org_for_project_uuid(auth.project_uuid)
        else:
            org = self.get_org_from_request(
                request,
                missing_status=400,
                missing_error="project_uuid is required",
                not_found_error="Project not found",
            )
        if isinstance(org, Response):
            return org

        channels = Channel.objects.filter(org=org, is_active=True)
        results = [self._serialize_channel(channel) for channel in channels]
        return Response({"results": results})

    @staticmethod
    def _get_org_for_project_uuid(project_uuid):
        try:
            return Org.objects.get(proj_uuid=project_uuid)
        except (Org.DoesNotExist, django_exceptions.ValidationError, ValueError):
            return Response({"error": "Project not found"}, status=404)

    @staticmethod
    def _serialize_channel(channel):
        config = channel.config or {}
        channel_data = {
            "uuid": str(channel.uuid),
            "channel_type": channel.channel_type,
            "name": channel.name,
            "is_active": channel.is_active,
            "waba": config.get("wa_waba_id") or None,
            "phone_number": config.get("wa_number") or None,
            "config": {
                "wa_waba_id": config.get("wa_waba_id"),
                "wa_number": config.get("wa_number"),
                "is_demo": bool(config.get("is_demo", False)),
            },
        }
        if channel.channel_type == "WAC":
            channel_data["MMLite"] = True if config.get("mmlite") else False
        return channel_data


class ChannelAllowedDomainsView(APIViewMixin, APIView):
    authentication_classes = [RequiredJWTAuthentication]
    permission_classes = [HasValidJWT]

    def get(self, request: Request):
        channel_uuid = getattr(request, "channel_uuid", None)

        if channel_uuid is None:
            return Response(status=400)
        try:
            channel = Channel.objects.get(uuid=channel_uuid)
        except Channel.DoesNotExist:
            return Response(status=404)

        response = []
        allowedDomains = channel.config.get("allowed_domains")
        if allowedDomains is not None and len(allowedDomains) > 0:
            response = allowedDomains

        return Response(response)


class ChannelElevenLabsApiKeyView(APIViewMixin, APIView):
    authentication_classes = [RequiredJWTAuthentication]
    permission_classes = [HasValidJWT]

    def get(self, request: Request):
        channel_uuid = getattr(request, "channel_uuid", None)
        serializer = ChannelElevenLabsApiKeySerializer(data={"channel_uuid": channel_uuid})
        serializer.is_valid(raise_exception=True)

        usecase = GetElevenLabsApiKeyUseCase()
        api_key = usecase.execute(serializer.validated_data["channel_uuid"])

        return Response({"api_key": api_key})


class ChannelMarketingTagsView(APIViewMixin, APIView):
    authentication_classes = [RequiredJWTAuthentication]
    permission_classes = [HasValidJWT]

    def get(self, request: Request):
        channel_uuid = getattr(request, "channel_uuid", None)
        serializer = ChannelMarketingTagsSerializer(data={"channel_uuid": channel_uuid})
        serializer.is_valid(raise_exception=True)

        usecase = GetChannelMarketingTagsUseCase()
        marketing_tags = usecase.execute(serializer.validated_data["channel_uuid"])

        return Response({"marketing_tags": marketing_tags})


class ChannelWabaMigrationView(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, OIDCCanCommunicateInternally]

    def post(self, request: Request):
        serializer = ChannelWabaMigrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        usecase = UpdateWhatsAppCloudWabaUseCase()
        try:
            results = usecase.execute(
                old_waba_id=serializer.validated_data["old_waba_id"],
                new_waba_id=serializer.validated_data["new_waba_id"],
            )
        except WabaChannelNotFound:
            return Response(
                {"detail": "No WhatsApp Cloud channel found for the provided WABA"},
                status=404,
            )

        return Response({"results": results})
