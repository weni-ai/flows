import requests
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication

from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.permissions import IsUserInOrg
from temba.msgs.cost_service import get_billing_pricing


class BillingPricingEndpoint(APIViewMixin, APIView):
    """
    Proxy endpoint that returns the billing pricing payload as-is.

    Optional query params:
      - project: UUID of the project to fetch pricing for. If omitted, uses the current org's proj_uuid.
    """

    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, IsUserInOrg]

    def get(self, request, *args, **kwargs):
        org = self.get_org_from_request(
            request,
            missing_status=400,
            missing_error="project_uuid is required",
            not_found_error="Project not found",
        )
        if isinstance(org, Response):
            return org
        project_uuid = request.project_uuid

        try:
            data = get_billing_pricing(project=project_uuid)
            return Response(data)
        except requests.RequestException:
            return Response({}, status=502)
