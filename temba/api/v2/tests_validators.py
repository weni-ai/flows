import unittest
from types import SimpleNamespace
from unittest.mock import patch

from temba.api.v2.validators import LambdaURLValidator


class LambdaURLValidatorTest(unittest.TestCase):
    def setUp(self):
        self.validator = LambdaURLValidator()

    def test_is_valid_url_with_list(self):
        stub_settings = SimpleNamespace(
            LAMBDA_VALIDATION_URL=[
                "https://sts.amazonaws.com/?Action=GetCallerIdentity&",
                "https://example.com/auth/sts?Action=GetCallerIdentity&",
            ]
        )
        with patch("temba.api.v2.validators.settings", stub_settings):
            self.assertTrue(
                self.validator.is_valid_url(
                    "https://sts.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15&X-Amz-Algorithm=AWS4-HMAC-SHA256"
                )
            )
            self.assertTrue(
                self.validator.is_valid_url("https://example.com/auth/sts?Action=GetCallerIdentity&Version=2011-06-15")
            )
            self.assertFalse(
                self.validator.is_valid_url("https://malicious.com/?Action=GetCallerIdentity&Version=2011-06-15")
            )

    def test_is_valid_url_rejects_dotdot(self):
        stub_settings = SimpleNamespace(LAMBDA_VALIDATION_URL=["https://sts.amazonaws.com/?Action=GetCallerIdentity&"])
        with patch("temba.api.v2.validators.settings", stub_settings):
            self.assertFalse(
                self.validator.is_valid_url(
                    "https://sts.amazonaws.com/?Action=GetCallerIdentity&..&Version=2011-06-15"
                )
            )
