import requests
from rest_framework import status
from rest_framework.response import Response
from rest_framework.validators import UniqueValidator, qs_filter

from django.conf import settings


class UniqueForOrgValidator(UniqueValidator):
    """
    UniqueValidator requires a queryset at compile time but we always need to include org, which isn't known until
    request time. So this subclass reads org from the field's context and applies it to the queryset at runtime.
    """

    requires_context = True

    def __init__(self, queryset, ignore_case=True, message=None):
        lookup = "iexact" if ignore_case else "exact"

        super().__init__(queryset, message=message, lookup=lookup)

    def filter_queryset(self, value, queryset, field_name):
        queryset = super().filter_queryset(value, queryset, field_name)
        return qs_filter(queryset, **{"org": self.org})

    def __call__(self, value, serializer_field):
        self.org = serializer_field.context["org"]

        super().__call__(value, serializer_field)


class LambdaURLValidator:  # pragma: no cover
    def is_valid_url(self, sts_url):
        return sts_url.startswith("https://sts.amazonaws.com/?Action=GetCallerIdentity&") and (".." not in sts_url)

    def protected_resource(self, request):
        try:
            sts_url = request.headers.get("Authorization").split("Bearer ", 2)[1]
            if not self.is_valid_url(sts_url):
                return Response({"message": "Invalid sts"}, status=status.HTTP_400_BAD_REQUEST)

            response = requests.request(method="GET", url=sts_url, headers={"Accept": "application/json"}, timeout=30)

            identity_arn = response.json()["GetCallerIdentityResponse"]["GetCallerIdentityResult"]["Arn"]
            if identity_arn in settings.LAMBDA_ALLOWED_ROLES:
                return Response({"message": "Access granted!", "role": identity_arn})
            else:
                return Response({"message": "Invalid arn"}, status=status.HTTP_401_UNAUTHORIZED)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
