# Contract: Kubernetes objects and permissions

**Spec**: [../spec.md](../spec.md)

This is the contract between Flows and the platform repository (`kubernetes-manifests-platform`) and the cloud team. Flows creates only what is listed here. Everything below uses `<hex>` for the 32 hexadecimal characters of the channel UUID, `<uuid>` for the hyphenated UUID, and the values in angle brackets from settings.

## Objects created per channel

All four custom resources carry these labels and **no others**:

```yaml
labels:
  weni.ai/managed-by: flows
  weni.ai/channel-uuid: <uuid>
```

```yaml
apiVersion: kubevoip.com/v1alpha1
kind: CallScope
metadata:
  name: tph-<hex>
  namespace: <TPH_SIP_K8S_NAMESPACE>
spec:
  gatewayRef: { name: <TPH_SIP_GATEWAY_NAME> }
---
apiVersion: kubevoip.com/v1alpha1
kind: DialPolicy
metadata:
  name: tph-<hex>
  namespace: <TPH_SIP_K8S_NAMESPACE>
spec:
  gatewayRef: { name: <TPH_SIP_GATEWAY_NAME> }
  scopes:
    - name: tph-<hex>
---
apiVersion: kubevoip.com/v1alpha1
kind: CallRoute
metadata:
  name: tph-<hex>
  namespace: <TPH_SIP_K8S_NAMESPACE>
spec:
  gatewayRef: { name: <TPH_SIP_GATEWAY_NAME> }
  scopeRef: { name: tph-<hex> }
  match:
    calledNumber: "<digits of the channel address>"
  target:
    asteriskPoolRef: <TPH_SIP_ASTERISK_POOL>
    extension: "<TPH_SIP_ASTERISK_EXTENSION>"
---
apiVersion: kubevoip.com/v1alpha1
kind: SIPUser
metadata:
  name: tph-<hex>
  namespace: <TPH_SIP_K8S_NAMESPACE>
spec:
  gatewayRef: { name: <TPH_SIP_GATEWAY_NAME> }
  dialPolicyRef: { name: tph-<hex> }
  extension: "<prefix + zero-padded channel id>"
  authUsername: tph-<hex>
  callerId: "<digits of the channel address>"
  passwordSecretRef:
    name: <TPH_SIP_CREDENTIALS_SECRET>
    key: tph-<hex>
```

Credential entry, patched into the existing Secret `<TPH_SIP_CREDENTIALS_SECRET>`:

```json
{ "data": { "tph-<hex>": "<base64 of the password>" } }
```

Removal sets the key to `null` in a merge patch.

Field constraints taken from the installed CRDs (`platform-crds-v0.6.9.yaml`): `authUsername` matches `^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$` and has at most 40 characters (the name has 36); `extension` is digits only, at most 20; `calledNumber` matches `^[+0-9.*]+$`, at most 64; a route with `asteriskPoolRef` requires `extension`; `DialPolicy.scopes` has at least one item.

## Permission required by the `flows` service account (SEC-01)

To be delivered in `kubernetes-manifests-platform` (replaces the wider scope in CLOUDW-4780):

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: flows-tph-sip
  namespace: kubevoip
rules:
  - apiGroups: ["kubevoip.com"]
    resources: ["sipusers", "callscopes", "dialpolicies", "callroutes"]
    verbs: ["create", "get", "list", "delete"]
  - apiGroups: [""]
    resources: ["secrets"]
    resourceNames: ["voice-mode-tph-credentials"]
    verbs: ["get", "patch"]
```

A `RoleBinding` in `kubevoip` binds it to `ServiceAccount flows` of the namespace where Flows runs. Notes:

- `get` on `sipusers` returns the object with its `status`, so no rule on the status subresource is needed.
- No `update` or `patch` on the custom resources: Flows never edits them, it deletes and recreates. If a later change needs edits, the permission is widened in that change.
- `list` on the four kinds is required by reconciliation and is limited by label selector in the client.
- No permission on `secrets` besides the one named Secret, no other kinds of `kubevoip.com`, no `ClusterRole`.

## Cluster-side guard (SEC-02, cloud team)

A `ValidatingAdmissionPolicy` bound to requests from the Flows service account should reject:

- any object whose name does not start with `tph-` or that lacks the `weni.ai/managed-by: flows` label;
- a `SIPUser` whose `dialPolicyRef.name` does not equal its own name, or whose `passwordSecretRef.name` is not the credential Secret;
- a `CallRoute` whose `match.calledNumber` contains `.` or `*`, whose `scopeRef.name` differs from its own name, or whose target is not an `asteriskPoolRef` of the voice pool;
- a `DialPolicy` that lists any scope other than the one with its own name.

## Objects created once by the platform team

- Secret `<TPH_SIP_CREDENTIALS_SECRET>` in `<TPH_SIP_K8S_NAMESPACE>`, empty.
- The Role, RoleBinding and policy above.

## Operator behavior to confirm in staging

- A dial policy limits a SIP user to the routes of the scopes it lists (OQ-01).
- A SIP user whose policy has no trunk scope cannot originate through a trunk (OQ-01).
- The `status.phase` values of healthy and failing SIP users (T-STG-2).
