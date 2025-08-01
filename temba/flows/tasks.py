import logging
from collections import defaultdict
from datetime import datetime, timedelta

import iso8601
import pytz
from django_redis import get_redis_connection

from django.conf import settings
from django.utils import timezone
from django.utils.timesince import timesince

from celery import shared_task

from temba import mailroom
from temba.utils import chunk_list
from temba.utils.celery import nonoverlapping_task

from .models import (
    ExportFlowResultsTask,
    FlowCategoryCount,
    FlowNodeCount,
    FlowPathCount,
    FlowPathRecentRun,
    FlowRevision,
    FlowRun,
    FlowRunCount,
    FlowSession,
    FlowStart,
    FlowStartCount,
)

FLOW_TIMEOUT_KEY = "flow_timeouts_%y_%m_%d"
logger = logging.getLogger(__name__)


@shared_task(track_started=True, name="update_run_expirations_task")
def update_run_expirations_task(flow_id):
    """
    Update all of our current run expirations according to our new expiration period
    """
    for run in FlowRun.objects.filter(flow_id=flow_id, is_active=True):
        if run.path:
            last_arrived_on = iso8601.parse_date(run.path[-1]["arrived_on"])
            run.update_expiration(last_arrived_on)


@shared_task(track_started=True, name="export_flow_results_task")
def export_flow_results_task(export_id):
    """
    Export a flow to a file and e-mail a link to the user
    """
    ExportFlowResultsTask.objects.select_related("org", "created_by").get(id=export_id).perform()


@nonoverlapping_task(track_started=True, name="squash_flowcounts", lock_timeout=7200, use_watchdog=True)
def squash_flowcounts():
    FlowNodeCount.squash()
    FlowRunCount.squash()
    FlowPathRecentRun.prune()
    FlowStartCount.squash()
    FlowPathCount.squash()


@nonoverlapping_task(track_started=True, name="squash_flow_category_counts", lock_timeout=7200)
def squash_flow_category_counts():
    FlowCategoryCount.squash()


@nonoverlapping_task(track_started=True, name="trim_flow_revisions")
def trim_flow_revisions():
    start = timezone.now()

    # get when the last time we trimmed was
    r = get_redis_connection()
    last_trim = r.get(FlowRevision.LAST_TRIM_KEY)
    if not last_trim:
        last_trim = 0

    last_trim = datetime.utcfromtimestamp(int(last_trim)).astimezone(pytz.utc)
    count = FlowRevision.trim(last_trim)

    r.set(FlowRevision.LAST_TRIM_KEY, int(timezone.now().timestamp()))

    elapsed = timesince(start)
    logger.info(f"Trimmed {count} flow revisions since {last_trim} in {elapsed}")


@nonoverlapping_task(track_started=True, name="interrupt_flow_sessions")
def interrupt_flow_sessions():
    """
    Write ended_on in session not expired in 90 days
    """
    before = timezone.now() - timedelta(days=90)
    num_interrupted = 0

    sessions_list = defaultdict(list)
    sessions = (
        FlowSession.objects.filter(created_on__lte=before, status=FlowSession.STATUS_WAITING)
        .only("id", "org")
        .select_related("org")
        .order_by("id")
    )

    for session in sessions:
        sessions_list[session.org].append(session)

    for org, sessions in sessions_list.items():
        for batch in chunk_list(sessions, 100):
            mailroom.queue_interrupt(org, sessions=batch)
            num_interrupted += len(sessions)

    return {"sessions interrupted": num_interrupted}


@nonoverlapping_task(track_started=True, name="trim_flow_sessions_and_starts")
def trim_flow_sessions_and_starts():
    trim_flow_sessions()
    trim_flow_starts()


def trim_flow_sessions():
    """
    Cleanup old flow sessions
    """
    trim_before = timezone.now() - settings.RETENTION_PERIODS["flowsession"]
    num_deleted = 0
    start = timezone.now()

    logger.info(f"Deleting flow sessions which ended before {trim_before.isoformat()}...")

    while True:
        session_ids = list(FlowSession.objects.filter(ended_on__lte=trim_before).values_list("id", flat=True)[:100])
        if not session_ids:
            break

        # detach any flows runs that belong to these sessions
        FlowRun.objects.filter(session_id__in=session_ids).update(session_id=None)

        FlowSession.objects.filter(id__in=session_ids).delete()
        num_deleted += len(session_ids)

        if num_deleted % 10000 == 0:  # pragma: no cover
            print(f" > Deleted {num_deleted} flow sessions")

    logger.info(f"Deleted {num_deleted} flow sessions in {timesince(start)}")


def trim_flow_starts_base(filter_kwargs, exclude_kwargs, retention_period_key, log_name):
    """
    Cleanup completed flow starts based on given filter criteria and retention period.
    """
    trim_before = timezone.now() - settings.RETENTION_PERIODS[retention_period_key]
    num_deleted = 0
    start = timezone.now()

    logger.info(f"Deleting {log_name} flow starts created before {trim_before.isoformat()}")

    while True:
        query = FlowStart.objects.filter(
            **filter_kwargs,
            status__in=(FlowStart.STATUS_COMPLETE, FlowStart.STATUS_FAILED),
            modified_on__lte=trim_before,
        )

        if exclude_kwargs:
            query = query.exclude(**exclude_kwargs)

        start_ids = list(query.values_list("id", flat=True)[:1000])

        if not start_ids:
            break

        run_ids = FlowRun.objects.filter(start_id__in=start_ids).values_list("id", flat=True)[:100000]
        while len(run_ids) > 0:
            for chunk in chunk_list(run_ids, 1000):
                FlowRun.objects.filter(id__in=chunk).update(start_id=None)

            run_ids = FlowRun.objects.filter(start_id__in=start_ids).values_list("id", flat=True)[:100000]

        FlowStart.contacts.through.objects.filter(flowstart_id__in=start_ids).delete()
        FlowStart.groups.through.objects.filter(flowstart_id__in=start_ids).delete()
        FlowStartCount.objects.filter(start_id__in=start_ids).delete()
        FlowStart.objects.filter(id__in=start_ids).delete()
        num_deleted += len(start_ids)

        if num_deleted % 10000 == 0:  # pragma: no cover
            logger.debug(f" > Deleted {num_deleted} {log_name} flow starts")

    logger.info(f"Deleted {num_deleted} {log_name} flow starts in {timesince(start)}")


def trim_flow_starts():
    """
    Cleanup completed non-user created flow starts
    """
    trim_flow_starts_base(
        filter_kwargs={"start_type": FlowStart.TYPE_API},
        exclude_kwargs={},
        retention_period_key="flowstart",
        log_name="non-user created",
    )


@nonoverlapping_task(track_started=True, name="trim_all_flow_starts")
def trim_all_flow_starts():
    """
    Cleanup completed flow starts
    """
    trim_flow_starts_base(
        filter_kwargs={},
        exclude_kwargs={"start_type": FlowStart.TYPE_API},
        retention_period_key="all_flowstart",
        log_name="all",
    )
