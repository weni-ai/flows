import uuid
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytz

from django.test import override_settings

from temba.tests import TembaTest
from temba.utils.datalake.layer_validation import (
    LAYER_CHECKS,
    ProjectReport,
    TableResult,
    format_report,
    post_report_to_slack,
    previous_local_day_window,
    validate_layers,
)
from temba.utils.datalake.tasks import validate_datalake_layers_task

SAO_PAULO = pytz.timezone("America/Sao_Paulo")
# 02:30 in Sao Paulo, when the previous local day is validated
NOW = datetime(2026, 10, 8, 5, 30, 12, tzinfo=timezone.utc)
WEBHOOK_URL = "https://hooks.slack.com/services/T000/B000/XXXX"


def count_response(value):
    return [{"count": value}]


class PreviousLocalDayWindowTest(TembaTest):
    def test_returns_previous_local_day_in_utc(self):
        self.assertEqual(
            previous_local_day_window(NOW, SAO_PAULO),
            (date(2026, 10, 7), "2026-10-07T03:00:00Z", "2026-10-08T02:59:59Z"),
        )

    def test_uses_the_project_timezone(self):
        tokyo = pytz.timezone("Asia/Tokyo")

        self.assertEqual(
            previous_local_day_window(NOW, tokyo),
            (date(2026, 10, 7), "2026-10-06T15:00:00Z", "2026-10-07T14:59:59Z"),
        )


@patch("temba.utils.datalake.layer_validation.dl_get_events_silver_count")
@patch("temba.utils.datalake.layer_validation.dl_get_events_count")
class ValidateLayersTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.proj_uuid = str(uuid.uuid4())
        self.org.proj_uuid = self.proj_uuid
        self.org.timezone = SAO_PAULO
        self.org.save(update_fields=("proj_uuid", "timezone"))

    def test_projects_are_only_checked_at_the_local_validation_hour(self, mock_bronze, mock_silver):
        self.assertEqual(validate_layers(datetime(2026, 10, 8, 6, 30, tzinfo=timezone.utc), [self.proj_uuid]), [])

        mock_bronze.assert_not_called()
        mock_silver.assert_not_called()

    def test_bronze_and_silver_are_queried_with_the_same_filters(self, mock_bronze, mock_silver):
        mock_bronze.return_value = count_response(0)
        mock_silver.return_value = count_response(0)

        reports = validate_layers(NOW, [self.proj_uuid])

        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].day, date(2026, 10, 7))
        self.assertEqual(mock_bronze.call_count, len(LAYER_CHECKS))

        for bronze_call, silver_call in zip(mock_bronze.call_args_list, mock_silver.call_args_list):
            silver_kwargs = dict(silver_call.kwargs)
            table = silver_kwargs.pop("table")

            self.assertEqual(bronze_call.kwargs, silver_kwargs)
            self.assertEqual(bronze_call.kwargs["project"], self.proj_uuid)
            self.assertEqual(bronze_call.kwargs["date_start"], "2026-10-07T03:00:00Z")
            self.assertEqual(bronze_call.kwargs["date_end"], "2026-10-08T02:59:59Z")
            self.assertEqual(bronze_call.kwargs["event_name"], "weni_nexus_data")
            self.assertEqual(bronze_call.kwargs["key"], "conversation_classification")
            self.assertEqual(table, "conversation_classification")

    def test_divergent_classification_counts_are_reported(self, mock_bronze, mock_silver):
        mock_bronze.return_value = [{"count": "91"}]
        mock_silver.return_value = count_response(0)

        (report,) = validate_layers(NOW, [self.proj_uuid])

        (result,) = report.results
        self.assertEqual(result.table, "conversation_classification")
        self.assertEqual((result.bronze, result.silver, result.status), (91, 0, "DIVERGENT"))
        self.assertEqual((report.org_name, report.project_uuid), (self.org.name, self.proj_uuid))

    def test_query_failures_are_reported_as_errors(self, mock_bronze, mock_silver):
        mock_bronze.return_value = [{"count": "91"}]
        mock_silver.side_effect = Exception("Could not send message to DC API!")

        with self.assertLogs("temba.utils.datalake.layer_validation", level="ERROR"):
            (report,) = validate_layers(NOW, [self.proj_uuid])

        (result,) = report.results
        self.assertEqual(result.status, "ERROR")

    def test_empty_count_responses_are_zero(self, mock_bronze, mock_silver):
        mock_bronze.return_value = [{}]
        mock_silver.return_value = []

        (report,) = validate_layers(NOW, [self.proj_uuid])

        self.assertEqual({result.status for result in report.results}, {"OK"})
        self.assertEqual(report.results[0].bronze, 0)

    def test_invalid_project_uuid_is_logged_and_skipped(self, mock_bronze, mock_silver):
        mock_bronze.return_value = count_response(0)
        mock_silver.return_value = count_response(0)

        with self.assertLogs("temba.utils.datalake.layer_validation", level="ERROR") as logs:
            reports = validate_layers(NOW, ["not-a-uuid", self.proj_uuid])

        self.assertEqual(len(reports), 1)
        self.assertTrue(any("skipped invalid project uuid" in message for message in logs.output))

    def test_unknown_or_inactive_projects_are_logged_and_skipped(self, mock_bronze, mock_silver):
        self.org2.proj_uuid = uuid.uuid4()
        self.org2.is_active = False
        self.org2.save(update_fields=("proj_uuid", "is_active"))

        with self.assertLogs("temba.utils.datalake.layer_validation", level="ERROR") as logs:
            reports = validate_layers(NOW, [str(uuid.uuid4()), str(self.org2.proj_uuid)])

        self.assertEqual(reports, [])
        self.assertEqual(len(logs.output), 2)
        mock_bronze.assert_not_called()


