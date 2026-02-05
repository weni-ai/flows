import logging
from datetime import timedelta

from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ConnectionError, ConnectionTimeout, TransportError

from django.conf import settings
from django.utils import timezone

from celery import shared_task

from temba.contacts.models import URN, ContactURN, ExportContactsTask
from temba.contacts.tasks import export_contacts_task
from temba.flows.models import ExportFlowResultsTask
from temba.flows.tasks import export_flow_results_task
from temba.msgs.models import ExportMessagesTask
from temba.msgs.tasks import export_messages_task
from temba.utils.celery import nonoverlapping_task

from .models import CreditAlert, Invitation, Org, OrgActivity, TopUpCredits, UniqueContactCount


@shared_task(track_started=True, name="send_invitation_email_task")
def send_invitation_email_task(invitation_id):
    invitation = Invitation.objects.get(pk=invitation_id)
    invitation.send_email()


@shared_task(track_started=True, name="send_alert_email_task")
def send_alert_email_task(alert_id):
    alert = CreditAlert.objects.get(pk=alert_id)
    alert.send_email()


@shared_task(track_started=True, name="check_credits_task")
def check_credits_task():  # pragma: needs cover
    CreditAlert.check_org_credits()


@shared_task(track_started=True, name="check_topup_expiration_task")
def check_topup_expiration_task():
    CreditAlert.check_topup_expiration()


@shared_task(track_started=True, name="apply_topups_task")
def apply_topups_task(org_id):
    org = Org.objects.get(id=org_id)
    org.apply_topups()


@shared_task(track_started=True, name="normalize_contact_tels_task")
def normalize_contact_tels_task(org_id):
    org = Org.objects.get(id=org_id)

    # do we have an org-level country code? if so, try to normalize any numbers not starting with +
    if org.default_country_code:
        urns = ContactURN.objects.filter(org=org, scheme=URN.TEL_SCHEME).exclude(path__startswith="+").iterator()
        for urn in urns:
            urn.ensure_number_normalization(org.default_country_code)


@nonoverlapping_task(track_started=True, name="squash_topupcredits", lock_key="squash_topupcredits", lock_timeout=7200)
def squash_topupcredits():
    TopUpCredits.squash()


@nonoverlapping_task(track_started=True, name="resume_failed_tasks", lock_key="resume_failed_tasks", lock_timeout=7200)
def resume_failed_tasks():
    now = timezone.now()
    window = now - timedelta(hours=1)

    contact_exports = ExportContactsTask.objects.filter(modified_on__lte=window).exclude(
        status__in=[ExportContactsTask.STATUS_COMPLETE, ExportContactsTask.STATUS_FAILED]
    )
    for contact_export in contact_exports:
        export_contacts_task.delay(contact_export.pk)

    flow_results_exports = ExportFlowResultsTask.objects.filter(modified_on__lte=window).exclude(
        status__in=[ExportFlowResultsTask.STATUS_COMPLETE, ExportFlowResultsTask.STATUS_FAILED]
    )
    for flow_results_export in flow_results_exports:
        export_flow_results_task.delay(flow_results_export.pk)

    msg_exports = ExportMessagesTask.objects.filter(modified_on__lte=window).exclude(
        status__in=[ExportMessagesTask.STATUS_COMPLETE, ExportMessagesTask.STATUS_FAILED]
    )
    for msg_export in msg_exports:
        export_messages_task.delay(msg_export.pk)


@nonoverlapping_task(track_started=True, name="update_org_activity_task")
def update_org_activity(now=None):
    now = now if now else timezone.now()
    OrgActivity.update_day(now)


@nonoverlapping_task(
    track_started=True, name="suspend_topup_orgs_task", lock_key="suspend_topup_orgs_task", lock_timeout=7200
)
def suspend_topup_orgs_task():
    # for every org on a topup plan that isn't suspended, check they have credits, if not, suspend them
    for org in Org.objects.filter(uses_topups=True, is_active=True, is_suspended=False):
        if org.get_credits_remaining() <= 0:
            org.clear_credit_cache()
            if org.get_credits_remaining() <= 0:
                org.is_suspended = True
                org.plan_end = timezone.now()
                org.save(update_fields=["is_suspended", "plan_end"])


@nonoverlapping_task(track_started=True, name="delete_orgs_task", lock_key="delete_orgs_task", lock_timeout=7200)
def delete_orgs_task():
    # for each org that was released over 7 days ago, delete it for real
    week_ago = timezone.now() - timedelta(days=Org.DELETE_DELAY_DAYS)
    for org in Org.objects.filter(is_active=False, released_on__lt=week_ago, deleted_on=None):
        try:
            org.delete()
        except Exception:  # pragma: no cover
            logging.exception(f"exception while deleting {org.name}")


logger = logging.getLogger(__name__)

