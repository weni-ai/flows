# Quickstart: validate TPH SIP provisioning

**Spec**: [spec.md](spec.md) | **Contracts**: [contracts/](contracts/)

## 1. Automated validation (local, no cluster)

Prerequisites: the project virtualenv and the test database as described in the repository README.

```bash
poetry run coverage run manage.py test temba.channels.types.telephony --noinput
poetry run coverage run manage.py test temba.api.v2.internals.channels --noinput
./code_check.py
```

Expected: all green. The Kubernetes API is the in-memory fake, so these runs never reach a cluster.

Checks to read in the output or in the tests:

- A claim with the flag on creates five objects with the expected names, labels and references.
- A claim where the fake fails the fourth object leaves no channel and no objects.
- The password is not in `channel.config`, logs or any channel column.
- Cross-project, inactive, wrong-type and unknown channels return the same `404`.
- The sixth issue within an hour returns `429`.
- A claim with the flag off makes no cluster call.

## 2. Settings for a staging run

Set in the Flows web and Celery environment (names and defaults in [data-model.md](data-model.md)):

```text
TPH_SIP_PROVISIONING_ENABLED=true
TPH_SIP_K8S_NAMESPACE=kubevoip
TPH_SIP_DOMAIN=voip.stg.cloud.weni.ai
TPH_SIP_CREDENTIALS_SECRET=voice-mode-tph-credentials
```

Platform prerequisites (separate repository changes): the Role and RoleBinding from [contracts/kubernetes-objects.md](contracts/kubernetes-objects.md), the empty credential Secret, and the web pods mounting the `flows` service account.

## 3. Staging checks with a real cluster (with the cloud team)

| # | Action | Expected |
|---|--------|----------|
| 1 | Check that the service account can do only the permitted actions (`kubectl auth can-i` as the `flows` service account) | `create sipusers` yes; `create secrets` no; `get secrets/voice-mode-secret` no; `create sipgateways` no; any other namespace no |
| 2 | Create a TPH channel from the claim API | Five objects exist with label `weni.ai/managed-by=flows`; the operator reports the SIP user phase |
| 3 | `GET channel_sip_connection` | Domain, user, DID, codecs; `status` moves from `pending` to `ready`; no password |
| 4 | `POST channel_sip_credentials` | A password in the response only; `Cache-Control: no-store` |
| 5 | Register a test PBX with the data and call the DID | The voice agent answers |
| 6 | With the same credential, dial another channel's DID | Refused |
| 7 | With the same credential, dial an external number | Refused |
| 8 | Try to create, as the `flows` service account, a SIP user with `dialPolicyRef: voice-mode-internal` | Rejected by the admission policy |
| 9 | Send repeated wrong passwords | Limited or blocked at the SIP proxy |
| 10 | Release the channel | The five objects and the Secret key disappear |
| 11 | Delete a SIP user by hand and wait for reconciliation | Objects recreated, `credentials_reset_required` true |
| 12 | Record the `status.phase` of a healthy and a failing SIP user | Update `SIP_USER_READY_PHASES` and `SIP_USER_ERROR_PHASES` |

Rollback: set `TPH_SIP_PROVISIONING_ENABLED=false`. New channels stop being provisioned. To revoke everything, the cloud team deletes `sipusers,callroutes,dialpolicies,callscopes` by label `weni.ai/managed-by=flows` in `kubevoip` and removes the keys from the Secret.