class FormatReportTest(TembaTest):
    def test_summary_lists_each_project_and_table(self):
        report = ProjectReport(
            org_name="Acme",
            project_uuid="1a2b",
            timezone="America/Sao_Paulo",
            day=date(2026, 10, 7),
            results=[
                TableResult("conversation_classification", bronze=91, silver=0),
            ],
        )

        text = format_report([report])

        self.assertIn("Projects checked: 1 | With problems: 1", text)
        self.assertIn("*Acme* (`1a2b`) | 2026-10-07 (America/Sao_Paulo)", text)
        self.assertIn("• conversation_classification: bronze=91 silver=0 (-91) DIVERGENT", text)

    def test_format_report_includes_error_line(self):
        report = ProjectReport(
            org_name="Acme",
            project_uuid="1a2b",
            timezone="America/Sao_Paulo",
            day=date(2026, 10, 7),
            results=[TableResult("conversation_classification", error=True)],
        )

        text = format_report([report])

        self.assertIn("• conversation_classification: ERROR", text)
        self.assertIn("With problems: 1", text)


class PostReportToSlackTest(TembaTest):
    @override_settings(DATALAKE_VALIDATION_SLACK_WEBHOOK_URL=WEBHOOK_URL)
    @patch("temba.utils.datalake.layer_validation.requests.post")
    def test_posts_formatted_text_to_webhook(self, mock_post):
        with patch("temba.utils.datalake.layer_validation.format_report", return_value="summary"):
            post_report_to_slack([])

        mock_post.assert_called_once_with(WEBHOOK_URL, json={"text": "summary"}, timeout=10)
        mock_post.return_value.raise_for_status.assert_called_once()


@override_settings(DATALAKE_VALIDATION_SLACK_WEBHOOK_URL=WEBHOOK_URL, DATALAKE_VALIDATION_PROJECTS=["1a2b"])
class ValidateDatalakeLayersTaskTest(TembaTest):
    @override_settings(DATALAKE_VALIDATION_SLACK_WEBHOOK_URL="")
    @patch("temba.utils.datalake.tasks.validate_layers")
    def test_skips_when_webhook_is_not_configured(self, mock_validate):
        with self.assertLogs("temba.utils.datalake.tasks", level="WARNING"):
            validate_datalake_layers_task()

        mock_validate.assert_not_called()

    @override_settings(DATALAKE_VALIDATION_PROJECTS=[])
    @patch("temba.utils.datalake.tasks.validate_layers")
    def test_skips_when_no_projects_are_configured(self, mock_validate):
        with self.assertLogs("temba.utils.datalake.tasks", level="WARNING"):
            validate_datalake_layers_task()

        mock_validate.assert_not_called()

    @patch("temba.utils.datalake.tasks.post_report_to_slack")
    @patch("temba.utils.datalake.tasks.validate_layers", return_value=[])
    def test_does_not_post_when_no_project_was_due(self, mock_validate, mock_post):
        validate_datalake_layers_task()

        mock_validate.assert_called_once()
        self.assertEqual(mock_validate.call_args.args[1], ["1a2b"])
        mock_post.assert_not_called()

    @patch("temba.utils.datalake.tasks.post_report_to_slack")
    @patch("temba.utils.datalake.tasks.validate_layers")
    def test_posts_reports_of_checked_projects(self, mock_validate, mock_post):
        validate_datalake_layers_task()

        mock_post.assert_called_once_with(mock_validate.return_value)
