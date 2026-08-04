import os
from unittest import TestCase, mock

from redis.exceptions import LockNotOwnedError

from temba.sentry_config import get_float_env, get_ignored_errors_from_env


class GetFloatEnvTest(TestCase):
    def test_returns_default_when_missing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_float_env("SENTRY_SAMPLE_RATE", 1.0), 1.0)

    def test_returns_default_when_empty(self):
        with mock.patch.dict(os.environ, {"SENTRY_SAMPLE_RATE": ""}, clear=False):
            self.assertEqual(get_float_env("SENTRY_SAMPLE_RATE", 0.5), 0.5)

    def test_parses_valid_float(self):
        with mock.patch.dict(os.environ, {"SENTRY_TRACES_SAMPLE_RATE": "0.1"}):
            self.assertEqual(get_float_env("SENTRY_TRACES_SAMPLE_RATE", 1.0), 0.1)

    def test_returns_default_on_invalid_value(self):
        with mock.patch.dict(os.environ, {"SENTRY_PROFILES_SAMPLE_RATE": "abc"}):
            self.assertEqual(get_float_env("SENTRY_PROFILES_SAMPLE_RATE", 0.0), 0.0)


class GetIgnoredErrorsFromEnvTest(TestCase):
    def test_returns_empty_when_unset(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("SENTRY_IGNORE_ERRORS", None)
            self.assertEqual(get_ignored_errors_from_env(), [])

    def test_resolves_builtin_exceptions(self):
        with mock.patch.dict(os.environ, {"SENTRY_IGNORE_ERRORS": "ValueError, KeyError"}):
            self.assertEqual(get_ignored_errors_from_env(), [ValueError, KeyError])

    def test_resolves_custom_exceptions(self):
        with mock.patch.dict(os.environ, {"SENTRY_IGNORE_ERRORS": "LockNotOwnedError"}):
            self.assertEqual(get_ignored_errors_from_env(), [LockNotOwnedError])

    def test_skips_unknown_names(self):
        with mock.patch.dict(os.environ, {"SENTRY_IGNORE_ERRORS": "ValueError,NotARealError"}):
            self.assertEqual(get_ignored_errors_from_env(), [ValueError])

    def test_ignores_non_exception_builtins(self):
        with mock.patch.dict(os.environ, {"SENTRY_IGNORE_ERRORS": "int,ValueError"}):
            self.assertEqual(get_ignored_errors_from_env(), [ValueError])
