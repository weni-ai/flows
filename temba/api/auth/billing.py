from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission

from django.conf import settings
from django.contrib.auth.models import AnonymousUser


class BillingFixedAccessTokenAuthentication(BaseAuthentication):
    """
    Service-to-service auth via the shared BILLING_FIXED_ACCESS_TOKEN query param.

    Mirrors the inline token check previously used by ChannelProjectView and InternalContactView,
    but as a DRF authenticator so it can compose with InternalOIDCAuthentication.
    """

    def authenticate(self, request):
        token = request.query_params.get("token")
        if token is None:
            return None

        billing_token = getattr(settings, "BILLING_FIXED_ACCESS_TOKEN", None)
        if not billing_token or token != billing_token:
            raise AuthenticationFailed()

        request.billing_fixed_access_authenticated = True
        return (AnonymousUser(), None)


class HasBillingFixedAccessToken(BasePermission):
    def has_permission(self, request, view):
        return getattr(request, "billing_fixed_access_authenticated", False)


class BillingFixedAccessTokenViewMixin:
    authentication_classes = [BillingFixedAccessTokenAuthentication]
    permission_classes = [HasBillingFixedAccessToken]
