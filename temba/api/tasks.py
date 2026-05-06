from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from temba.orgs.models import Org
from temba.utils import chunk_list
from temba.utils.celery import nonoverlapping_task

from .models import WebHookEvent

User = get_user_model()


@shared_task(track_started=True, name="whatsapp_broadcast_deferred")
def whatsapp_broadcast_deferred_task(org_id, user_id, payload):
    """
    Validates and persists a WhatsApp broadcast using the same rules as InternalWhatsappBroadcastsEndpoint.

    Intended for fire-and-forget HTTP 202 semantics; failures appear in worker logs/Celery result.
    """
    from temba.api.v2.serializers import WhatsappBroadcastWriteSerializer

    org = Org.objects.get(pk=org_id)
    user = User.objects.get(pk=user_id)

    with transaction.atomic():
        serializer = WhatsappBroadcastWriteSerializer(
            data=payload,
            context={"request": None, "org": org, "user": user},
        )
        serializer.is_valid(raise_exception=True)
        broadcast = serializer.save()
        return broadcast.pk


@nonoverlapping_task(track_started=True, name="trim_webhook_event_task")
def trim_webhook_event_task():
    """
    Trims old webhook events
    """

    if settings.RETENTION_PERIODS["webhookevent"]:
        trim_before = timezone.now() - settings.RETENTION_PERIODS["webhookevent"]
        event_ids = WebHookEvent.objects.filter(created_on__lte=trim_before).values_list("id", flat=True)
        for batch in chunk_list(event_ids, 1000):
            WebHookEvent.objects.filter(id__in=batch).delete()
