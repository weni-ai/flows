"""
Minimal client for the in-cluster Kubernetes API, used only to manage the KubeVoIP objects of TPH channels.

It is deliberately narrow: five operations on the custom resources of one namespace plus ``get`` and merge-patch of a
single Secret. It authenticates with the mounted service account, verifies TLS, applies an explicit timeout and retries a
bounded number of times, only on failures that can plausibly succeed on another attempt (Principle XI).

Errors never carry the response body: it can echo the submitted manifest, which may hold a password.
"""

import json
import logging
import os
import time

import requests

from . import constants

logger = logging.getLogger(__name__)

MERGE_PATCH_CONTENT_TYPE = "application/merge-patch+json"


class KubernetesError(Exception):
    """Base class. ``status`` is the HTTP status when there was a response, ``reason`` the Kubernetes reason string."""

    def __init__(self, message, status=None, reason=None):
        super().__init__(message)
        self.status = status
        self.reason = reason


class KubernetesTransientError(KubernetesError):
    """Connection error, timeout, 429 or 5xx that persisted after the allowed attempts, or the deadline expired."""


class KubernetesNotFound(KubernetesError):
    pass


class KubernetesConflict(KubernetesError):
    """The object already exists."""


class KubernetesForbidden(KubernetesError):
    """Missing permission or rejected by an admission policy. A defect of configuration, never retried."""


class KubernetesRequestError(KubernetesError):
    """Any other 4xx: the request itself is wrong."""


class KubernetesConfigurationError(KubernetesError):
    """The client cannot find the in-cluster credentials."""


class KubernetesClient:
    def __init__(
        self,
        namespace,
        *,
        timeout,
        session=None,
        token_file=constants.K8S_TOKEN_FILE,
        ca_file=constants.K8S_CA_FILE,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        self.namespace = namespace
        self.timeout = timeout
        self.session = session or requests.Session()
        self.token_file = token_file
        self.ca_file = ca_file
        self._sleep = sleep
        self._clock = clock
        self._deadline = None

    # operations used by the provisioner -------------------------------------------------------------------------

    def begin_operation(self):
        """Starts the overall deadline of one provisioning operation (several calls)."""
        self._deadline = self._clock() + constants.K8S_OVERALL_DEADLINE_SECS

    def create_resource(self, kind, body):
        return self._request("POST", self._custom_path(kind), json_body=body)

    def get_resource(self, kind, name):
        return self._request("GET", self._custom_path(kind, name))

    def delete_resource(self, kind, name):
        return self._request("DELETE", self._custom_path(kind, name))

    def list_resources(self, kind, label_selector):
        result = self._request("GET", self._custom_path(kind), params={"labelSelector": label_selector})
        return result.get("items") or []

    def get_secret(self, name):
        return self._request("GET", self._secret_path(name))

    def patch_secret_data(self, name, data):
        """Merge-patches ``data`` of a Secret. A value of ``None`` removes the key. Values must already be base64."""
        return self._request(
            "PATCH", self._secret_path(name), json_body={"data": data}, content_type=MERGE_PATCH_CONTENT_TYPE
        )

    # paths --------------------------------------------------------------------------------------------------------

    def _custom_path(self, kind, name=None):
        plural = constants.KIND_PLURALS[kind]
        group_version = f"{constants.KUBEVOIP_API_GROUP}/{constants.KUBEVOIP_API_VERSION}"
        base = f"/apis/{group_version}/namespaces/{self.namespace}/{plural}"
        return f"{base}/{name}" if name else base

    def _secret_path(self, name):
        return f"/api/v1/namespaces/{self.namespace}/secrets/{name}"

    # transport ----------------------------------------------------------------------------------------------------

    def _base_url(self):
        host = os.environ.get("KUBERNETES_SERVICE_HOST")
        port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
        if not host:
            raise KubernetesConfigurationError("KUBERNETES_SERVICE_HOST is not set")
        if ":" in host:  # IPv6 literal
            host = f"[{host}]"
        return f"https://{host}:{port}"

    def _token(self):
        # projected tokens rotate, so the file is read on every request
        try:
            with open(self.token_file) as token_file:
                return token_file.read().strip()
        except OSError:
            raise KubernetesConfigurationError("service account token is not readable")

    def _check_deadline(self):
        if self._deadline is not None and self._clock() > self._deadline:
            raise KubernetesTransientError("overall deadline exceeded")

    def _request(self, method, path, *, params=None, json_body=None, content_type="application/json"):
        url = self._base_url() + path
        last_error = None

        for attempt in range(1, constants.K8S_MAX_ATTEMPTS + 1):
            self._check_deadline()
            headers = {"Authorization": f"Bearer {self._token()}", "Accept": "application/json"}
            data = None
            if json_body is not None:
                headers["Content-Type"] = content_type
                data = json.dumps(json_body)

            try:
                response = self.session.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    data=data,
                    timeout=self.timeout,
                    verify=self.ca_file,
                )
            except (requests.ConnectionError, requests.Timeout) as e:
                last_error = KubernetesTransientError(f"{method} request failed: {type(e).__name__}")
            else:
                if response.status_code in constants.K8S_RETRYABLE_STATUSES:
                    last_error = KubernetesTransientError(
                        f"{method} request returned {response.status_code}", status=response.status_code
                    )
                else:
                    return self._handle_response(method, response)

            is_last_attempt = attempt == constants.K8S_MAX_ATTEMPTS
            logger.warning(
                "tph sip: kubernetes call failed, attempts exhausted"
                if is_last_attempt
                else "tph sip: kubernetes call failed, will retry",
                extra={"method": method, "attempt": attempt, "error": str(last_error)},
            )
            if not is_last_attempt:
                self._sleep(constants.K8S_BACKOFF_BASE_SECS * (2 ** (attempt - 1)))

        raise last_error

    def _handle_response(self, method, response):
        status = response.status_code
        if 200 <= status < 300:
            if not response.content:
                return {}
            try:
                return response.json()
            except ValueError:
                return {}

        reason = self._reason(response)
        message = f"{method} request returned {status}"
        if status == 404:
            raise KubernetesNotFound(message, status=status, reason=reason)
        if status == 409:
            raise KubernetesConflict(message, status=status, reason=reason)
        if status in (401, 403):
            raise KubernetesForbidden(message, status=status, reason=reason)
        raise KubernetesRequestError(message, status=status, reason=reason)

    @staticmethod
    def _reason(response):
        """Only the machine-readable ``reason`` of the Status object, never its message or the echoed manifest."""
        try:
            reason = response.json().get("reason")
        except (ValueError, AttributeError):
            return None
        return reason if isinstance(reason, str) else None
