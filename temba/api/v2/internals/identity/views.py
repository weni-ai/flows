from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication
from weni.internal.permissions import CanCommunicateInternally

from temba.api.v2.internals.views import APIViewMixin
from temba.contacts import identity
from temba.orgs.models import Org


class IdentityView(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [CanCommunicateInternally]

    def _org(self, request):
        project_id = None
        if isinstance(request.data, dict):
            project_id = request.data.get("project_id") or request.data.get("project_uuid")
        if not project_id:
            project_id = request.query_params.get("project_id") or request.query_params.get("project_uuid")
        if not project_id:
            return None, Response({"error": "validation"}, status=400)
        try:
            return Org.objects.get(proj_uuid=project_id), None
        except Org.DoesNotExist:
            return None, Response({"error": "forbidden"}, status=403)

    def _respond(self, result):
        if result.code:
            return Response({"error": result.code}, status=result.status)
        return Response(result.payload, status=result.status)


class IdentityAttachView(IdentityView):
    def post(self, request, *args, **kwargs):
        org, error = self._org(request)
        if error:
            return error
        anchor = request.data.get("anchor") or {}
        result = identity.attach(
            org,
            urn_id=request.data.get("urn_id"),
            anchor_type=anchor.get("type"),
            value=anchor.get("value"),
            verified=anchor.get("verified", False),
            actor=request.data.get("actor") or "api",
        )
        return self._respond(result)


class IdentityDetachView(IdentityView):
    def post(self, request, *args, **kwargs):
        org, error = self._org(request)
        if error:
            return error
        result = identity.detach(
            org,
            urn_id=request.data.get("urn_id"),
            target_consumer_id=request.data.get("target_consumer_id"),
            confirmation_code=request.data.get("confirmation_code"),
            actor=request.data.get("actor") or "api",
            privileged=bool(request.data.get("privileged")),
        )
        return self._respond(result)


class IdentityGraphView(IdentityView):
    def get(self, request, *args, **kwargs):
        org, error = self._org(request)
        if error:
            return error
        result = identity.read_graph(
            org,
            urn_id=request.query_params.get("urn_id"),
            consumer_id=request.query_params.get("consumer_id"),
        )
        return self._respond(result)


class IdentityInactivityView(IdentityView):
    def post(self, request, *args, **kwargs):
        org, error = self._org(request)
        if error:
            return error
        result = identity.set_inactivity(
            org,
            ai_inactivity_hours=request.data.get("ai_inactivity_hours"),
            human_inactivity_hours=request.data.get("human_inactivity_hours"),
        )
        return self._respond(result)


class IdentityConfirmationView(IdentityView):
    def post(self, request, *args, **kwargs):
        org, error = self._org(request)
        if error:
            return error
        urn = identity._lookup_urn(org, request.data.get("urn_id"), lock=False)
        if urn is None:
            return Response({"error": "validation"}, status=400)
        code = identity.issue_confirmation_code(org, urn)
        return Response({"confirmation_code": code}, status=201)


class IdentityForgetView(IdentityView):
    def post(self, request, *args, **kwargs):
        org, error = self._org(request)
        if error:
            return error
        result = identity.forget_consumer(
            org,
            consumer_id=request.data.get("consumer_id"),
            actor=request.data.get("actor") or "api",
        )
        return self._respond(result)
