from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from weni.internal.authenticators import InternalOIDCAuthentication
from weni.internal.permissions import CanCommunicateInternally

from temba.api.v2.internals.views import APIViewMixin
from temba.api.v2.permissions import IsUserInOrg
from temba.api.v2.views_base import DefaultLimitOffsetPagination

from .serializers import CtwaReferralSourceSerializer, ListCtwaReferralSourceQuerySerializer
from .usecases import ListCtwaReferralSourcesDTO, ListCtwaReferralSourcesUseCase, ProjectNotFoundError


class CtwaReferralSourceListView(APIViewMixin, APIView):
    authentication_classes = [InternalOIDCAuthentication]
    permission_classes = [IsAuthenticated & (CanCommunicateInternally | IsUserInOrg)]

    def get(self, request: Request):
        serializer = ListCtwaReferralSourceQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        dto = ListCtwaReferralSourcesDTO(
            project_uuid=str(serializer.validated_data["project_uuid"]),
            source_type=serializer.validated_data.get("source_type"),
            after=serializer.validated_data.get("after"),
            before=serializer.validated_data.get("before"),
        )

        try:
            queryset = ListCtwaReferralSourcesUseCase().execute(dto)
        except ProjectNotFoundError:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)

        paginator = DefaultLimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, self)
        return paginator.get_paginated_response(CtwaReferralSourceSerializer(page, many=True).data)
