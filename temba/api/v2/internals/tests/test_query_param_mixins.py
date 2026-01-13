from types import SimpleNamespace

from django.test import SimpleTestCase
from rest_framework.response import Response

from temba.api.v2.mixins import ISO8601DateFilterQueryParamsMixin


class _DummyISO8601DateFilterQueryParams(ISO8601DateFilterQueryParamsMixin):
    pass


def _req(**query_params):
    return SimpleNamespace(query_params=query_params)


class ISO8601DateFilterQueryParamsMixinTest(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.mixin = _DummyISO8601DateFilterQueryParams()

    def test_no_params_returns_none_tuple(self):
        after_date, before_date = self.mixin.get_date_range_from_request(_req())
        self.assertIsNone(after_date)
        self.assertIsNone(before_date)

    def test_uses_aliases_when_primary_params_missing(self):
        after_date, before_date = self.mixin.get_date_range_from_request(
            _req(start_date="2026-01-01", end_date="2026-01-02")
        )
        self.assertEqual(str(after_date), "2026-01-01")
        self.assertEqual(str(before_date), "2026-01-02")

    def test_uses_primary_params_when_present(self):
        after_date, before_date = self.mixin.get_date_range_from_request(_req(after="2026-01-03", before="2026-01-04"))
        self.assertEqual(str(after_date), "2026-01-03")
        self.assertEqual(str(before_date), "2026-01-04")

    def test_invalid_after_returns_400(self):
        resp = self.mixin.get_date_range_from_request(_req(after="not-a-date"))
        self.assertIsInstance(resp, Response)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data, {"error": "Invalid after/start_date, expected ISO-8601 date"})

    def test_invalid_before_returns_400(self):
        resp = self.mixin.get_date_range_from_request(_req(after="2026-01-01", before="not-a-date"))
        self.assertIsInstance(resp, Response)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data, {"error": "Invalid before/end_date, expected ISO-8601 date"})

    def test_after_greater_than_before_returns_400(self):
        resp = self.mixin.get_date_range_from_request(_req(after="2026-01-03", before="2026-01-02"))
        self.assertIsInstance(resp, Response)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data, {"error": "after/start_date must be <= before/end_date"})

    def test_empty_string_primary_does_not_fall_back_to_alias(self):
        # If after is present but empty, we don't fall back to start_date because after_value isn't None.
        after_date, before_date = self.mixin.get_date_range_from_request(
            _req(after="", start_date="2026-01-01", before="", end_date="2026-01-02")
        )
        self.assertIsNone(after_date)
        self.assertIsNone(before_date)
