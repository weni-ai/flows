"""
In-memory stand-in for ``KubernetesClient``, used only by tests (spec 019, Test Strategy).

It implements the same operations, records every call and can be told to fail a given call, so flows can be tested
without a cluster.
"""

import copy
from datetime import datetime, timedelta, timezone

from .kubernetes_client import KubernetesConflict, KubernetesNotFound


class FakeKubernetes:
    def __init__(self, secret_name=None):
        self.resources = {}  # kind -> {name: body}
        self.secrets = {}  # secret name -> {key: base64 value}
        self.calls = []  # (operation, kind or secret name, object name or None)
        self._failures = []  # [operation, kind, error, remaining]
        self.now = datetime.now(timezone.utc)  # creationTimestamp given to new objects
        if secret_name:
            self.secrets[secret_name] = {}

    # test controls ------------------------------------------------------------------------------------------------

    def fail(self, operation, error, kind=None, times=1):
        """Makes the next ``times`` matching calls raise ``error`` (``kind`` None matches any kind)."""
        self._failures.append([operation, kind, error, times])

    def age_all(self, seconds):
        """Makes every object look ``seconds`` older, to exercise the minimum age of the reconciliation."""
        for bodies in self.resources.values():
            for body in bodies.values():
                created = datetime.strptime(body["metadata"]["creationTimestamp"], "%Y-%m-%dT%H:%M:%SZ")
                aged = created - timedelta(seconds=seconds)
                body["metadata"]["creationTimestamp"] = aged.strftime("%Y-%m-%dT%H:%M:%SZ")

    def set_sip_user_phase(self, name, phase):
        self.resources["SIPUser"][name].setdefault("status", {})["phase"] = phase

    def names(self, kind):
        return sorted(self.resources.get(kind, {}))

    def kinds_present(self):
        return sorted(kind for kind, bodies in self.resources.items() if bodies)

    def secret_data(self, name=None):
        """The base64 values of a credential Secret (the only secret the fake is built with when ``name`` is None)."""
        return dict(self.secrets[name or next(iter(self.secrets))])

    def secret_keys(self, name=None):
        return sorted(self.secret_data(name))

    def calls_of(self, operation):
        return [call for call in self.calls if call[0] == operation]

    # same operations as KubernetesClient --------------------------------------------------------------------------

    def begin_operation(self):
        pass

    def create_resource(self, kind, body):
        name = body["metadata"]["name"]
        self._record("create", kind, name)
        existing = self.resources.setdefault(kind, {})
        if name in existing:
            raise KubernetesConflict("already exists", status=409, reason="AlreadyExists")
        stored = copy.deepcopy(body)
        stored["metadata"]["creationTimestamp"] = self.now.strftime("%Y-%m-%dT%H:%M:%SZ")
        existing[name] = stored
        return copy.deepcopy(stored)

    def get_resource(self, kind, name):
        self._record("get", kind, name)
        try:
            return copy.deepcopy(self.resources[kind][name])
        except KeyError:
            raise KubernetesNotFound("not found", status=404, reason="NotFound")

    def delete_resource(self, kind, name):
        self._record("delete", kind, name)
        try:
            del self.resources[kind][name]
        except KeyError:
            raise KubernetesNotFound("not found", status=404, reason="NotFound")
        return {}

    def list_resources(self, kind, label_selector):
        self._record("list", kind, None)
        wanted = dict(part.split("=", 1) for part in label_selector.split(","))
        return [
            copy.deepcopy(body)
            for body in self.resources.get(kind, {}).values()
            if all(body["metadata"].get("labels", {}).get(key) == value for key, value in wanted.items())
        ]

    def get_secret(self, name):
        self._record("get_secret", name, None)
        if name not in self.secrets:
            raise KubernetesNotFound("not found", status=404, reason="NotFound")
        return {"data": dict(self.secrets[name])}

    def patch_secret_data(self, name, data):
        self._record("patch_secret", name, None)
        if name not in self.secrets:
            raise KubernetesNotFound("not found", status=404, reason="NotFound")
        for key, value in data.items():
            if value is None:
                self.secrets[name].pop(key, None)
            else:
                self.secrets[name][key] = value
        return {}

    def _record(self, operation, kind, name):
        self.calls.append((operation, kind, name))
        for failure in self._failures:
            failure_operation, failure_kind, error, remaining = failure
            if remaining > 0 and failure_operation == operation and failure_kind in (None, kind):
                failure[3] -= 1
                raise error
