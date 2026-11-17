# Data Model: Provision customer SIP credentials on TPH channel creation

**Spec**: [spec.md](spec.md) | **Research**: [research.md](research.md)

No database table, column or migration is added. State lives in two places: the existing `channels.Channel.config` JSON (non-sensitive metadata only) and the Kubernetes cluster (the SIP credential set).

## 1. Channel configuration keys (TPH channels only)

Stored in `Channel.config`, written by `activate` and by reconciliation. **None of these is a secret.** The password is never stored here (FR-006).

| Key | Type | Written when | Meaning |
|-----|------|--------------|---------|
| `sip_resource_name` | string | provisioning | `tph-<32 hex characters of the channel UUID>`. Presence means the channel is provisioned |
| `sip_username` | string | provisioning | The SIP `authUsername`. Equal to `sip_resource_name` |
| `sip_extension` | string | provisioning | Digits-only extension of the SIP user (prefix + padded channel id) |
| `sip_credentials_reset_required` | boolean | reconciliation recreates a lost SIP user | The customer must issue a new password. Cleared by the next successful issue |

Validation and rules:

- Keys are absent on channels created before the feature or with provisioning disabled. The connection endpoints answer `409` for those.
- Existing keys (`voice_mode`, ...) are untouched. Only `config` is saved (`update_fields=["config"]`).
- Courier ignores unknown keys, so nothing changes for call handling.

## 2. SIP credential set (cluster objects)

All five are created together in the namespace `TPH_SIP_K8S_NAMESPACE` and share the name `tph-<hex>`, except the credential entry, which is a key with that name inside the Secret `TPH_SIP_CREDENTIALS_SECRET`.

| Object | API group and kind | Key fields set by Flows | Created order | Deleted order |
|--------|--------------------|-------------------------|---------------|---------------|
| Credential entry | `v1` Secret, key `tph-<hex>` | `data.<key>` = base64 password | 1 | 5 |
| Call scope | `kubevoip.com/v1alpha1` `CallScope` | `spec.gatewayRef.name` | 2 | 4 |
| Dial policy | `kubevoip.com/v1alpha1` `DialPolicy` | `spec.gatewayRef.name`, `spec.scopes[0].name` = own scope | 3 | 3 |
| Call route | `kubevoip.com/v1alpha1` `CallRoute` | `spec.gatewayRef`, `spec.scopeRef` = own scope, `spec.match.calledNumber` = normalized DID (CRD pattern `^[+0-9.*]+$`, max 64), `spec.target.asteriskPoolRef` (a string, not an object) and `spec.target.extension` | 4 | 2 |
| SIP user | `kubevoip.com/v1alpha1` `SIPUser` | `spec.gatewayRef`, `spec.dialPolicyRef` = own policy, `spec.extension`, `spec.authUsername`, `spec.callerId`, `spec.passwordSecretRef` {name, key} | 5 | 1 |

Deletion runs in reverse so a SIP user never outlives its policy and scope. Labels on the four custom resources: `weni.ai/managed-by: flows`, `weni.ai/channel-uuid: <uuid>`. See [contracts/kubernetes-objects.md](contracts/kubernetes-objects.md) for the manifests and the permission they require.

### Invariants (each is asserted by a test)

1. The route's `scopeRef` is the channel's scope and never `voice-mode-internal`.
2. The dial policy lists exactly one scope: the channel's.
3. The route's `calledNumber` is non-empty, digits only, and contains no wildcard.
4. The SIP user's `dialPolicyRef` is the channel's policy.
5. `passwordSecretRef.name` is the configured credential Secret and `key` equals the resource name.
6. No object carries a GitOps tracking label or the kustomize common labels.

## 3. Provisioning state machine (per channel)

```text
(no sip_resource_name) --activate/command--> provisioned
provisioned --release--> deprovisioned (objects deleted, config irrelevant)
provisioned --reconciliation finds SIP user missing--> provisioned + sip_credentials_reset_required
provisioned + reset_required --issue password--> provisioned
inactive channel with leftovers --reconciliation--> deleted
```

Connection status reported to callers is derived at request time from the SIP user, not stored:

| Reported `status` | Source |
|-------------------|--------|
| `pending` | SIP user exists, phase is absent or not yet in the ready set |
| `ready` | phase maps to ready (mapping in `SIP_USER_READY_PHASES` and `SIP_USER_ERROR_PHASES`, T-STG-2) |
| `error` | phase maps to an error value, or the SIP user cannot be read after retries |

## 4. Connection data (response entity, not stored)

Built per request from channel config plus settings. Fields and the example are in [contracts/internals-sip-endpoints.md](contracts/internals-sip-endpoints.md). `password` exists only in the issue response.

## 5. Settings added

| Setting (environment variable) | Default | Purpose |
|--------------------------------|---------|---------|
| `TPH_SIP_PROVISIONING_ENABLED` | `false` | Feature flag (FR-015) |
| `TPH_SIP_K8S_NAMESPACE` | `kubevoip` | Namespace of the objects |
| `TPH_SIP_GATEWAY_NAME` | `voice-mode` | `gatewayRef` of every object |
| `TPH_SIP_ASTERISK_POOL` | `voice-mode` | Route target pool |
| `TPH_SIP_ASTERISK_EXTENSION` | `100` | Route target extension that opens the voice session |
| `TPH_SIP_CREDENTIALS_SECRET` | `voice-mode-tph-credentials` | Secret holding customer passwords |
| `TPH_SIP_EXTENSION_PREFIX` | `9` | Prefix of generated SIP extensions |
| `TPH_SIP_K8S_TIMEOUT_SECS` | `5` | Per-request timeout |
| `TPH_SIP_DOMAIN` | empty | SIP domain returned to the customer |
| `TPH_SIP_TRANSPORTS` | `tls:5061,udp:5060,tcp:5060` | Transports and ports returned |
| `TPH_SIP_SIGNALING_IPS` | empty | Signaling IPs returned |
| `TPH_SIP_MEDIA_IPS` | empty | Media IPs returned |
| `TPH_SIP_RTP_PORT_RANGE` | `10000-10035` | Media range returned |
| `TPH_SIP_CODECS` | `PCMA,PCMU` | Codecs returned |
| `TPH_SIP_DTMF_MODE` | `rfc4733` | DTMF mode returned |
| `TPH_SIP_ISSUE_MAX_PER_WINDOW` | `5` | Issue limit per channel |

Named constants (not settings): `SIP_PASSWORD_BYTES = 24`, `SIP_EXTENSION_LENGTH = 12`, `SIP_CREDENTIALS_WINDOW_SECS = 3600`, `K8S_MAX_ATTEMPTS = 3`, `K8S_BACKOFF_BASE_SECS = 0.2`, `K8S_OVERALL_DEADLINE_SECS = 20`, `RECONCILE_INTERVAL_SECS = 900`, `RECONCILE_MAX_DELETIONS_PER_RUN = 50`, `MANAGED_BY_LABEL`, `CHANNEL_UUID_LABEL`, `RESOURCE_NAME_PREFIX = "tph-"`.
