import json
from datetime import timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from weni_datalake_sdk.clients.redshift.events import (
    get_events as dl_get_events,
    get_events_silver as dl_get_events_silver,
    get_events_count_by_group as dl_get_events_count_by_group,
    get_events_count_by_group_silver as dl_get_events_count_by_group_silver,
)


def _parse_event_values(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    processed: List[Dict[str, Any]] = []
    for event in events:
        try:
            processed_event: Dict[str, Any] = {}
            for key, value in event.items():
                if isinstance(value, str):
                    try:
                        processed_event[key] = json.loads(value)
                    except (json.JSONDecodeError, TypeError):
                        processed_event[key] = value
                else:
                    processed_event[key] = value
            processed.append(processed_event)
        except Exception as e:
            # Log but don't skip the event - add it as-is
            print(f"Warning: Error parsing event, adding as-is: {e}")
            processed.append(event)
    return processed


def _normalize_datetime_params(params: Dict[str, Any]) -> None:
    """
    Normalize datetime parameters for Redshift queries.

    Converts datetime objects to UTC ISO format strings.
    """
    if "date_start" in params and hasattr(params["date_start"], "isoformat"):
        dt_start = params["date_start"]
        if dt_start.tzinfo is not None:
            dt_start = dt_start.astimezone(timezone.utc)
        params["date_start"] = dt_start.isoformat()

    if "date_end" in params and hasattr(params["date_end"], "isoformat"):
        dt_end = params["date_end"]
        if dt_end.tzinfo is not None:
            dt_end = dt_end.astimezone(timezone.utc)
        params["date_end"] = dt_end.isoformat()


def _prepare_datalake_params(user, filters: Dict[str, Any]) -> Tuple[Dict[str, Any], bool, Optional[str]]:
    """
    Prepares common parameters for datalake calls and extracts control flags.
    Returns (base_params, silver_flag, table_name)
    """
    org = user.get_org()
    params = dict(filters)
    params["project"] = str(org.proj_uuid)

    _normalize_datetime_params(params)

    base_params = {k: v for k, v in params.items() if k not in ("silver", "table")}
    return base_params, bool(params.get("silver")), params.get("table")


def _fetch_by_flag(
    base_params: Dict[str, Any],
    silver: bool,
    table: Optional[str],
    std_fn: Callable[..., Iterable[Dict[str, Any]]],
    silver_fn: Callable[..., Iterable[Dict[str, Any]]],
) -> Iterable[Dict[str, Any]]:
    if silver:
        params = dict(base_params)
        if table is not None:
            params["table"] = table
        return silver_fn(**params)
    return std_fn(**base_params)


def fetch_events_for_org(user, **filters) -> List[Dict[str, Any]]:
    base_params, silver, table = _prepare_datalake_params(user, filters)
    events = _fetch_by_flag(base_params, silver, table, dl_get_events, dl_get_events_silver)
    return _parse_event_values(events)


def fetch_event_counts_for_org(user, **filters) -> List[Dict[str, Any]]:
    base_params, silver, table = _prepare_datalake_params(user, filters)
    counts = _fetch_by_flag(
        base_params, silver, table, dl_get_events_count_by_group, dl_get_events_count_by_group_silver
    )
    return _parse_event_values(counts)
