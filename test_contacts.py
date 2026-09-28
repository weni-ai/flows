import os

import requests


# FLOWS_BASE_URL = os.environ.get("FLOWS_BASE_URL", "https://flows.stg.cloud.weni.ai")
# Kong staging (contacts.json may return HTML instead of JSON on this host):
FLOWS_BASE_URL = "http://kong-7d38d265f259bbab.elb.sa-east-1.amazonaws.com"

TOKEN = os.environ.get(
    "TOKEN",
    "sZLrgz61HjSPpPrdYgx8x_FpMb2MJUzKGTA9MseQ4RU",
)

# APIToken uses "Token". JWT Bearer (hey load test) can be tried via:
#   AUTH_SCHEME=Bearer TOKEN='<jwt>' python test_contacts.py
AUTH_SCHEME = os.environ.get("AUTH_SCHEME", "Bearer")

LIMIT = int(os.environ.get("LIMIT", "250"))

headers = {"Authorization": f"{AUTH_SCHEME} {TOKEN}"}


def print_http_error(response):
    print(f"HTTP {response.status_code} {response.reason}")
    print(f"URL: {response.url}")
    print(f"Auth: {AUTH_SCHEME} (token length: {len(TOKEN)})")
    for header in ("server", "content-type", "www-authenticate", "x-kong-request-id"):
        value = response.headers.get(header)
        if value:
            print(f"{header}: {value}")
    print(f"Body: {response.text}")


def parse_json_response(response):
    content_type = response.headers.get("Content-Type", "")
    if "application/json" not in content_type:
        preview = response.text[:300].replace("\n", " ")
        raise ValueError(
            f"Expected JSON but got {content_type or 'unknown content-type'} "
            f"(status {response.status_code}). Body preview: {preview}"
        )
    return response.json()


def get_contacts(extra_params=None):
    path = "/contacts"
    url = f"{FLOWS_BASE_URL}{path}"

    print("Starting contacts request...")

    all_contacts = []
    current_page = 1
    next_url = url
    params = {"limit": LIMIT, **(extra_params or {})}

    while next_url:
        try:
            print(f"Requesting page {current_page}...")
            request_params = params if current_page == 1 else None
            response = requests.get(next_url, params=request_params, timeout=60, headers=headers)
            if not response.ok:
                print_http_error(response)
                response.raise_for_status()

            payload = parse_json_response(response)
            results = payload.get("results", [])
            all_contacts.extend(results)

            print(f"Added {len(results)} contacts (total: {len(all_contacts)})")

            next_url = payload.get("next")
            current_page += 1

            if not next_url:
                print("No more pages to fetch")
        except (requests.exceptions.RequestException, ValueError) as e:
            print(f"Error: {e}")
            break

    print(f"Total contacts fetched: {len(all_contacts)}")
    return all_contacts


def summarize_contacts(contacts):
    blocked = sum(1 for c in contacts if c.get("blocked"))
    stopped = sum(1 for c in contacts if c.get("stopped"))

    print(f"\nBlocked: {blocked}")
    print(f"Stopped: {stopped}")
    print(f"Active: {len(contacts) - blocked - stopped}")


if __name__ == "__main__":
    contacts = get_contacts()
    summarize_contacts(contacts)
