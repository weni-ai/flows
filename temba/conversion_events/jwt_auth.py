import jwt
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from django.conf import settings
from django.contrib.auth.models import AnonymousUser


class JWTModuleAuthentication(BaseAuthentication):
    """
    DRF authentication class for JWT tokens.
    - Validates signature using the public key from settings
    - Extracts 'project_uuid' from payload and injects it into the request
    """

    def authenticate(self, request):
        public_key = getattr(settings, "JWT_PUBLIC_KEY", None)
        if not public_key:
            raise AuthenticationFailed("JWT_PUBLIC_KEY not configured in settings.")

        auth_header = request.headers.get("Authorization", "")
        if not isinstance(auth_header, str) or not auth_header.startswith("Bearer "):
            raise AuthenticationFailed("Missing or invalid Authorization header.")

        token = auth_header.split(" ", 1)[1]
        try:
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed("Token expired.")
        except jwt.InvalidTokenError:
            raise AuthenticationFailed("Invalid token.")

        project_uuid = payload.get("project_uuid")
        if not project_uuid:
            raise AuthenticationFailed("project_uuid not found in token payload.")

        request.project_uuid = project_uuid
        request.jwt_payload = payload
        return (AnonymousUser(), None)  # No user associated


class JWTModuleAuthMixin:
    """
    Mixin for easy access to project_uuid and JWT payload.
    """

    authentication_classes = [JWTModuleAuthentication]
    permission_classes = []

    @property
    def project_uuid(self):
        return getattr(self.request, "project_uuid", None)

    @property
    def jwt_payload(self):
        return getattr(self.request, "jwt_payload", None)
