from datetime import timedelta
from types import SimpleNamespace

from django.test import TestCase
from django.utils import timezone

from temba.channels.models import ChannelLog
from temba.channels.usecases.message_error_logs import (
    failed_reason_for_api,
    load_error_logs_by_message_id,
    redact_authorization_headers,
)
from temba.msgs.models import Msg
from temba.tests import TembaTest


class RedactAuthorizationHeadersTest(TestCase):
    def test_replaces_header_values_and_leaves_other_text(self):
        request = "POST /send HTTP/1.1\r\nAuthorization: Bearer secret-token\r\nX-Other: keep\r\n\r\nsecret-token"
        response = "HTTP/1.1 200\r\nauthorization:Bearer other-token\r\n\r\nbody"

        self.assertIn("Authorization: ********", redact_authorization_headers(request))
        self.assertNotIn("secret-token", redact_authorization_headers(request))
        self.assertIn("X-Other: keep", redact_authorization_headers(request))
        self.assertIn("authorization:********", redact_authorization_headers(response))
        self.assertNotIn("other-token", redact_authorization_headers(response))
        self.assertIsNone(redact_authorization_headers(None))
        self.assertEqual("", redact_authorization_headers(""))

    def test_failed_reason_mapping(self):
        self.assertIsNone(failed_reason_for_api(SimpleNamespace(failed_reason=None)))
        self.assertIsNone(failed_reason_for_api(SimpleNamespace(failed_reason="")))
        self.assertEqual("suspended", failed_reason_for_api(SimpleNamespace(failed_reason=Msg.FAILED_SUSPENDED)))
        self.assertEqual("looping", failed_reason_for_api(SimpleNamespace(failed_reason=Msg.FAILED_LOOPING)))
        self.assertEqual("error_limit", failed_reason_for_api(SimpleNamespace(failed_reason=Msg.FAILED_ERROR_LIMIT)))
        self.assertEqual("too_old", failed_reason_for_api(SimpleNamespace(failed_reason=Msg.FAILED_TOO_OLD)))
        self.assertEqual(
            "no_destination", failed_reason_for_api(SimpleNamespace(failed_reason=Msg.FAILED_NO_DESTINATION))
        )
        self.assertIsNone(failed_reason_for_api(SimpleNamespace(failed_reason="Z")))


class MessageErrorLogsServiceTest(TembaTest):
    def test_inclusion_ordering_and_null_metadata(self):
        contact = self.create_contact("Ada", phone="+250788000111")
        delivered = self.create_outgoing_msg(contact, "ok", status=Msg.STATUS_DELIVERED)
        failed = self.create_outgoing_msg(contact, "nope", status=Msg.STATUS_FAILED)
        stamp = timezone.now()

        ChannelLog.objects.create(
            channel=delivered.channel,
            msg=delivered,
            description="Message Sent",
            is_error=False,
            method="POST",
            url="https://example.com/ok",
            request="ok",
            response="ok",
            response_status=200,
            request_time=5,
        )
        ChannelLog.objects.create(
            channel=failed.channel,
            msg=failed,
            description="older",
            is_error=False,
            method="POST",
            url="https://example.com/old",
            request="old",
            response="old",
            response_status=200,
            request_time=0,
            created_on=stamp - timedelta(seconds=1),
        )
        ChannelLog.objects.create(
            channel=failed.channel,
            msg=failed,
            description="newer-a",
            is_error=False,
            method="POST",
            url="https://example.com/a",
            request="a",
            response=None,
            response_status=None,
            request_time=None,
            created_on=stamp,
        )
        ChannelLog.objects.create(
            channel=failed.channel,
            msg=failed,
            description="newer-b",
            is_error=True,
            method="POST",
            url="https://example.com/b",
            request="b",
            response="b",
            response_status=500,
            request_time=8,
            created_on=stamp,
        )

        logs = load_error_logs_by_message_id([delivered, failed], self.admin, self.org, "default")

        self.assertNotIn(delivered.id, logs)
        self.assertEqual([item["description"] for item in logs[failed.id]], ["newer-b", "newer-a", "older"])
        self.assertEqual(logs[failed.id][0]["elapsed_ms"], 8)
        self.assertIsNone(logs[failed.id][1]["elapsed_ms"])
        self.assertIsNone(logs[failed.id][1]["response_status"])
        self.assertIsNone(logs[failed.id][1]["response"])
        self.assertEqual(logs[failed.id][2]["elapsed_ms"], 0)
