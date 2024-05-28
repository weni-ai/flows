from rest_framework.renderers import JSONRenderer


class APIViewMixin:
    authentication_classes = []
    permission_classes = []
    pagination_class = None
    renderer_classes = [JSONRenderer]
    throttle_classes = []
