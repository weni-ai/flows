import json
from datetime import timedelta, timezone
from typing import Any, Dict, Iterable, List

from weni_datalake_sdk.clients.redshift.events import (
    get_events as dl_get_events,
    get_events_count_by_group as dl_get_events_count_by_group,
)


def _parse_event_values(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    processed: List[Dict[str, Any]] = []
    for event in events:
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
    return processed


def _normalize_datetime_params(params: Dict[str, Any]) -> None:
    """
    Normalize datetime parameters for Redshift queries.
    
    Converts datetime objects to UTC ISO format strings and adjusts date_end
    by subtracting 1 second to avoid capturing events from the next day
    (since Redshift BETWEEN is inclusive on both ends).
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
        adjusted_end = dt_end - timedelta(seconds=1)
        params["date_end"] = adjusted_end.isoformat()


def fetch_events_for_org(user, **filters) -> List[Dict[str, Any]]:
    org = user.get_org()
    params = dict(filters)
    params["project"] = str(org.proj_uuid)
    
    _normalize_datetime_params(params)
    
    events = dl_get_events(**params)
    return _parse_event_values(events)


def fetch_event_counts_for_org(user, **filters) -> List[Dict[str, Any]]:
    org = user.get_org()
    params = dict(filters)
    params["project"] = str(org.proj_uuid)
    
    _normalize_datetime_params(params)
    
    events = dl_get_events_count_by_group(**params)
    return _parse_event_values(events)
