import os

from django.http import HttpResponseForbidden
from django.http import HttpResponse
from django_prometheus.exports import ExportToDjangoView


def metrics_view(request):
    auth_token = request.headers.get("Authorization")
    prometheus_auth_token = settings.PROMETHEUS_AUTH_TOKEN

    expected_token = f"Bearer {prometheus_auth_token}"
    if not auth_token or auth_token != expected_token:
        return HttpResponseForbidden("Acesso negado")

    return ExportToDjangoView(request)