# Retry settings for individual org processing
ORG_MAX_RETRIES = 3
ORG_RETRY_BACKOFF = 5  # seconds


def _fetch_unique_contact_count_for_org(client, org, day, next_day):
    """
    Fetches unique contact count from Elasticsearch for a single org with retries.

    Args:
        client: Elasticsearch client instance
        org: Org instance
        day: Target date
        next_day: Day after target date (for range query)

    Returns:
        int: The count of unique contacts

    Raises:
        Exception: If all retries are exhausted
    """
    import time

    last_exception = None

    for attempt in range(ORG_MAX_RETRIES):
        try:
            response = client.count(
                index="contacts",
                body={
                    "query": {
                        "bool": {
                            "filter": [
                                {"term": {"org_id": org.id}},
                                {
                                    "range": {
                                        "last_seen_on": {
                                            "gte": f"{day}T00:00:00",
                                            "lt": f"{next_day}T00:00:00",
                                            "time_zone": "+00:00",
                                        }
                                    }
                                },
                            ]
                        }
                    }
                },
            )
            return response.get("count", 0)

        except (ConnectionError, ConnectionTimeout, TransportError) as e:
            # Connection errors - retry with backoff
            last_exception = e
            if attempt < ORG_MAX_RETRIES - 1:
                sleep_time = ORG_RETRY_BACKOFF * (2**attempt)  # exponential backoff
                logger.warning(
                    f"Connection error for org {org.id} ({org.name}), "
                    f"attempt {attempt + 1}/{ORG_MAX_RETRIES}. Retrying in {sleep_time}s..."
                )
                time.sleep(sleep_time)
            else:
                raise last_exception

        except Exception as e:
            # Other errors - retry with backoff as well
            last_exception = e
            if attempt < ORG_MAX_RETRIES - 1:
                sleep_time = ORG_RETRY_BACKOFF * (2**attempt)
                logger.warning(
                    f"Error for org {org.id} ({org.name}): {e}, "
                    f"attempt {attempt + 1}/{ORG_MAX_RETRIES}. Retrying in {sleep_time}s..."
                )
                time.sleep(sleep_time)
            else:
                raise last_exception

    raise last_exception


@shared_task(
    bind=True,
    name="update_unique_contact_counts",
    autoretry_for=(ConnectionError, ConnectionTimeout, TransportError),
    retry_backoff=60,
    retry_backoff_max=3600,
    max_retries=5,
)
def update_unique_contact_counts(self, target_date=None):
    """
    Fetches unique contact counts from Elasticsearch for all active orgs.

    Runs daily at 5am UTC, fetching data for the previous day.
    A contact is counted as "unique" for a day if their last_seen_on falls within that day.

    Each org is processed with its own retry logic (3 attempts with exponential backoff).
    If all retries fail for an org, the error is sent to Sentry for monitoring.

    Args:
        target_date: Optional date string (YYYY-MM-DD) to fetch counts for.
                    Defaults to yesterday (UTC).
    """
    from sentry_sdk import capture_exception

    if not settings.ELASTICSEARCH_URL:
        logger.warning("ELASTICSEARCH_URL not configured, skipping unique contact counts update")
        return

    # Determine the target date (default to yesterday UTC)
    if target_date:
        from datetime import datetime

        day = datetime.strptime(target_date, "%Y-%m-%d").date()
    else:
        now = timezone.now()
        day = (now - timedelta(days=1)).date()

    next_day = day + timedelta(days=1)

    logger.info(f"Updating unique contact counts for {day}")

    # Initialize Elasticsearch client
    client = Elasticsearch(
        settings.ELASTICSEARCH_URL,
        timeout=int(settings.ELASTICSEARCH_TIMEOUT_REQUEST),
    )

    # Get all active orgs
    orgs = Org.objects.filter(is_active=True).only("id", "name")
    success_count = 0
    failed_orgs = []

    for org in orgs:
        try:
            count = _fetch_unique_contact_count_for_org(client, org, day, next_day)

            # Update or create the count record
            UniqueContactCount.objects.update_or_create(
                org=org,
                day=day,
                defaults={"count": count},
            )

            success_count += 1

        except Exception as e:
            # All retries exhausted - log to Sentry and continue with other orgs
            logger.error(
                f"Failed to fetch unique contact count for org {org.id} ({org.name}) "
                f"after {ORG_MAX_RETRIES} retries: {e}"
            )
            capture_exception(e)
            failed_orgs.append({"org_id": org.id, "org_name": org.name, "error": str(e)})
            continue

    # Log summary
    if failed_orgs:
        logger.error(
            f"Unique contact counts update for {day} completed with errors. "
            f"Success: {success_count}, Failed: {len(failed_orgs)}. "
            f"Failed orgs: {[f['org_id'] for f in failed_orgs]}"
        )
    else:
        logger.info(f"Unique contact counts update completed successfully for {day}. Total: {success_count}")
