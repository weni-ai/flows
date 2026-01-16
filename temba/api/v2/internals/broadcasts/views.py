from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated, ParseError
from rest_framework.mixins import CreateModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication
from weni.internal.permissions import CanCommunicateInternally
from weni.internal.views import InternalGenericViewSet

from django.conf import settings
from django.contrib.auth import get_user_model

from temba.api.auth.jwt import OptionalJWTAuthentication
from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.permissions import HasValidJWT, IsUserInOrg
from temba.api.v2.serializers import WhatsappBroadcastReadSerializer, WhatsappBroadcastWriteSerializer
from temba.api.v2.views_base import DefaultLimitOffsetPagination
from temba.contacts.models import ContactGroup
from temba.msgs.models import Broadcast, BroadcastStatistics
from temba.msgs.services import count_duplicate_contacts_across_groups, count_unique_contacts_in_groups
from temba.orgs.models import Org

from .serializers import BroadcastSerializer, BroadcastWithStatisticsSerializer, UserAndProjectSerializer
from .services import upload_broadcast_media

User = get_user_model()


class BroadcastsViewSet(CreateModelMixin, InternalGenericViewSet):
    authentication_classes = []
    permission_classes = []
    serializer_class = BroadcastSerializer

    def get_serializer(self, *args, **kwargs):
        serializer = UserAndProjectSerializer(data=self.request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        project = serializer.validated_data["project"]

        context = dict(org=project.org, user=user)

        return super().get_serializer(*args, **kwargs, context=context)

    def create(self, request, *args, **kwargs):
        params = request.query_params
        token = params.get("token")

        if token is None:
            raise NotAuthenticated()

        if token != settings.ROUTER_FIXED_ACCESS_TOKEN:
            raise AuthenticationFailed()

        return super().create(request, *args, **kwargs)


class InternalWhatsappBroadcastsEndpoint(APIViewMixin, APIView):
    # Try JWT first; if not applicable, fall back to OIDC
    authentication_classes = [OptionalJWTAuthentication, InternalOIDCAuthentication]
    permission_classes = [(IsAuthenticated & (CanCommunicateInternally | IsUserInOrg)) | HasValidJWT]

    def post(self, request, *args, **kwargs):
        project_uuid = request.data.get("project") or getattr(request, "project_uuid", None)

        if not project_uuid:
            return Response({"error": "Project not provided"}, status=401)

        try:
            org = Org.objects.get(proj_uuid=project_uuid)
            # When authenticated via JWT, prefer email from token; otherwise use request.user
            if getattr(request, "jwt_payload", None):
                email = (
                    request.jwt_payload.get("email")
                    or request.jwt_payload.get("user_email")
                    or request.data.get("user_email")
                )
            else:
                email = getattr(request.user, "email", None)

            if not email:
                return Response({"error": "User email not provided"}, status=401)

            user, _ = User.objects.get_or_create(email=email)
        except Org.DoesNotExist:
            return Response({"error": "Project not found"}, status=404)

        serializer = WhatsappBroadcastWriteSerializer(
            data=request.data, context={"request": request, "org": org, "user": user}
        )

        if serializer.is_valid():
            broadcast = serializer.save()
            response_serializer = WhatsappBroadcastReadSerializer(
                instance=broadcast, context={"request": request, "org": org, "user": user}
            )
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=400)


class InternalBroadcastStatisticsEndpoint(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, IsUserInOrg]
    serializer_class = BroadcastWithStatisticsSerializer

    def get(self, request, *args, **kwargs):
        org = self.get_org_from_request(
            request,
            missing_status=400,
            missing_error="Project UUID not provided",
            not_found_error="Project not found",
        )
        if isinstance(org, Response):
            return org
        qs = Broadcast.objects.filter(org=org, is_bulk_send=True)
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        name = request.query_params.get("name")
        broadcast_id = request.query_params.get("id")

        if start_date:
            qs = qs.filter(created_on__gte=start_date)
        if end_date:
            qs = qs.filter(created_on__lte=end_date)
        if name:
            qs = qs.filter(name__icontains=name)
        if broadcast_id:
            qs = qs.filter(id=broadcast_id)

        qs = qs.order_by("-created_on")
        paginator = DefaultLimitOffsetPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = BroadcastWithStatisticsSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class InternalBroadcastStatisticMontlyEndpoint(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, IsUserInOrg]

    def get(self, request, *args, **kwargs):
        org = self.get_org_from_request(
            request,
            missing_status=400,
            missing_error="Project UUID not provided",
            not_found_error="Project not found",
        )
        if isinstance(org, Response):
            return org

        result = {}
        result["last_30_days_stats"] = BroadcastStatistics.last_30_days_stats(org)
        result["success_rate_30_days"] = BroadcastStatistics.success_rate_30_days(org)

        return Response(result)


class InternalBroadcastGroupsStatsEndpoint(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, IsUserInOrg]

    def get(self, request, *args, **kwargs):
        org = self.get_org_from_request(
            request,
            query_keys=("project_uuid", "project"),
            missing_status=400,
            missing_error="Project UUID not provided",
            not_found_error="Project not found",
        )
        if isinstance(org, Response):
            return org

        # Accept both repeated query params (?groups=...&groups=...) and comma-separated values
        group_ids = request.query_params.getlist("group_ids") or []
        group_uuids = request.query_params.getlist("groups") or request.query_params.getlist("group_uuids") or []

        if len(group_ids) == 1 and "," in (group_ids[0] or ""):
            group_ids = [gid for gid in group_ids[0].split(",") if gid]
        if len(group_uuids) == 1 and "," in (group_uuids[0] or ""):
            group_uuids = [g for g in group_uuids[0].split(",") if g]

        if not group_ids and not group_uuids:
            return Response({"error": "Groups not provided"}, status=400)

        groups_qs = ContactGroup.user_groups.filter(org=org, is_active=True)
        groups = []
        if group_ids:
            groups += list(groups_qs.filter(id__in=group_ids))
        if group_uuids:
            groups += list(groups_qs.filter(uuid__in=group_uuids))

        # dedupe in case of overlap
        groups = {g.id: g for g in groups}.values()
        groups = list(groups)

        if not groups:
            return Response({"error": "No valid groups found for this project"}, status=400)

        total_groups_count = sum((g.get_member_count() or 0) for g in groups)
        group_ids = [g.id for g in groups]
        duplicates_count = count_duplicate_contacts_across_groups(group_ids) if len(groups) > 1 else 0
        distinct_count = count_unique_contacts_in_groups(group_ids)

        return Response(
            {
                "total_count": total_groups_count,
                "duplicates_count": duplicates_count,
                "distinct_count": distinct_count,
            }
        )


class InternalBroadcastsUploadMediaEndpoint(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated & (CanCommunicateInternally | IsUserInOrg)]

    def post(self, request: Request):
        project_uuid = request.data.get("project_uuid") or request.data.get("project")

        if not project_uuid:
            return Response({"error": "project_uuid is required"}, status=400)
        
        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except Org.DoesNotExist:
            return Response({"error": "Project not found"}, status=404)

        result = {}
        result["last_30_days_stats"] = BroadcastStatistics.last_30_days_stats(org)
        result["success_rate_30_days"] = BroadcastStatistics.success_rate_30_days(org)

        upload = request.FILES.get("file") or request.data.get("file")
        if not upload:
            raise ParseError(detail="file is required")

        result = upload_broadcast_media(org, upload)

        return Response(result)
