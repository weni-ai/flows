"""
Named constants for TPH SIP credential provisioning (spec 019).

Values that differ per environment are settings (``TPH_SIP_*`` in ``temba/settings_common.py``). The values here are
fixed by the design and by the KubeVoIP CRDs.
"""

# resource naming and labels. Only these two labels are set on objects created by Flows, so that nothing in the cluster
# (GitOps controller, kustomize labels) treats them as part of a tracked application.
RESOURCE_NAME_PREFIX = "tph-"
MANAGED_BY_LABEL = "weni.ai/managed-by"
MANAGED_BY_VALUE = "flows"
CHANNEL_UUID_LABEL = "weni.ai/channel-uuid"

# KubeVoIP custom resources
KUBEVOIP_API_GROUP = "kubevoip.com"
KUBEVOIP_API_VERSION = "v1alpha1"
KIND_CALL_SCOPE = "CallScope"
KIND_DIAL_POLICY = "DialPolicy"
KIND_CALL_ROUTE = "CallRoute"
KIND_SIP_USER = "SIPUser"
# creation order. Deletion runs in the reverse order so a SIP user never outlives its policy and scope
CUSTOM_RESOURCE_KINDS = (KIND_CALL_SCOPE, KIND_DIAL_POLICY, KIND_CALL_ROUTE, KIND_SIP_USER)
KIND_PLURALS = {
    KIND_CALL_SCOPE: "callscopes",
    KIND_DIAL_POLICY: "dialpolicies",
    KIND_CALL_ROUTE: "callroutes",
    KIND_SIP_USER: "sipusers",
}

# channel config keys written by provisioning. None of them is a secret
CONFIG_SIP_RESOURCE_NAME = "sip_resource_name"
CONFIG_SIP_USERNAME = "sip_username"
CONFIG_SIP_EXTENSION = "sip_extension"
CONFIG_SIP_RESET_REQUIRED = "sip_credentials_reset_required"

# password issued to the customer. 24 random bytes give a 32 character URL-safe string
SIP_PASSWORD_BYTES = 24

# SIP extension: settings prefix followed by the channel id, left padded with zeros up to this many digits. The CRD
# accepts digits only, up to 20
SIP_EXTENSION_LENGTH = 12

# limit of password issues per channel. The maximum is TPH_SIP_ISSUE_MAX_PER_WINDOW
SIP_CREDENTIALS_WINDOW_SECS = 3600
SIP_CREDENTIALS_RATE_KEY = "tph-sip-credentials:%s"

# Kubernetes API client
K8S_MAX_ATTEMPTS = 3
K8S_BACKOFF_BASE_SECS = 0.2
# the claim is synchronous in a web request: stop the whole operation, not only one call, past this deadline
K8S_OVERALL_DEADLINE_SECS = 20
K8S_SERVICE_ACCOUNT_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"
K8S_TOKEN_FILE = K8S_SERVICE_ACCOUNT_DIR + "/token"
K8S_CA_FILE = K8S_SERVICE_ACCOUNT_DIR + "/ca.crt"
# HTTP statuses worth another attempt. Everything else is a defect of the request or of the permission
K8S_RETRYABLE_STATUSES = (429, 500, 502, 503, 504)

# reconciliation
RECONCILE_INTERVAL_SECS = 900
# a bug (for example an empty channel table) must not delete every customer credential in one run
RECONCILE_MAX_DELETIONS_PER_RUN = 50
# A claim runs inside a transaction, so its objects exist in the cluster before the channel is visible in the database.
# Objects younger than this are never treated as orphans
RECONCILE_MIN_AGE_SECS = 600

# status reported to the customer, derived from SIPUser.status.phase
STATUS_PENDING = "pending"
STATUS_READY = "ready"
STATUS_ERROR = "error"
# Lower-cased phases. The exact values written by the operator are not in the CRDs and must be confirmed in staging
# (T-STG-2). Any other value is reported as pending, which is the safe default.
SIP_USER_READY_PHASES = frozenset({"ready"})
SIP_USER_ERROR_PHASES = frozenset({"error", "failed"})
