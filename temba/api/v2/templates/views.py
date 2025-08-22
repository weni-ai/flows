from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication

from django.db.models import F

from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.permissions import IsUserInOrg
from temba.api.v2.views_base import CreatedOnCursorPagination
from temba.orgs.models import Org
from temba.templates.models import TemplateTranslation

from .serializers import TemplateTranslationDetailsSerializer


class TemplatesTranslationsEndpoint(APIViewMixin, APIView):
    """
    GET returns paginated list of active template translations for an org, selected by project_uuid.
    Each item includes header/body/footer/buttons.
    Query params:
      - project_uuid: required
      - category: optional template category filter (e.g. MARKETING, marketing)
      - limit: optional page size
      - cursor: optional cursor for pagination
    """

    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, IsUserInOrg]

    class Pagination(CreatedOnCursorPagination):
        default_page_size = 20
        page_size_query_param = "limit"
        ordering = ("-sort_on", "-id")

    def get(self, request, *args, **kwargs):
        project_uuid = request.query_params.get("project_uuid")
        if not project_uuid:
            return Response({"error": "Project not provided"}, status=401)

        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except Org.DoesNotExist:
            return Response({"error": "Project not found"}, status=404)

        queryset = (
            TemplateTranslation.objects.filter(is_active=True, template__org=org, template__is_active=True)
            .select_related("template")
            .prefetch_related("headers", "buttons")
            .annotate(sort_on=F("template__modified_on"))
            .order_by("-sort_on", "-id")
        )

        # optional filter by template category (accepts either display or enum casing)
        category = request.query_params.get("category")
        if category:
            queryset = queryset.filter(template__category=category.upper())

        pagination = self.Pagination()
        page = pagination.paginate_queryset(queryset, request, self)
        serializer = TemplateTranslationDetailsSerializer(page, many=True)
        return pagination.get_paginated_response(serializer.data)
