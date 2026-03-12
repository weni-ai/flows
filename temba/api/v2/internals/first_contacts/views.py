from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication
from weni.internal.permissions import CanCommunicateInternally

from django.db.models import F, Min

from temba.api.v2.internals.views import APIViewMixin
from temba.msgs.models import Msg
from temba.orgs.models import Org


class FirstContactsPagination(LimitOffsetPagination):
    default_limit = 500
    max_limit = 1000


class InternalFirstContactsView(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, CanCommunicateInternally]

    def get(self, request, *args, **kwargs):
        project_uuid = request.query_params.get("project_uuid")

        if not project_uuid:
            return Response({"error": "project_uuid is required"}, status=400)

        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except Org.DoesNotExist:
            return Response({"error": "Project not found"}, status=404)

        channel_uuid = request.query_params.get("channel_uuid")
        after = request.query_params.get("after")
        before = request.query_params.get("before")

        if not channel_uuid:
            return Response({"error": "channel_uuid is required"}, status=400)
        if not after:
            return Response({"error": "after is required"}, status=400)
        if not before:
            return Response({"error": "before is required"}, status=400)

        queryset = (
            Msg.objects.filter(
                org=org,
                channel__uuid=channel_uuid,
                created_on__gte=after,
                created_on__lt=before,
                direction=Msg.DIRECTION_IN,
            )
            .exclude(status__in=[Msg.STATUS_FAILED, Msg.STATUS_ERRORED])
            .values(contact_urn=F("contact_urn__identity"))
            .annotate(first_created_on=Min("created_on"))
            .order_by("contact_urn")
        )

        paginator = FirstContactsPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)

        return paginator.get_paginated_response(page)
