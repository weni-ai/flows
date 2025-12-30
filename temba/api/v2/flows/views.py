import json

from mozilla_django_oidc.contrib.drf import OIDCAuthentication
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication

from django.conf import settings

from temba import mailroom
from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.permissions import IsUserInOrg
from temba.api.v2.views_base import CreatedOnCursorPagination
from temba.flows.models import Flow
from temba.utils import analytics


class SimulateAPIView(APIView):  # pragma: no cover
    authentication_classes = [OIDCAuthentication]
    permission_classes = [IsAuthenticated]
    pagination_class = None
    renderer_classes = [JSONRenderer]
    throttle_classes = []

    def user_has_org_perm(self, org, permission):
        return self.request.user.has_org_perm(org, permission)

    def post(self, request, flow_uuid, *args, **kwargs):
        flows = Flow.objects.filter(uuid=flow_uuid)

        if not flows.exists():
            raise NotFound()

        flow = flows.first()

        if not self.user_has_org_perm(flow.org, "flows.flow_simulate"):
            raise PermissionDenied()

        try:
            json_dict = json.loads(request.body)
        except Exception as e:
            return Response(dict(status="error", description="Error parsing JSON: %s" % str(e)), status=400)

        if not settings.MAILROOM_URL:  # pragma: no cover
            return Response(dict(status="error", description="mailroom not configured, cannot simulate"), status=500)

        client = mailroom.get_client()

        analytics.track(request.user, "temba.flow_simulated", dict(flow=flow.name, uuid=flow.uuid))

        channel_uuid = "440099cf-200c-4d45-a8e7-4a564f4a0e8b"
        channel_name = "Test Channel"

        # build our request body, which includes any assets that mailroom should fake
        payload = {
            "org_id": flow.org_id,
            "assets": {
                "channels": [
                    {
                        "uuid": channel_uuid,
                        "name": channel_name,
                        "address": "+18005551212",
                        "schemes": ["tel"],
                        "roles": ["send", "receive", "call"],
                        "country": "US",
                    }
                ]
            },
        }

        if "flow" in json_dict:
            payload["flows"] = [{"uuid": flow.uuid, "definition": json_dict["flow"]}]

        # check if we are triggering a new session
        if "trigger" in json_dict:
            payload["trigger"] = json_dict["trigger"]

            # ivr flows need a connection in their trigger
            if flow.flow_type == Flow.TYPE_VOICE:
                payload["trigger"]["connection"] = {
                    "channel": {"uuid": channel_uuid, "name": channel_name},
                    "urn": "tel:+12065551212",
                }

            payload["trigger"]["environment"] = flow.org.as_environment_def()
            payload["trigger"]["user"] = self.request.user.as_engine_ref()

            try:
                return Response(client.sim_start(payload))
            except mailroom.MailroomException:
                return Response(dict(status="error", description="mailroom error"), status=500)

        # otherwise we are resuming
        elif "resume" in json_dict:
            payload["resume"] = json_dict["resume"]
            payload["resume"]["environment"] = flow.org.as_environment_def()
            payload["session"] = json_dict["session"]

            try:
                return Response(client.sim_resume(payload))
            except mailroom.MailroomException:
                return Response(dict(status="error", description="mailroom error"), status=500)


class InternalFlowsAPIView(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, IsUserInOrg]

    class Pagination(CreatedOnCursorPagination):
        page_size_query_param = "limit"

    def get(self, request: Request):
        org = request.org

        queryset = Flow.objects.filter(org=org, is_active=True)

        paginator = self.Pagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        results = [{"uuid": str(flow.uuid), "name": flow.name} for flow in page]
        return paginator.get_paginated_response(results)
