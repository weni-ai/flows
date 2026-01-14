from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication

from django.db.models import Q, Sum

from temba.api.auth.jwt import RequiredJWTAuthentication
from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.mixins import ISO8601DateFilterQueryParamsMixin
from temba.api.v2.permissions import HasValidJWT, IsUserInOrg
from temba.channels.models import Channel, ChannelCount
from temba.orgs.models import Org


class GetProjectView(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, IsUserInOrg]

    def get(self, request: Request):
        org = self.get_org_from_request(request, missing_status=400, missing_error="project_uuid is required")
        if isinstance(org, Response):
            return org

        project_data = {
            "project_uuid": str(org.proj_uuid),
            "name": org.name,
            "is_active": org.is_active,
            "brain_on": org.brain_on,
        }
        return Response(project_data)


class ProjectLanguageView(APIViewMixin, APIView):
    authentication_classes = [RequiredJWTAuthentication]
    permission_classes = [HasValidJWT]

    def get(self, request: Request):
        project_uuid = getattr(request, "project_uuid", None)
        channel_uuid = getattr(request, "channel_uuid", None)

        if project_uuid is None and channel_uuid is None:
            return Response(status=400, data={"error": "project_uuid or channel_uuid is required"})

        try:
            if project_uuid:
                org = Org.objects.get(proj_uuid=project_uuid)
            else:
                channel = Channel.objects.get(uuid=channel_uuid)
                org = channel.org
        except (Org.DoesNotExist):
            return Response(status=404, data={"error": "Project not found"})
        except Channel.DoesNotExist:
            return Response(status=404, data={"error": "Channel not found"})

        return Response({"language": org.language})


class ProjectMessageCountView(ISO8601DateFilterQueryParamsMixin, APIViewMixin, APIView):
    """
    Returns message counts (incoming/outgoing/total) for a project, using ChannelCount.

    Optional date filters (inclusive):
    - after / before (API v2 convention)
    - start_date / end_date (aliases)
    """

    authentication_classes = [RequiredJWTAuthentication]
    permission_classes = [HasValidJWT]

    def _get_queryset(self, project_uuid: str, after_date, before_date):
        queryset = ChannelCount.objects.filter(
            channel__org__proj_uuid=project_uuid,
            count_type__in=[ChannelCount.INCOMING_MSG_TYPE, ChannelCount.OUTGOING_MSG_TYPE],
        )

        if after_date or before_date:
            queryset = queryset.filter(day__isnull=False)
        if after_date:
            queryset = queryset.filter(day__gte=after_date)
        if before_date:
            queryset = queryset.filter(day__lte=before_date)

        return queryset

    def _aggregate_counts(self, queryset):
        def as_amount(value):
            return 0 if value is None else value

        agg = queryset.aggregate(
            incoming=Sum("count", filter=Q(count_type=ChannelCount.INCOMING_MSG_TYPE)),
            outgoing=Sum("count", filter=Q(count_type=ChannelCount.OUTGOING_MSG_TYPE)),
            total=Sum("count"),
        )

        return {
            "incoming_amount": as_amount(agg.get("incoming")),
            "outgoing_amount": as_amount(agg.get("outgoing")),
            "total_amount": as_amount(agg.get("total")),
        }

    def get(self, request: Request):
        project_uuid = getattr(request, "project_uuid", None)

        if project_uuid is None:
            return Response(status=400, data={"error": "project_uuid is required"})

        try:
            Org.objects.only("id").get(proj_uuid=project_uuid)
        except Org.DoesNotExist:
            return Response(status=404, data={"error": "Project not found"})

        date_filters = self.get_date_range_from_request(request)
        if isinstance(date_filters, Response):
            return date_filters
        after_date, before_date = date_filters

        queryset = self._get_queryset(project_uuid, after_date, before_date)
        return Response(self._aggregate_counts(queryset))
