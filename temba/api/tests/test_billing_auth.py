from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, override_settings

from temba.api.auth.billing import BillingFixedAccessTokenAuthentication, HasBillingFixedAccessToken


class BillingFixedAccessTokenAuthenticationTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.auth = BillingFixedAccessTokenAuthentication()

    def test_no_token_returns_none(self):
        request = self.factory.get("/")
        self.assertIsNone(self.auth.authenticate(request))

    @override_settings(BILLING_FIXED_ACCESS_TOKEN="12345")
    def test_invalid_token_raises(self):
        request = self.factory.get("/?token=invalid")
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(request)

    @override_settings(BILLING_FIXED_ACCESS_TOKEN="12345")
    def test_valid_token_authenticates(self):
        request = self.factory.get("/?token=12345")
        user, auth = self.auth.authenticate(request)
        self.assertIsInstance(user, AnonymousUser)
        self.assertIsNone(auth)
        self.assertTrue(request.billing_fixed_access_authenticated)


class HasBillingFixedAccessTokenTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.permission = HasBillingFixedAccessToken()

    def test_denies_without_flag(self):
        request = self.factory.get("/")
        self.assertFalse(self.permission.has_permission(request, view=None))

    def test_allows_with_flag(self):
        request = self.factory.get("/")
        request.billing_fixed_access_authenticated = True
        self.assertTrue(self.permission.has_permission(request, view=None))
