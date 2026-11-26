from weni.internal.authenticators import InternalOIDCAuthentication

from temba.api.v2.validators import LambdaURLValidator


class InternalOIDCExceptLambdaAuthentication(InternalOIDCAuthentication):
    """
    Lambda callers send their STS caller-identity URL as the bearer value. Forwarding it to the identity
    provider would reject them with 401 before HasValidLambdaIdentity runs, so those requests are skipped.
    """

    def authenticate(self, request):
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer ") and LambdaURLValidator().is_valid_url(auth_header.split(" ", 1)[1]):
            return None
        return super().authenticate(request)
