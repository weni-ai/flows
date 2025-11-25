from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication

from temba.api.auth.jwt import RequiredJWTAuthentication
from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.permissions import HasValidJWT, IsUserInOrg
from temba.channels.models import Channel
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


class ProjectLanguageView(APIViewMixin, APIView):
    authentication_classes = [RequiredJWTAuthentication]
    permission_classes = [(IsAuthenticated & HasValidJWT)]

    def get(self, request: Request):
        params = request.query_params
        project_uuid = params.get("project_uuid")
        channel_uuid = params.get("channel_uuid")

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
