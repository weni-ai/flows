from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication

from django.db.models import F

from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.permissions import IsUserInOrg
from temba.api.v2.views_base import DefaultLimitOffsetPagination
from temba.orgs.models import Org
from temba.templates.models import Template, TemplateTranslation

from .serializers import TemplateTranslationDetailsSerializer


class TemplatesTranslationsEndpoint(APIViewMixin, APIView):
    """
    GET returns paginated list of active template translations for an org, selected by project_uuid.
    Each item includes header/body/footer/buttons.
    Query params:
      - project_uuid: required
      - name: optional filter by template name (icontains)
      - language: optional filter by translation language (case-insensitive)
      - category: optional template category filter (e.g. MARKETING, marketing)
      - order_by: optional ordering, one of: name, -name, created_on, -created_on (default -created_on)
      - limit: optional page size
      - offset: optional offset for pagination
    """

    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, IsUserInOrg]

    # Using limit/offset pagination with shared defaults

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
        )

        # optional filter by template category (accepts either display or enum casing)
        category = request.query_params.get("category")
        if category:
            queryset = queryset.filter(template__category=category.upper())

        # optional filter by template name (icontains)
        name = request.query_params.get("name")
        if name:
            queryset = queryset.filter(template__name__icontains=name)

        # optional filter by channel
        channel_uuid = request.query_params.get("channel")
        if channel_uuid:
            queryset = queryset.filter(channel__uuid=channel_uuid)

        # optional filter by language (case-insensitive exact)
        language = request.query_params.get("language")
        if language:
            queryset = queryset.filter(language__iexact=language)

        # determine sort field for ordering
        order_by = request.query_params.get("order_by")
        if order_by in ("name", "-name"):
            queryset = queryset.annotate(sort_on=F("template__name"))
        else:
            # default and any other value -> created_on
            queryset = queryset.annotate(sort_on=F("template__created_on"))

        # apply explicit ordering for limit/offset pagination
        if order_by == "name":
            order_fields = ("sort_on", "id")
        elif order_by == "-name":
            order_fields = ("-sort_on", "-id")
        elif order_by == "created_on":
            order_fields = ("sort_on", "id")
        else:
            # default and any other value -> -created_on
            order_fields = ("-sort_on", "-id")
        queryset = queryset.order_by(*order_fields)

        pagination = DefaultLimitOffsetPagination()
        page = pagination.paginate_queryset(queryset, request, self)
        serializer = TemplateTranslationDetailsSerializer(page, many=True)
        return pagination.get_paginated_response(serializer.data)


class TemplateByIdEndpoint(APIViewMixin, APIView):
    """
    GET returns a single active template translation for a template, selected by project_uuid and path template_id.
    Query:
      - project_uuid: required (query param)
      - language: optional (query param, case-insensitive)
    Path:
      - template_id: required (numeric id of Template)
    """

    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated, IsUserInOrg]

    def get(self, request, *args, **kwargs):
        project_uuid = request.query_params.get("project_uuid")
        if not project_uuid:
            return Response({"error": "Project not provided"}, status=401)

        try:
            org = Org.objects.get(proj_uuid=project_uuid)
        except Org.DoesNotExist:
            return Response({"error": "Project not found"}, status=404)

        template_id = kwargs.get("template_id")
        try:
            template_id = int(template_id)
        except (TypeError, ValueError):
            return Response({"error": "Template id must be an integer"}, status=400)

        template = Template.objects.filter(id=template_id, org=org, is_active=True).first()
        if not template:
            return Response({"error": "Template not found"}, status=404)

        language = request.query_params.get("language")
        translations = TemplateTranslation.objects.filter(template=template, is_active=True)
        if language:
            translations = translations.filter(language__iexact=language)

        translation = (
            translations.select_related("template").prefetch_related("headers", "buttons").order_by("-id").first()
        )

        if not translation:
            if language:
                return Response({"error": "Translation not found for language"}, status=404)
            return Response({"error": "No active translations for template"}, status=404)

        data = TemplateTranslationDetailsSerializer(translation).data
        return Response(data)
