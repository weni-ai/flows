import json
import os
import tempfile
from unittest.mock import patch

import requests

from django.test import SimpleTestCase

from . import constants
from .kubernetes_client import (
    KubernetesClient,
    KubernetesConfigurationError,
    KubernetesConflict,
    KubernetesForbidden,
    KubernetesNotFound,
    KubernetesRequestError,
    KubernetesTransientError,
)


class StubResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body
        self.content = b"" if body is None else json.dumps(body).encode()

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


class StubSession:
    """Returns the queued responses (or raises the queued exceptions) in order and records every request."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append({"method": method, "url": url, **kwargs})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class KubernetesClientTest(SimpleTestCase):
    def setUp(self):
        super().setUp()
        token_dir = tempfile.TemporaryDirectory()
        self.addCleanup(token_dir.cleanup)
        self.token_file = os.path.join(token_dir.name, "token")
        self._write_token("token-1")

        env = patch.dict(os.environ, {"KUBERNETES_SERVICE_HOST": "10.0.0.1", "KUBERNETES_SERVICE_PORT": "443"})
        env.start()
        self.addCleanup(env.stop)

        self.sleeps = []
        self.now = 1000.0

    def _write_token(self, value):
        with open(self.token_file, "w") as f:
            f.write(value + "\n")

    def _client(self, session):
        return KubernetesClient(
            "kubevoip",
            timeout=5,
            session=session,
            token_file=self.token_file,
            ca_file="/ca.crt",
            sleep=self.sleeps.append,
            clock=lambda: self.now,
        )

    def test_request_shape(self):
        session = StubSession(StubResponse(201, {"metadata": {"name": "tph-a"}}))

        result = self._client(session).create_resource(constants.KIND_SIP_USER, {"kind": "SIPUser"})

        self.assertEqual({"metadata": {"name": "tph-a"}}, result)
        request = session.requests[0]
        self.assertEqual("POST", request["method"])
        self.assertEqual(
            "https://10.0.0.1:443/apis/kubevoip.com/v1alpha1/namespaces/kubevoip/sipusers", request["url"]
        )
        self.assertEqual("Bearer token-1", request["headers"]["Authorization"])
        self.assertEqual("application/json", request["headers"]["Content-Type"])
        self.assertEqual(5, request["timeout"])
        self.assertEqual("/ca.crt", request["verify"])
        self.assertEqual({"kind": "SIPUser"}, json.loads(request["data"]))

    def test_token_is_read_on_every_request(self):
        session = StubSession(StubResponse(200, {}), StubResponse(200, {}))
        client = self._client(session)

        client.get_resource(constants.KIND_SIP_USER, "tph-a")
        self._write_token("token-2")
        client.get_resource(constants.KIND_SIP_USER, "tph-a")

        self.assertEqual("Bearer token-1", session.requests[0]["headers"]["Authorization"])
        self.assertEqual("Bearer token-2", session.requests[1]["headers"]["Authorization"])

    def test_list_uses_label_selector(self):
        session = StubSession(StubResponse(200, {"items": [{"metadata": {"name": "tph-a"}}]}))

        items = self._client(session).list_resources(constants.KIND_CALL_ROUTE, "weni.ai/managed-by=flows")

        self.assertEqual([{"metadata": {"name": "tph-a"}}], items)
        self.assertEqual({"labelSelector": "weni.ai/managed-by=flows"}, session.requests[0]["params"])
        self.assertTrue(session.requests[0]["url"].endswith("/namespaces/kubevoip/callroutes"))

    def test_secret_merge_patch(self):
        session = StubSession(StubResponse(200, {}))

        self._client(session).patch_secret_data("creds", {"tph-a": "c2VjcmV0", "tph-b": None})

        request = session.requests[0]
        self.assertEqual("PATCH", request["method"])
        self.assertTrue(request["url"].endswith("/api/v1/namespaces/kubevoip/secrets/creds"))
        self.assertEqual("application/merge-patch+json", request["headers"]["Content-Type"])
        self.assertEqual({"data": {"tph-a": "c2VjcmV0", "tph-b": None}}, json.loads(request["data"]))

    def test_get_secret(self):
        session = StubSession(StubResponse(200, {"data": {"tph-a": "c2VjcmV0"}}))

        self.assertEqual({"data": {"tph-a": "c2VjcmV0"}}, self._client(session).get_secret("creds"))
        self.assertTrue(session.requests[0]["url"].endswith("/api/v1/namespaces/kubevoip/secrets/creds"))

    def test_delete_with_empty_body(self):
        session = StubSession(StubResponse(200, None))

        self.assertEqual({}, self._client(session).delete_resource(constants.KIND_CALL_SCOPE, "tph-a"))

    def test_transient_status_is_retried_with_backoff_until_success(self):
        session = StubSession(StubResponse(503), StubResponse(429), StubResponse(200, {"ok": True}))

        result = self._client(session).get_resource(constants.KIND_SIP_USER, "tph-a")

        self.assertEqual({"ok": True}, result)
        self.assertEqual(3, len(session.requests))
        self.assertEqual([0.2, 0.4], self.sleeps)

    def test_connection_error_and_timeout_are_retried(self):
        session = StubSession(requests.ConnectionError("boom"), requests.Timeout("slow"), StubResponse(200, {}))

        self._client(session).get_resource(constants.KIND_SIP_USER, "tph-a")

        self.assertEqual(3, len(session.requests))

    def test_attempts_are_bounded(self):
        session = StubSession(*[StubResponse(500) for _ in range(10)])

        with self.assertRaises(KubernetesTransientError) as ctx:
            self._client(session).get_resource(constants.KIND_SIP_USER, "tph-a")

        self.assertEqual(constants.K8S_MAX_ATTEMPTS, len(session.requests))
        self.assertEqual(500, ctx.exception.status)

    def test_client_errors_are_not_retried(self):
        cases = [
            (403, KubernetesForbidden),
            (401, KubernetesForbidden),
            (404, KubernetesNotFound),
            (409, KubernetesConflict),
            (422, KubernetesRequestError),
        ]
        for status, expected in cases:
            with self.subTest(status=status):
                session = StubSession(StubResponse(status, {"reason": "SomeReason", "message": "x"}))

                with self.assertRaises(expected) as ctx:
                    self._client(session).get_resource(constants.KIND_SIP_USER, "tph-a")

                self.assertEqual(1, len(session.requests))
                self.assertEqual(status, ctx.exception.status)
                self.assertEqual("SomeReason", ctx.exception.reason)

    def test_error_never_carries_the_response_body(self):
        body = {"reason": "Invalid", "message": "secret-password-123 echoed from the manifest"}
        session = StubSession(StubResponse(422, body))

        with self.assertRaises(KubernetesRequestError) as ctx:
            self._client(session).create_resource(constants.KIND_SIP_USER, {})

        self.assertNotIn("secret-password-123", str(ctx.exception))

    def test_overall_deadline_stops_the_operation(self):
        session = StubSession(StubResponse(200, {}))
        client = self._client(session)
        client.begin_operation()
        self.now += constants.K8S_OVERALL_DEADLINE_SECS + 1

        with self.assertRaises(KubernetesTransientError):
            client.get_resource(constants.KIND_SIP_USER, "tph-a")

        self.assertEqual([], session.requests)

    def test_missing_credentials_are_a_configuration_error(self):
        client = self._client(StubSession())
        client.token_file = "/nonexistent/token"
        with self.assertRaises(KubernetesConfigurationError):
            client.get_resource(constants.KIND_SIP_USER, "tph-a")

        with patch.dict(os.environ, clear=False):
            os.environ.pop("KUBERNETES_SERVICE_HOST")
            with self.assertRaises(KubernetesConfigurationError):
                self._client(StubSession()).get_resource(constants.KIND_SIP_USER, "tph-a")

    def test_ipv6_host_is_bracketed(self):
        with patch.dict(os.environ, {"KUBERNETES_SERVICE_HOST": "2001:db8::1", "KUBERNETES_SERVICE_PORT": "443"}):
            session = StubSession(StubResponse(200, {}))
            self._client(session).get_resource(constants.KIND_SIP_USER, "tph-a")

        self.assertTrue(session.requests[0]["url"].startswith("https://[2001:db8::1]:443/"))

    def test_non_json_success_body_is_ignored(self):
        response = StubResponse(200)
        response.content = b"not-json"
        session = StubSession(response)

        self.assertEqual({}, self._client(session).delete_resource(constants.KIND_CALL_SCOPE, "tph-a"))

    def test_error_body_that_is_not_json_has_no_reason(self):
        session = StubSession(StubResponse(422))

        with self.assertRaises(KubernetesRequestError) as ctx:
            self._client(session).get_resource(constants.KIND_SIP_USER, "tph-a")

        self.assertIsNone(ctx.exception.reason)
