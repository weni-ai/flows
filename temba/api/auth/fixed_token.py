import hmac

from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated

from django.conf import settings


def require_fixed_query_token(request, setting_name: str) -> str:
    """
    Authenticate a service-to-service caller via `?token=`.

    An empty or unset setting never authenticates: `?token=` must not succeed.
    """
    token = request.query_params.get("token")
    if token is None:
        raise NotAuthenticated()

    expected = getattr(settings, setting_name, None) or ""
    provided = str(token)
    expected = str(expected)
    if not expected or len(provided) != len(expected) or not hmac.compare_digest(provided, expected):
        raise AuthenticationFailed()

    return expected
