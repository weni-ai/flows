import requests
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication

from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.permissions import IsUserInOrg
from temba.msgs.cost_service import get_billing_pricing
from temba.orgs.models import Org


class BillingPricingEndpoint(APIViewMixin, APIView):
    """
    Proxy endpoint that returns the billing pricing payload as-is.

    Optional query params:
      - project: UUID of the project to fetch pricing for. If omitted, uses the current org's proj_uuid.
    """

    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, IsUserInOrg]

    def get(self, request, *args, **kwargs):
        params = request.query_params
        project_uuid = params.get("project_uuid")

        if project_uuid is None:
            return Response(status=400, data={"error": "project_uuid is required"})

        try:
            Org.objects.get(proj_uuid=project_uuid)
        except Org.DoesNotExist:
            return Response(status=404, data={"error": "Project not found"})

        try:
            data = get_billing_pricing(project=project_uuid)
            return Response(data)
        except requests.RequestException:
            return Response({}, status=502)
