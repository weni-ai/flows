"""
SIP credential provisioning for TPH channels (spec 019).

``SIPProvisioner`` is the only door from Flows to the cluster. It creates, reads and deletes the KubeVoIP objects of one
channel and sets the channel password in the shared credential Secret. A password lives only in memory during the
request and in that Secret: it is never logged, stored in channel config or put in an exception.
"""

import base64
import logging
import secrets

import sentry_sdk
from django_redis import get_redis_connection

from django.conf import settings

from . import constants, manifests
from .kubernetes_client import (
    KubernetesClient,
    KubernetesConfigurationError,
    KubernetesConflict,
    KubernetesError,
    KubernetesForbidden,
    KubernetesNotFound,
    KubernetesTransientError,
)

logger = logging.getLogger(__name__)

# machine-readable reason of a SIPProvisioningError. The message is always generic
ERROR_UNAVAILABLE = "unavailable"
ERROR_FORBIDDEN = "forbidden"
ERROR_CONFLICT = "conflict"
ERROR_MISCONFIGURED = "misconfigured"
ERROR_RATE_LIMITED = "rate_limited"

GENERIC_MESSAGE = "SIP provisioning failed"


class SIPProvisioningError(Exception):
    """Carries a reason code and nothing from the cluster: the message is generic (SEC-08)."""

    def __init__(self, code, message=GENERIC_MESSAGE):
        super().__init__(message)
        self.code = code


class SIPRateLimitError(SIPProvisioningError):
    def __init__(self, retry_after):
        super().__init__(ERROR_RATE_LIMITED, "Too many password requests")
        self.retry_after = retry_after


def is_enabled():
    return bool(settings.TPH_SIP_PROVISIONING_ENABLED)


def build_client():
    return KubernetesClient(settings.TPH_SIP_K8S_NAMESPACE, timeout=settings.TPH_SIP_K8S_TIMEOUT_SECS)


def encode_password(password):
    return base64.b64encode(password.encode()).decode()


def generate_password():
    return secrets.token_urlsafe(constants.SIP_PASSWORD_BYTES)


def _code_for(error):
    if isinstance(error, KubernetesForbidden):
        return ERROR_FORBIDDEN
    if isinstance(error, KubernetesConfigurationError):
        return ERROR_MISCONFIGURED
    if isinstance(error, KubernetesTransientError):
        return ERROR_UNAVAILABLE
    return ERROR_MISCONFIGURED


def report(error, *, event, channel_uuid, org_id=None, user_id=None):
    """
    Logs and reports a failure with opaque identifiers only (Principle XIII). Defects of configuration or permission go
    to Sentry; transient unavailability is logged, since retrying already happened and the caller sees a generic error.
    """
    extra = {
        "event": event,
        "channel_uuid": str(channel_uuid),
        "org_id": org_id,
        "user_id": user_id,
        "status": getattr(error, "status", None),
        "reason": getattr(error, "reason", None),
        "error_type": type(error).__name__,
    }
    logger.error("tph sip: %s failed", event, extra=extra)

    if not isinstance(error, KubernetesTransientError):
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("tph_sip_event", event)
            scope.set_tag("channel_uuid", str(channel_uuid))
            if org_id is not None:
                scope.set_tag("org_id", str(org_id))
            if user_id is not None:
                scope.set_tag("user_id", str(user_id))
            sentry_sdk.capture_exception(error)


