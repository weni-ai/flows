import jwt as jwt
from django.conf import settings as settings
from temba.api.auth.jwt import RequiredJWTAuthentication, JWTAuthMixinRequired
from temba.api.v2.permissions import HasValidJWT


class JWTModuleAuthentication(RequiredJWTAuthentication):
    def get_settings(self):
        return settings

    def get_jwt(self):
        return jwt


class JWTModuleAuthMixin(JWTAuthMixinRequired):
    authentication_classes = [JWTModuleAuthentication]
    permission_classes = [HasValidJWT]
