import logging

from django.conf import settings
from django.utils import timezone

from temba.utils.celery import nonoverlapping_task

from .layer_validation import post_report_to_slack, validate_layers

logger = logging.getLogger(__name__)


@nonoverlapping_task(track_started=True, name="validate_datalake_layers_task", lock_timeout=3600)
def validate_datalake_layers_task():
    """
    Compares the previous local day's bronze and silver event counts of the configured projects and posts a
    summary to Slack
    """

    if not settings.DATALAKE_VALIDATION_SLACK_WEBHOOK_URL:
        logger.warning("DATALAKE_VALIDATION_SLACK_WEBHOOK_URL is not set, skipping datalake layer validation")
        return

    if not settings.DATALAKE_VALIDATION_PROJECTS:
        logger.warning("DATALAKE_VALIDATION_PROJECTS is not set, skipping datalake layer validation")
        return

    reports = validate_layers(timezone.now(), settings.DATALAKE_VALIDATION_PROJECTS)
    if reports:
        post_report_to_slack(reports)
