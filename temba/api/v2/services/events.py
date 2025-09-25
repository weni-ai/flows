import json
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


def fetch_events_for_org(user, **filters) -> List[Dict[str, Any]]:
    org = user.get_org()
    params = dict(filters)
    params["project"] = str(org.proj_uuid)
    events = dl_get_events(**params)
    return _parse_event_values(events)


def fetch_event_counts_for_org(user, **filters) -> List[Dict[str, Any]]:
    org = user.get_org()
    params = dict(filters)
    params["project"] = str(org.proj_uuid)
    events = dl_get_events_count_by_group(**params)
    return _parse_event_values(events)
