import logging

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.utils.timesince import timesince

from temba.utils.celery import nonoverlapping_task

from .models import WAConversationHandover

logger = logging.getLogger(__name__)

TRIM_BATCH_SIZE = 1000


def _trim_eligible(trim_before):
    # created_on is the last write: Courier resets it on every upsert, while occurred_on can be days old
    return Q(consumed_on__isnull=False) | Q(created_on__lte=trim_before)


def _select_trim_ids(trim_before, limit):
    return list(
        WAConversationHandover.objects.filter(_trim_eligible(trim_before)).values_list("id", flat=True)[:limit]
    )


@nonoverlapping_task(track_started=True, name="trim_wa_conversation_handovers_task", use_watchdog=True)
def trim_wa_conversation_handovers_task():
    start = timezone.now()
    trim_before = start - settings.RETENTION_PERIODS["wa_conversation_handover"]
    num_deleted = 0

    while True:
        ids = _select_trim_ids(trim_before, TRIM_BATCH_SIZE)
        if not ids:
            break

        # eligibility is re-checked in the delete so a row Courier wrote to after selection is kept
        num_deleted += WAConversationHandover.objects.filter(_trim_eligible(trim_before), id__in=ids).delete()[0]

    logger.info(f"Deleted {num_deleted} wa conversation handovers in {timesince(start)}")
