import iso8601
from rest_framework.request import Request
from rest_framework.response import Response


class ISO8601DateFilterQueryParamsMixin:
    """
    Helpers for parsing inclusive date range filters from query params.

    Conventions:
    - `after` / `before` are the API v2 defaults
    - `start_date` / `end_date` are accepted as aliases

    Values may be any ISO-8601 datetime or date; we coerce to `.date()`.
    """

    after_param = "after"
    before_param = "before"
    after_aliases = ("start_date",)
    before_aliases = ("end_date",)

    def _parse_iso_date(self, value: str, *, error_message: str):
        try:
            return iso8601.parse_date(value).date()
        except Exception:
            return Response(status=400, data={"error": error_message})

    def get_date_range_from_request(self, request: Request):
        params = getattr(request, "query_params", None) or {}

        after_value = params.get(self.after_param)
        if after_value is None:
            for alias in self.after_aliases:
                after_value = params.get(alias)
                if after_value:
                    break

        before_value = params.get(self.before_param)
        if before_value is None:
            for alias in self.before_aliases:
                before_value = params.get(alias)
                if before_value:
                    break

        after_date = None
        before_date = None

        if after_value:
            parsed = self._parse_iso_date(
                after_value, error_message="Invalid after/start_date, expected ISO-8601 date"
            )
            if isinstance(parsed, Response):
                return parsed
            after_date = parsed

        if before_value:
            parsed = self._parse_iso_date(
                before_value, error_message="Invalid before/end_date, expected ISO-8601 date"
            )
            if isinstance(parsed, Response):
                return parsed
            before_date = parsed

        if after_date and before_date and after_date > before_date:
            return Response(status=400, data={"error": "after/start_date must be <= before/end_date"})

        return after_date, before_date
