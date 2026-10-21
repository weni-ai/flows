"""
Harden weni-rp-apps endpoints that this app mounts but does not own.

OrgViewSet and TicketerQueuesEndpoint live in the weni package. Patching the
classes here takes effect on already-registered URLs because DRF looks up
action methods on the class at request time.
"""

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from weni.internal.models import TicketerQueue
from weni.internal.permissions import CanCommunicateInternally
from weni.orgs_api.views import OrgViewSet
from weni.ticketer_queues.serializers import TicketerQueueSerializer
from weni.ticketer_queues.views import TicketerQueuesEndpoint

from django.shortcuts import get_object_or_404

from temba.orgs.models import Org
from temba.tickets.models import Ticketer


def _is_trusted_internal(request, view) -> bool:
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return CanCommunicateInternally().has_permission(request, view) is True


def _org_for_privileged_action(view, request, uuid):
    org = get_object_or_404(Org, uuid=uuid)
    user = getattr(request, "user", None)
    if _is_trusted_internal(request, view):
        return org
    if user and getattr(user, "is_authenticated", False) and org.has_user(user):
        return org
    raise PermissionDenied()


def _patched_is_suspended(self, request, uuid=None):
    org = _org_for_privileged_action(self, request, uuid)
    org.is_suspended = bool(request.data.get("is_suspended"))
    org.save()
    from django.http import JsonResponse

    return JsonResponse(dict(is_suspended=org.is_suspended))


def _patched_suspend_flag(self, request, uuid=None):
    from django.http import JsonResponse

    from weni.orgs_api.serializers import FlagOrgSerializer

    org = _org_for_privileged_action(self, request, uuid)

    if request.method == "DELETE":
        if org.config.get("date_billing_expired"):
            org.config.pop("date_billing_expired")
        if org.config.get("date_org_will_suspend"):
            org.config.pop("date_org_will_suspend")
        org.save()
        return JsonResponse(data=dict(success=True), status=200)

    serializer = FlagOrgSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    for flag_name, date in serializer.data.items():
        org.config[flag_name] = date
    org.save()
    return JsonResponse(data=serializer.data, status=200)


def _patched_ticketer_queues_get(self, request, format=None):
    ticketer_uuid = request.query_params.get("ticketer_uuid")
    if ticketer_uuid is None:
        raise ValidationError("ticketer_uuid is required")

    try:
        ticketer = Ticketer.objects.get(uuid=ticketer_uuid, is_active=True)
    except Ticketer.DoesNotExist:
        return Response([], status=200)

    user = getattr(request, "user", None)
    if not _is_trusted_internal(request, self):
        if not (user and getattr(user, "is_authenticated", False) and ticketer.org.has_user(user)):
            raise PermissionDenied()

    queues = TicketerQueue.objects.filter(ticketer=ticketer, is_active=True)
    serializer = TicketerQueueSerializer(queues, many=True)
    return Response(serializer.data)


OrgViewSet.is_suspended = _patched_is_suspended
OrgViewSet.suspend_flag = _patched_suspend_flag
TicketerQueuesEndpoint.get = _patched_ticketer_queues_get
