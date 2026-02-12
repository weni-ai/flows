import requests


FLOWS_BASE_URL = "https://flows.weni.ai"
LIMIT = 700


base_kwargs = {
    "date_start": "2026-01-30T00:00:00",
    "date_end": "2026-01-30T23:59:59",
    "event_name": "weni_nexus_data",
    "key": "conversation_classification",
    "table": "conversation_classification",
    "value": "unresolved",
}

headers = {"Authorization": "Token 263c4c885d1c84fe27136a6e6ec18d62171c5980"}


def get_events():
    path = "/api/v2/events.json"
    url = f"{FLOWS_BASE_URL}{path}"

    print("Starting events request...")

    all_events = []

    offset = 0
    current_page = 1

    while True:

        try:
            params = {
                **base_kwargs,
                "limit": LIMIT,
                "offset": offset,
            }
            print(f"Requesting page {current_page}...")
            response = requests.get(url, params=params, timeout=60, headers=headers)
            response.raise_for_status()

            events = response.json()

            print(events)

            if len(events) == 0 or events == [{}]:
                print("No more events to fetch")
                break

            all_events.extend(events)
            print(f"Added {len(events)} events to the list")

            offset += LIMIT
            current_page += 1
        except requests.exceptions.RequestException as e:
            print(f"Error: {e}")
            break

    print(f"Total events fetched: {len(all_events)}")

    return all_events


def get_event_types(all_events):
    resolved = []
    unresolved = []
    transferred = []
    other = []

    for event in all_events:
        value = event["value"]
        if value == "resolved":
            resolved.append(event)
        elif value == "unresolved":
            unresolved.append(event)
        elif event.get("metadata", {}).get("human_support", False) == True:
            transferred.append(event)
        else:
            other.append(event)

    return resolved, unresolved, transferred, other


if __name__ == "__main__":
    all_events = get_events()
    resolved, unresolved, transferred, other = get_event_types(all_events)

    print(f"\nResolved: {len(resolved)}")
    print(f"Unresolved: {len(unresolved)}")
    print(f"Transferred: {len(transferred)}")
    print(f"Other: {len(other)}")