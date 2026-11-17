from datetime import timedelta
from types import SimpleNamespace

from django.test import TestCase
from django.utils import timezone

from temba.channels.models import ChannelLog
from temba.channels.usecases.message_error_logs import (
    _display_value,
    failed_reason_for_api,
    load_error_logs_by_message_id,
    redact_authorization_headers,
)
from temba.contacts.models import ContactURN
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

    def test_leaves_short_header_values_in_the_body(self):
        trace = "GET / HTTP/1.1\r\nAuthorization: abc\r\n\r\nabc stays"
        redacted = redact_authorization_headers(trace)

        self.assertIn("Authorization: ********", redacted)
        self.assertIn("abc stays", redacted)

        already_masked = "GET / HTTP/1.1\r\nAuthorization: ********\r\n\r\nstill here"
        self.assertIn("still here", redact_authorization_headers(already_masked))

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

    def test_empty_page_and_messages_that_do_not_qualify(self):
        self.assertEqual(load_error_logs_by_message_id([], self.admin, self.org, "default"), {})
        self.assertEqual(load_error_logs_by_message_id(None, self.admin, self.org, "default"), {})

        contact = self.create_contact("Bea", phone="+250788000222")
        delivered = self.create_outgoing_msg(contact, "ok", status=Msg.STATUS_DELIVERED)
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
            request_time=1,
        )

        self.assertEqual(load_error_logs_by_message_id([delivered], self.admin, self.org, "default"), {})

    def test_anonymous_org_masks_when_the_urn_cannot_be_redacted(self):
        self.org.is_anon = True
        self.org.save(update_fields=["is_anon"])
        contact = self.create_contact("Cara", phone="+250788000333")
        missing_urn = self.create_outgoing_msg(contact, "missing", status=Msg.STATUS_FAILED)
        missing_urn.contact_urn = None
        missing_urn.save(update_fields=["contact_urn"])
        ChannelLog.objects.create(
            channel=missing_urn.channel,
            msg=missing_urn,
            description="Message Send Error",
            is_error=True,
            method="POST",
            url="https://example.com/missing",
            request="POST /send HTTP/1.1\r\n\r\nplain",
            response="plain",
            response_status=400,
            request_time=1,
        )

        untouched = self.create_outgoing_msg(contact, "untouched", status=Msg.STATUS_FAILED)
        ChannelLog.objects.create(
            channel=untouched.channel,
            msg=untouched,
            description="Message Send Error",
            is_error=True,
            method="POST",
            url="https://example.com/untouched",
            request="POST /send HTTP/1.1\r\n\r\nno contact here",
            response="no contact here",
            response_status=400,
            request_time=1,
        )

        logs = load_error_logs_by_message_id([missing_urn, untouched], self.admin, self.org, "default")

        self.assertEqual(logs[missing_urn.id][0]["request"], ContactURN.ANON_MASK)
        self.assertEqual(logs[untouched.id][0]["request"], ContactURN.ANON_MASK)
        self.assertEqual(logs[untouched.id][0]["url"], ContactURN.ANON_MASK)

        empty_path = SimpleNamespace(
            msg_id=untouched.id,
            msg=SimpleNamespace(contact_urn_id=1, contact_urn=SimpleNamespace(path="")),
        )
        self.assertEqual(
            _display_value(empty_path, "POST /send HTTP/1.1\r\n\r\nbody", reveal_urns=False, redact_keys=()),
            ContactURN.ANON_MASK,
        )

    def test_redacts_json_body_keys_for_channel_types_that_declare_them(self):
        self.org.is_anon = True
        self.org.save(update_fields=["is_anon"])
        contact = self.create_contact("Dee", phone="+250788000444")
        msg = self.create_outgoing_msg(contact, "keyed", status=Msg.STATUS_FAILED)
        msg.channel.channel_type = "TWT"
        msg.channel.save(update_fields=["channel_type"])
        path = msg.contact_urn.path
        ChannelLog.objects.create(
            channel=msg.channel,
            msg=msg,
            description="Message Sent",
            is_error=True,
            method="POST",
            url=f"https://example.com/send?to={path}",
            request=f'POST /send HTTP/1.1\r\n\r\n{{"sender_id":"{path}","text":"hello"}}',
            response=f'{{"urn":"{path}"}}',
            response_status=400,
            request_time=3,
        )

        logs = load_error_logs_by_message_id([msg], self.admin, self.org, "default")
        item = logs[msg.id][0]

        self.assertNotIn(path, item["request"])
        self.assertNotIn(path, item["response"])
        self.assertIn("hello", item["request"])
