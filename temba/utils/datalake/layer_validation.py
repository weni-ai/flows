import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from weni_datalake_sdk.clients.redshift.events import (
    get_events_count as dl_get_events_count,
    get_events_silver_count as dl_get_events_silver_count,
)

from django.conf import settings

from temba.orgs.models import Org

logger = logging.getLogger(__name__)

DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
NEXUS_EVENT_NAME = "weni_nexus_data"

# events of a day only reach the bronze table after the project's local midnight
VALIDATION_LOCAL_HOUR = 2

# silver table -> filters that select the same events in the bronze table
LAYER_CHECKS: Dict[str, Dict[str, str]] = {
    "conversation_classification": {"event_name": NEXUS_EVENT_NAME, "key": "conversation_classification"},
}


@dataclass
class TableResult:
    table: str
    bronze: Optional[int] = None
    silver: Optional[int] = None
    error: bool = False

    @property
    def status(self) -> str:
        if self.error:
            return "ERROR"
        return "OK" if self.bronze == self.silver else "DIVERGENT"


@dataclass
class ProjectReport:
    org_name: str
    project_uuid: str
    timezone: str
    day: date
    results: List[TableResult] = field(default_factory=list)

    @property
    def has_problems(self) -> bool:
        return any(result.status != "OK" for result in self.results)


def _as_utc_string(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(DATE_FORMAT)


def previous_local_day_window(now: datetime, tz) -> Tuple[date, str, str]:
    day = now.astimezone(tz).date() - timedelta(days=1)
    start = tz.localize(datetime.combine(day, time.min))
    end = tz.localize(datetime.combine(day + timedelta(days=1), time.min))
    return day, _as_utc_string(start), _as_utc_string(end - timedelta(seconds=1))


def _parse_count(result: Any) -> int:
    if isinstance(result, list) and result and isinstance(result[0], dict):
        return int(result[0].get("count") or 0)
    return 0


def _active_orgs_by_project(project_uuids: List[str]) -> Dict[str, Org]:
    valid_uuids = []
    for project_uuid in project_uuids:
        try:
            valid_uuids.append(str(uuid.UUID(project_uuid)))
        except ValueError:
            logger.error("Datalake layer validation skipped invalid project uuid %s", project_uuid)

    orgs = Org.objects.filter(is_active=True, proj_uuid__in=valid_uuids).only("id", "name", "proj_uuid", "timezone")
    orgs_by_project = {str(org.proj_uuid): org for org in orgs}

    for project_uuid in valid_uuids:
        if project_uuid not in orgs_by_project:
            logger.error("Datalake layer validation found no active org for project %s", project_uuid)

    return orgs_by_project


def _check_project(org: Org, day: date, date_start: str, date_end: str) -> ProjectReport:
    project_uuid = str(org.proj_uuid)
    report = ProjectReport(org_name=org.name, project_uuid=project_uuid, timezone=str(org.timezone), day=day)

    for table, filters in LAYER_CHECKS.items():
        params = {"project": project_uuid, "date_start": date_start, "date_end": date_end, **filters}
        try:
            bronze = _parse_count(dl_get_events_count(**params))
            silver = _parse_count(dl_get_events_silver_count(**params, table=table))
        except Exception as e:
            logger.error("Datalake layer validation failed for project %s table %s: %s", project_uuid, table, e)
            report.results.append(TableResult(table, error=True))
            continue

        report.results.append(TableResult(table, bronze=bronze, silver=silver))

    return report


def validate_layers(now: datetime, project_uuids: List[str]) -> List[ProjectReport]:
    """
    Validates the previous local day of each project whose local time is in the validation hour
    """

    reports = []
    for org in _active_orgs_by_project(project_uuids).values():
        if now.astimezone(org.timezone).hour != VALIDATION_LOCAL_HOUR:
            continue

        day, date_start, date_end = previous_local_day_window(now, org.timezone)
        reports.append(_check_project(org, day, date_start, date_end))

    return reports


def _format_result(result: TableResult) -> str:
    if result.error:
        return f"• {result.table}: ERROR"

    diff = result.silver - result.bronze
    diff_text = f" ({diff:+d})" if diff else ""
    return f"• {result.table}: bronze={result.bronze} silver={result.silver}{diff_text} {result.status}"


def format_report(reports: List[ProjectReport]) -> str:
    with_problems = sum(1 for report in reports if report.has_problems)
    lines = [
        "*Datalake bronze x silver*",
        f"Projects checked: {len(reports)} | With problems: {with_problems}",
    ]

    for report in reports:
        lines += ["", f"*{report.org_name}* (`{report.project_uuid}`) | {report.day.isoformat()} ({report.timezone})"]
        lines += [_format_result(result) for result in report.results]

    return "\n".join(lines)


def post_report_to_slack(reports: List[ProjectReport]) -> None:
    response = requests.post(
        settings.DATALAKE_VALIDATION_SLACK_WEBHOOK_URL, json={"text": format_report(reports)}, timeout=10
    )
    response.raise_for_status()
