import logging

from django.conf import settings
from django.utils import timezone

from temba.utils import chunk_list
from temba.utils.celery import nonoverlapping_task

from .models import HTTPLog


logger = logging.getLogger(__name__)


@nonoverlapping_task(track_started=True, name="trim_http_logs_task")
def trim_http_logs_task():
    trim_before = timezone.now() - settings.RETENTION_PERIODS["httplog"]

    logger.info(f"[ Trim HTTPLogs ] Clearing all HTTPLogs before: {trim_before}")

    ids = HTTPLog.objects.filter(created_on__lte=trim_before).values_list("id", flat=True)

    logger.info("[ Trim HTTPLogs ] All IDs were returned!")

    chunk_count = 1000

    for chunk in chunk_list(ids, 1000):
        logger.info(f"[ Trim HTTPLogs ] Chunk count: {chunk_count}")
        HTTPLog.objects.filter(id__in=chunk).delete()
        chunk_count += 1000

    logger.info("[ Trim HTTPLogs ] The task was successfully completed!")
