from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication

from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.permissions import IsUserInOrg
from temba.orgs.models import Org


class GetProjectView(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, IsUserInOrg]

    def get(self, request: Request):
        params = request.query_params
        project_uuid = params.get("project_uuid")

        if project_uuid is None:
            return Response(status=400, data={"error": "project_uuid is required"})

        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except Org.DoesNotExist:
            return Response(status=404, data={"error": "Project not found"})

        project_data = {
            "project_uuid": str(org.proj_uuid),
            "name": org.name,
            "is_active": org.is_active,
            "brain_on": org.brain_on,
        }
        return Response(project_data)
