from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated

from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from .jwt_auth import JWTModuleAuthentication


class CourierFixedAccessTokenAuthentication(BaseAuthentication):
    """
    Service-to-service auth for Courier via shared COURIER_FIXED_ACCESS_TOKEN query param.
    """

    def authenticate(self, request):
        token = request.query_params.get("token")
        if token is None:
            return None

        courier_token = getattr(settings, "COURIER_FIXED_ACCESS_TOKEN", None)
        if not courier_token or token != courier_token:
            raise AuthenticationFailed()

        request.courier_fixed_access_authenticated = True
        return (AnonymousUser(), None)


class ConversionEventAuthentication(BaseAuthentication):
    """
    Accept Courier fixed token OR module JWT.
    Fixed token is checked first so Courier does not need a Bearer header.
    """

    def authenticate(self, request):
        courier_auth = CourierFixedAccessTokenAuthentication()
        courier_result = courier_auth.authenticate(request)
        if courier_result is not None:
            return courier_result

        jwt_auth = JWTModuleAuthentication()
        try:
            return jwt_auth.authenticate(request)
        except (AuthenticationFailed, NotAuthenticated):
            raise AuthenticationFailed("Missing or invalid authentication.")


class ConversionEventAuthMixin:
    authentication_classes = [ConversionEventAuthentication]
    permission_classes = []

    @property
    def project_uuid(self):
        return getattr(self.request, "project_uuid", None)

    @property
    def jwt_payload(self):
        return getattr(self.request, "jwt_payload", None)

    @property
    def courier_authenticated(self):
        return getattr(self.request, "courier_fixed_access_authenticated", False)
