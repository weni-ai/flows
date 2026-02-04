from datetime import datetime, time, timedelta

import pytz
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication

from django.core import exceptions as django_exceptions
from django.db.models import Q, Sum

from temba.api.auth.jwt import RequiredJWTAuthentication
from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.mixins import ISO8601DateFilterQueryParamsMixin
from temba.api.v2.permissions import HasValidJWT, IsUserInOrg
from temba.channels.models import Channel, ChannelCount
from temba.msgs.models import Msg
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
        channel_uuid = getattr(request, "channel_uuid", None)

        try:
            if project_uuid:
                Org.objects.only("id").get(proj_uuid=project_uuid)
            elif channel_uuid:
                channel = Channel.objects.select_related("org").only("org__proj_uuid").get(uuid=channel_uuid)
                project_uuid = str(channel.org.proj_uuid)
            else:
                return Response(status=400, data={"error": "project_uuid or channel_uuid is required"})
        except (Org.DoesNotExist, django_exceptions.ValidationError, ValueError):
            return Response(status=404, data={"error": "Project not found"})
        except Channel.DoesNotExist:
            return Response(status=404, data={"error": "Channel not found"})

        date_filters = self.get_date_range_from_request(request)
        if isinstance(date_filters, Response):
            return date_filters
        after_date, before_date = date_filters

        queryset = self._get_queryset(project_uuid, after_date, before_date)
        return Response(self._aggregate_counts(queryset))


class InternalProjectMessageCountView(ISO8601DateFilterQueryParamsMixin, APIViewMixin, APIView):
    """
    Returns message counts (incoming/outgoing/total) and unique contacts for projects.

    Uses InternalOIDCAuthentication for internal service-to-service calls.

    Query parameters:
    - project_uuid (optional): Filter by specific project. If not provided, returns
      aggregated counts for ALL projects.
    - after / start_date (optional): Filter messages from this date (inclusive).
      Defaults to today if not provided.
    - before / end_date (optional): Filter messages until this date (inclusive).
      Defaults to today if not provided. When filtering up to today, uses current
      time instead of end of day.

    Response:
    - incoming_amount: Total incoming messages
    - outgoing_amount: Total outgoing messages
    - total_amount: Total messages (incoming + outgoing)
    - unique_contacts: Unique contacts that sent messages (incoming) in the period
    """

    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated]

    def _get_message_counts(self, project_uuid, after_date, before_date):
        """
        Get incoming/outgoing message counts from ChannelCount (pre-aggregated, fast).
        """
        queryset = ChannelCount.objects.filter(
            count_type__in=[ChannelCount.INCOMING_MSG_TYPE, ChannelCount.OUTGOING_MSG_TYPE],
        )

        if project_uuid:
            queryset = queryset.filter(channel__org__proj_uuid=project_uuid)

        if after_date or before_date:
            queryset = queryset.filter(day__isnull=False)
        if after_date:
            queryset = queryset.filter(day__gte=after_date)
        if before_date:
            queryset = queryset.filter(day__lte=before_date)

        agg = queryset.aggregate(
            incoming=Sum("count", filter=Q(count_type=ChannelCount.INCOMING_MSG_TYPE)),
            outgoing=Sum("count", filter=Q(count_type=ChannelCount.OUTGOING_MSG_TYPE)),
        )

        incoming = agg.get("incoming") or 0
        outgoing = agg.get("outgoing") or 0

        return {
            "incoming_amount": incoming,
            "outgoing_amount": outgoing,
            "total_amount": incoming + outgoing,
        }

    def _get_unique_contacts(self, project_uuid, after_date, before_date):
        """
        Get unique contacts that sent messages (incoming) in the period.

        This requires a direct query on msgs_msg because unique contacts
        cannot be pre-aggregated for arbitrary date ranges.
        """
        from django.utils import timezone

        queryset = Msg.objects.filter(direction=Msg.DIRECTION_IN)

        if project_uuid:
            queryset = queryset.filter(org__proj_uuid=project_uuid)

        if after_date:
            start_datetime = datetime.combine(after_date, time.min, tzinfo=pytz.UTC)
            queryset = queryset.filter(created_on__gte=start_datetime)

        if before_date:
            today = timezone.now().date()
            if before_date >= today:
                # If before_date is today or future, use current time
                end_datetime = timezone.now()
            else:
                # Include the entire 'before_date' day (up to midnight of the next day)
                end_datetime = datetime.combine(before_date + timedelta(days=1), time.min, tzinfo=pytz.UTC)
            queryset = queryset.filter(created_on__lt=end_datetime)

        unique_count = queryset.values("contact_id", "org_id").distinct().count()

        return unique_count

    def _get_default_date_range(self):
        """
        Returns the default date range (today) when no filters are provided.
        """
        from django.utils import timezone

        today = timezone.now().date()
        return today, today

    def get(self, request: Request):
        project_uuid = request.query_params.get("project_uuid")

        if project_uuid:
            try:
                Org.objects.only("id").get(proj_uuid=project_uuid)
            except (Org.DoesNotExist, django_exceptions.ValidationError, ValueError):
                return Response(status=404, data={"error": "Project not found"})

        date_filters = self.get_date_range_from_request(request)
        if isinstance(date_filters, Response):
            return date_filters
        after_date, before_date = date_filters

        # Default to today if no date filters provided
        if after_date is None and before_date is None:
            after_date, before_date = self._get_default_date_range()

        counts = self._get_message_counts(project_uuid, after_date, before_date)

        counts["unique_contacts"] = self._get_unique_contacts(project_uuid, after_date, before_date)

        return Response(counts)
