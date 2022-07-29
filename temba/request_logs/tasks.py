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

    deleted_count = 0

    while True:
        http_log_ids = HTTPLog.objects.filter(created_on__lte=trim_before).values_list("id", flat=True)[:10]

        logger.info(f"[ Trim HTTPLogs ] 10 logs were filtered and will be deleted")

        if not http_log_ids:
            break

        HTTPLog.objects.filter(id__in=http_log_ids).delete()
        deleted_count += 10

        logger.info(f"[ Trim HTTPLogs ] Deleted {deleted_count} HTTPLogs")

    logger.info(f"[ Trim HTTPLogs ] The task was successfully completed! {deleted_count} HTTPLog were deleted!")
