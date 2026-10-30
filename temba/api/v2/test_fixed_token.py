from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from django.test import TestCase, override_settings

from temba.api.auth.fixed_token import require_fixed_query_token


class RequireFixedQueryTokenTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def _request(self, path="/"):
        return Request(self.factory.post(path))

    def test_missing_token_raises_not_authenticated(self):
        request = self._request("/")
        with self.assertRaises(NotAuthenticated):
            require_fixed_query_token(request, "ROUTER_FIXED_ACCESS_TOKEN")

    @override_settings(ROUTER_FIXED_ACCESS_TOKEN="")
    def test_empty_setting_rejects_empty_query_token(self):
        request = self._request("/?token=")
        with self.assertRaises(AuthenticationFailed):
            require_fixed_query_token(request, "ROUTER_FIXED_ACCESS_TOKEN")

    @override_settings(ROUTER_FIXED_ACCESS_TOKEN="secret")
    def test_wrong_token_raises(self):
        request = self._request("/?token=nope")
        with self.assertRaises(AuthenticationFailed):
            require_fixed_query_token(request, "ROUTER_FIXED_ACCESS_TOKEN")

    @override_settings(ROUTER_FIXED_ACCESS_TOKEN="secret")
    def test_matching_token_returns_expected(self):
        request = self._request("/?token=secret")
        self.assertEqual(require_fixed_query_token(request, "ROUTER_FIXED_ACCESS_TOKEN"), "secret")
