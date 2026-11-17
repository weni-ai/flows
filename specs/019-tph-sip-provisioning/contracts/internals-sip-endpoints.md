# Contract: internals endpoints for TPH SIP connection data

**Spec**: [../spec.md](../spec.md) | **Version impact**: minor (two new endpoints, no change to existing ones)

Both endpoints live next to the existing internals channel endpoints in `temba/api/v2/internals/channels/`. The consumer is the integrations service, which acts for a project administrator and is responsible for checking that user's permission before calling.

## Authentication and authorization

- Same classes as `InternalChannelView`: `WeniAuthentication` and `InternalOIDCAuthentication`, permission `CanCommunicateInternally | (IsAuthenticated & IsUserInOrg)`.
- The channel is resolved with `uuid = channel_uuid`, `org = org of project_uuid`, `is_active = true`, `channel_type = "TPH"`. Any miss returns the same `404` body, so unknown, other-project, inactive and wrong-type channels cannot be told apart. The cluster is not called before this check.
- `project_uuid` is required on both endpoints. A missing or unknown project is the same `404`.

## GET `/api/v2/internals/channel_sip_connection`

Query parameters: `channel_uuid` (UUID, required), `project_uuid` (UUID, required).

Success `200`:

```json
{
  "status": "ready",
  "domain": "voip.weni.ai",
  "transports": [
    { "protocol": "tls", "port": 5061 },
    { "protocol": "udp", "port": 5060 },
    { "protocol": "tcp", "port": 5060 }
  ],
  "username": "tph-3f2c9a7e5b4d41a0a1b2c3d4e5f60718",
  "did": "5511912345678",
  "signaling_ips": ["203.0.113.10"],
  "media": { "ips": ["203.0.113.20"], "rtp_port_range": "10000-10035" },
  "codecs": ["PCMA", "PCMU"],
  "dtmf_mode": "rfc4733",
  "credentials_reset_required": false
}
```

- `status` is `pending`, `ready` or `error`.
- There is **no** `password` field in this response, ever.
- `did` is the number the PBX must dial, in the normalized form used by the call route.
- `signaling_ips` and `media.ips` are empty arrays when not configured.
- `credentials_reset_required` mirrors `sip_credentials_reset_required`.

## POST `/api/v2/internals/channel_sip_credentials`

JSON body: `{ "channel_uuid": "<uuid>", "project_uuid": "<uuid>" }`.

Success `200`: the same document as the GET plus:

```json
{ "password": "<32 characters, shown only here>" }
```

Response headers: `Cache-Control: no-store`, `Pragma: no-cache`.

Effects: a new password is generated, written to the credential Secret, and any previous password stops working. `credentials_reset_required` becomes false. An audit log record is written without the password.

## Errors (both endpoints)

| Status | When | Body |
|--------|------|------|
| `400` | `channel_uuid` or `project_uuid` is missing or not a UUID | DRF validation body: `{"<field>": ["..."]}` |
| `401`/`403` | Missing or invalid authentication | framework default |
| `404` | Unknown channel, other project, inactive channel, non-TPH channel, unknown project | `{"error": "Channel not found"}` (identical in every case) |
| `409` | The channel exists but has no SIP provisioning (created before the feature or with the flag off) | `{"error": "SIP provisioning not available for this channel"}` |
| `429` | POST only: more than `TPH_SIP_ISSUE_MAX_PER_WINDOW` issues in the last hour for this channel | `{"error": "Too many password requests"}` with `Retry-After` |
| `503` | The cluster could not be reached after retries, or the credential store update failed | `{"error": "Service unavailable"}` |

No error body contains a cluster response, a manifest, a token or a stack trace (SEC-08).

## Compatibility

Additive. No existing endpoint, serializer or field changes. The integrations service can adopt the endpoints at its own pace. The earlier draft in `docs/plans` proposed per-channel URLs; this contract replaces it with the flat style used by the neighboring internals endpoints.
