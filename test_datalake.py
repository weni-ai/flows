import json
from weni_datalake_sdk.clients.redshift.events import get_events_silver


kwargs = {
    "project": "19f91ba7-185b-4d13-916f-b2f38e887dd2",
    "event_name": "weni_nexus_data",
    "key": "conversation_classification",
    "table": "conversation_classification",
    "date_start": "2026-01-30T03:00:00Z",
    "date_end": "2026-01-31T202:59:59Z",
}


def get():
    events = get_events_silver(**kwargs)
    return events


def get_types(events):
    resolved = []
    unresolved = []
    transferred = []
    other = []
    for event in events:
        value = event["value"]
        metadata = json.loads(event["metadata"])
        if value == "resolved":
            resolved.append(event)
        elif value == "unresolved":
            unresolved.append(event)
        elif metadata.get("human_support", False) == True:
            transferred.append(event)
        else:
            other.append(event)
    return resolved, unresolved, transferred, other


all_events = get()
print(f"Total events fetched: {len(all_events)}")

resolved, unresolved, transferred, other = get_types(all_events)

print(f"Resolved: {len(resolved)}")
print(f"Unresolved: {len(unresolved)}")
print(f"Transferred: {len(transferred)}")
print(f"Other: {len(other)}")