class SIPProvisioner:
    def __init__(self, client=None):
        self.client = client or build_client()
        self.secret_name = settings.TPH_SIP_CREDENTIALS_SECRET

    # provisioning -------------------------------------------------------------------------------------------------

    def provision(self, channel_uuid, channel_id, address):
        """
        Creates the five objects of a channel. Returns the non-sensitive metadata for the channel config.

        Idempotent: an object that already exists with the same channel label counts as created, and an existing
        password is never overwritten. If anything fails, what this call touched is removed and
        ``SIPProvisioningError`` is raised.
        """
        name = manifests.resource_name(channel_uuid)
        objects = manifests.build_custom_resources(channel_uuid, channel_id, address)

        self.client.begin_operation()
        touched = []
        try:
            # only a password created by this call is rolled back: a failed re-run must not erase one already issued
            if self._ensure_password_entry(name):
                touched.append(None)
            for kind, body in objects:
                self._create_idempotent(kind, body, channel_uuid)
                touched.append(kind)
        except SIPProvisioningError:
            self._rollback(name, touched)
            raise
        except KubernetesError as e:
            self._rollback(name, touched)
            raise SIPProvisioningError(_code_for(e)) from e

        return {
            constants.CONFIG_SIP_RESOURCE_NAME: name,
            constants.CONFIG_SIP_USERNAME: name,
            constants.CONFIG_SIP_EXTENSION: objects[-1][1]["spec"]["extension"],
        }

    def _ensure_password_entry(self, name):
        """
        Writes a password nobody sees so the SIP user has a valid reference. Never replaces an existing one.
        Returns True when it wrote one.
        """
        secret = self.client.get_secret(self.secret_name)
        if name in (secret.get("data") or {}):
            return False
        self.client.patch_secret_data(self.secret_name, {name: encode_password(generate_password())})
        return True

    def has_password_entry(self, name):
        """Whether the credential Secret already holds a password for ``name``. A missing Secret counts as no."""
        try:
            secret = self.client.get_secret(self.secret_name)
        except KubernetesNotFound:
            return False
        except KubernetesError as e:
            raise SIPProvisioningError(_code_for(e)) from e
        return name in (secret.get("data") or {})

    def _create_idempotent(self, kind, body, channel_uuid):
        try:
            self.client.create_resource(kind, body)
        except KubernetesConflict:
            existing = self.client.get_resource(kind, body["metadata"]["name"])
            labels = (existing.get("metadata") or {}).get("labels") or {}
            if labels.get(constants.CHANNEL_UUID_LABEL) != str(channel_uuid):
                raise SIPProvisioningError(ERROR_CONFLICT)

    def _rollback(self, name, touched):
        """Best effort, reverse order. A failure here is logged and left to the reconciliation task."""
        for kind in reversed(touched):
            try:
                if kind is None:
                    self.client.patch_secret_data(self.secret_name, {name: None})
                else:
                    self.client.delete_resource(kind, name)
            except KubernetesNotFound:
                pass
            except KubernetesError as e:
                logger.error(
                    "tph sip: rollback step failed",
                    extra={"resource_name": name, "kind": kind or "password", "error_type": type(e).__name__},
                )

    # revocation ---------------------------------------------------------------------------------------------------

    def deprovision(self, channel_uuid):
        """
        Deletes every object of a channel, SIP user first. Objects that are already gone count as deleted. Every step is
        attempted even if an earlier one fails, then ``SIPProvisioningError`` reports that something is left over.
        """
        name = manifests.resource_name(channel_uuid)
        self.client.begin_operation()
        failures = []

        for kind in reversed(constants.CUSTOM_RESOURCE_KINDS):
            self._delete_ignoring_missing(lambda kind=kind: self.client.delete_resource(kind, name), failures)
        self._delete_ignoring_missing(lambda: self.client.patch_secret_data(self.secret_name, {name: None}), failures)

        if failures:
            raise SIPProvisioningError(_code_for(failures[0])) from failures[0]

    @staticmethod
    def _delete_ignoring_missing(action, failures):
        try:
            action()
        except KubernetesNotFound:
            pass
        except KubernetesError as e:
            failures.append(e)

    # password -----------------------------------------------------------------------------------------------------

    def issue_password(self, channel_uuid):
        """
        Generates a new password and stores it in the Secret, replacing the previous one. Returns the password: this is
        the only place it leaves the Secret, and the caller must not store or log it.
        """
        name = manifests.resource_name(channel_uuid)
        password = generate_password()

        self.client.begin_operation()
        try:
            self.client.patch_secret_data(self.secret_name, {name: encode_password(password)})
        except KubernetesError as e:
            raise SIPProvisioningError(_code_for(e)) from e
        return password

    # status -------------------------------------------------------------------------------------------------------

    def read_status(self, channel_uuid):
        """``pending``, ``ready`` or ``error``, from the phase of the SIP user. An unreadable SIP user is ``error``."""
        name = manifests.resource_name(channel_uuid)
        self.client.begin_operation()
        try:
            sip_user = self.client.get_resource(constants.KIND_SIP_USER, name)
        except KubernetesError:
            return constants.STATUS_ERROR

        phase = str((sip_user.get("status") or {}).get("phase") or "").lower()
        if phase in constants.SIP_USER_READY_PHASES:
            return constants.STATUS_READY
        if phase in constants.SIP_USER_ERROR_PHASES:
            return constants.STATUS_ERROR
        return constants.STATUS_PENDING

    # reconciliation -----------------------------------------------------------------------------------------------

    def list_managed(self):
        """
        Every object that carries the Flows label, grouped by channel:
        ``{channel uuid: {"kinds": {kind: name}, "newest": newest creationTimestamp (RFC 3339) or None}}``.
        """
        self.client.begin_operation()
        found = {}
        selector = manifests.label_selector()
        for kind in constants.CUSTOM_RESOURCE_KINDS:
            try:
                items = self.client.list_resources(kind, selector)
            except KubernetesError as e:
                raise SIPProvisioningError(_code_for(e)) from e
            for item in items:
                metadata = item.get("metadata") or {}
                channel_uuid = (metadata.get("labels") or {}).get(constants.CHANNEL_UUID_LABEL)
                if not channel_uuid:
                    continue
                group = found.setdefault(channel_uuid, {"kinds": {}, "newest": None})
                group["kinds"][kind] = metadata.get("name")
                created = metadata.get("creationTimestamp")
                if created and (group["newest"] is None or created > group["newest"]):
                    group["newest"] = created
        return found


