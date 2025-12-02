import jwt
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from django.conf import settings
from django.contrib.auth.models import AnonymousUser


class OptionalJWTAuthentication(BaseAuthentication):
    """
    JWT authentication that plays well with other authenticators:
    - If no Bearer token is present, returns None (lets other auth methods run).
    - If Bearer token is present, validates with settings.JWT_PUBLIC_KEY and populates:
      request.jwt_payload and request.project_uuid (if present in payload).
    - Returns AnonymousUser since auth is token-based and not tied to a DB user.
    """

    def get_settings(self):
        return settings

    def get_jwt(self):
        return jwt

    def authenticate(self, request):
        auth_header = request.headers.get("Authorization", "")
        if not isinstance(auth_header, str) or not auth_header.startswith("Bearer "):
            return None

        public_key = getattr(self.get_settings(), "JWT_PUBLIC_KEY", None)
        if not public_key:
            # Not configured for JWT; allow other authenticators to run
            return None

        token = auth_header.split(" ", 1)[1]
        try:
            payload = self.get_jwt().decode(
                token,
                public_key,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )
        except (self.get_jwt().ExpiredSignatureError, self.get_jwt().InvalidTokenError):
            # Not a valid JWT for this auth; allow other authenticators to run
            return None

        request.jwt_payload = payload
        project_uuid = payload.get("project_uuid") or payload.get("project")
        channel_uuid = payload.get("channel_uuid") or payload.get("channel")
        if project_uuid:
            request.project_uuid = project_uuid
        if channel_uuid:
            request.channel_uuid = channel_uuid
        return (AnonymousUser(), None)


class BaseJWTAuthentication(BaseAuthentication):
    """
    Base class that handles the low-level mechanics of JWT validation:
    - Retrieves the Public Key.
    - Extracts the Bearer token from the header.
    - Decodes and validates the token signature/expiration.
    Returns the decoded payload if successful, or raises AuthenticationFailed.
    """

    def get_settings(self):
        return settings

    def get_jwt(self):
        return jwt

    def verify_and_decode_token(self, request):
        """
        Orchestrates the validation process and returns the payload.
        This method is meant to be called by subclasses.
        """
        public_key = getattr(self.get_settings(), "JWT_PUBLIC_KEY", None)
        if not public_key:
            raise AuthenticationFailed("JWT_PUBLIC_KEY not configured in settings.")

        auth_header = request.headers.get("Authorization", "")
        if not isinstance(auth_header, str) or not auth_header.startswith("Bearer "):
            raise AuthenticationFailed("Missing or invalid Authorization header.")

        token = auth_header.split(" ", 1)[1]
        try:
            payload = self.get_jwt().decode(
                token,
                public_key,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )
        except self.get_jwt().ExpiredSignatureError:
            raise AuthenticationFailed("Token expired.")
        except self.get_jwt().InvalidTokenError:
            raise AuthenticationFailed("Invalid token.")
        except Exception as e:
            raise AuthenticationFailed(f"Authentication error: {str(e)}")

        return payload

    def authenticate(self, request):
        """
        Base implementation. Can be used if you just want to validate the token
        without specific payload extraction requirements.
        """
        self.verify_and_decode_token(request)

        return (AnonymousUser(), None)


class RequiredJWTAuthentication(BaseJWTAuthentication):
    """
    Implementation that requires specific fields in the JWT payload.
    Uses the base class to validate the token mechanics, then checks for
    project/channel UUIDs.
    """

    def authenticate(self, request):
        payload = self.verify_and_decode_token(request)
        request.jwt_payload = payload

        project_uuid = payload.get("project_uuid")
        channel_uuid = payload.get("channel_uuid")

        if not project_uuid or not channel_uuid:
            raise AuthenticationFailed("project_uuid or channel_uuid not found in token payload.")

        if project_uuid:
            request.project_uuid = project_uuid
        if channel_uuid:
            request.channel_uuid = channel_uuid

        return (AnonymousUser(), None)


class JWTAuthMixinRequired:
    """
    Mixin for views that must require JWT (centralized, used across apps).
    Exposes request.project_uuid and request.jwt_payload when authenticated.
    """

    authentication_classes = [RequiredJWTAuthentication]
    permission_classes = []

    @property
    def project_uuid(self):
        return getattr(self.request, "project_uuid", None)

    @property
    def jwt_payload(self):
        return getattr(self.request, "jwt_payload", None)


class JWTAuthMixinOptional:
    """
    Mixin for views that can accept JWT OR other auth (non-blocking).
    """

    authentication_classes = [OptionalJWTAuthentication]
    permission_classes = []

    @property
    def project_uuid(self):
        return getattr(self.request, "project_uuid", None)

    @property
    def jwt_payload(self):
        return getattr(self.request, "jwt_payload", None)
