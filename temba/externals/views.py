from rest_framework import status
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView


class GetExternalTypes(APIView):
    authentication_classes = []
    permission_classes = []
    pagination_class = None
    renderer_classes = [JSONRenderer]
    throttle_classes = []

    def get(self, request, slug=None):
        from temba.externals.types import TYPES

        external_type = TYPES.get(slug)

        if external_type is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        actions = external_type.get_actions()
        return Response(actions, status=status.HTTP_200_OK)