def channel_is_provisioned(channel):
    return bool((channel.config or {}).get(constants.CONFIG_SIP_RESOURCE_NAME))


def provision_channel(channel, *, provisioner=None):
    """
    Provisions a TPH channel and records the non-sensitive metadata in its config. Raises ``SIPProvisioningError`` and
    leaves nothing in the cluster when it fails. Does not check the feature flag: callers decide whether to call it.
    """
    provisioner = provisioner or SIPProvisioner()
    try:
        metadata = provisioner.provision(channel.uuid, channel.id, channel.address)
    except SIPProvisioningError as e:
        report(
            e.__cause__ or e,
            event="provision",
            channel_uuid=channel.uuid,
            org_id=channel.org_id,
            user_id=channel.created_by_id,
        )
        raise

    config = dict(channel.config or {})
    config.update(metadata)
    config.pop(constants.CONFIG_SIP_RESET_REQUIRED, None)
    channel.config = config
    channel.save(update_fields=["config"])

    logger.info(
        "tph sip: provisioned",
        extra={
            "event": "provision",
            "outcome": "ok",
            "channel_uuid": str(channel.uuid),
            "org_id": channel.org_id,
            "resource_name": metadata[constants.CONFIG_SIP_RESOURCE_NAME],
        },
    )


def deprovision_channel(channel, *, provisioner=None):
    """
    Revokes the objects of a provisioned channel. It does not check the feature flag: turning the flag off must never
    leave a credential that cannot be revoked. A failure is reported and swallowed, because releasing a channel must
    complete and the reconciliation task removes what is left. Returns True when nothing is left behind.
    """
    if not channel_is_provisioned(channel):
        return True

    try:
        (provisioner or SIPProvisioner()).deprovision(channel.uuid)
    except SIPProvisioningError as e:
        report(
            e.__cause__ or e,
            event="deprovision",
            channel_uuid=channel.uuid,
            org_id=channel.org_id,
            user_id=channel.created_by_id,
        )
        return False

    logger.info(
        "tph sip: deprovisioned",
        extra={
            "event": "deprovision",
            "outcome": "ok",
            "channel_uuid": str(channel.uuid),
            "org_id": channel.org_id,
        },
    )
    return True


def check_issue_rate(channel_uuid, redis=None):
    """
    Counts a password issue for the channel in the current window and raises ``SIPRateLimitError`` past the limit.
    The counter lives in Redis so every web pod shares it (Principle XII).
    """
    redis = redis or get_redis_connection()
    key = constants.SIP_CREDENTIALS_RATE_KEY % channel_uuid

    count = redis.incr(key)
    if count == 1:
        redis.expire(key, constants.SIP_CREDENTIALS_WINDOW_SECS)

    if count > settings.TPH_SIP_ISSUE_MAX_PER_WINDOW:
        retry_after = redis.ttl(key)
        if retry_after is None or retry_after < 0:
            retry_after = constants.SIP_CREDENTIALS_WINDOW_SECS
        raise SIPRateLimitError(retry_after)
