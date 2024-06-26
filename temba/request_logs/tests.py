from datetime import datetime, timedelta
from io import BytesIO
from unittest.mock import MagicMock, Mock, patch

from requests import RequestException

from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from temba.classifiers.models import Classifier
from temba.classifiers.types.wit import WitType
from temba.contacts.models import ContactURN
from temba.request_logs.views import HTTPLogCRUDL
from temba.tests import CRUDLTestMixin, MockResponse, TembaTest
from temba.tickets.models import Ticketer
from temba.tickets.types.mailgun import MailgunType

from .models import HTTPLog
from .tasks import trim_http_logs_task


class HTTPLogTest(TembaTest):
    def test_trim_logs_task(self):
        c1 = Classifier.create(self.org, self.admin, WitType.slug, "Booker", {}, sync=False)

        HTTPLog.objects.create(
            classifier=c1,
            url="http://org1.bar/zap/?text=" + ("0123456789" * 30),
            request="GET /zap",
            response=" OK 200",
            is_error=False,
            log_type=HTTPLog.INTENTS_SYNCED,
            request_time=10,
            org=self.org,
            created_on=timezone.now() - timedelta(days=7),
        )
        l2 = HTTPLog.objects.create(
            classifier=c1,
            url="http://org2.bar/zap",
            request="GET /zap",
            response=" OK 200",
            is_error=False,
            log_type=HTTPLog.CLASSIFIER_CALLED,
            request_time=10,
            org=self.org,
        )

        trim_http_logs_task()

        # should only have one log remaining and should be l2
        self.assertEqual(1, HTTPLog.objects.all().count())
        self.assertTrue(HTTPLog.objects.filter(id=l2.id))


class HTTPLogCRUDLTest(TembaTest, CRUDLTestMixin):
    def test_webhooks(self):
        flow = self.create_flow()
        l1 = HTTPLog.objects.create(
            org=self.org,
            log_type="webhook_called",
            url="http://org1.bar/",
            request="GET /zap",
            response=" OK 200",
            request_time=10,
            is_error=False,
            flow=flow,
        )

        # log from other org
        HTTPLog.objects.create(
            org=self.org2,
            log_type="webhook_called",
            url="http://org1.bar/",
            request="GET /zap",
            response=" OK 200",
            request_time=10,
            is_error=False,
            flow=flow,
        )

        # non-webhook log
        HTTPLog.objects.create(
            org=self.org,
            log_type="intents_synced",
            url="http://org1.bar/",
            request="GET /zap",
            response=" OK 200",
            request_time=10,
            is_error=False,
        )

        webhooks_url = reverse("request_logs.httplog_webhooks")
        log_url = reverse("request_logs.httplog_read", args=[l1.id])

        response = self.assertListFetch(webhooks_url, allow_viewers=False, allow_editors=True, context_objects=[l1])
        self.assertContains(response, "Webhook Calls")
        self.assertContains(response, log_url)

        # view the individual log item
        response = self.assertReadFetch(log_url, allow_viewers=False, allow_editors=True, context_object=l1)
        self.assertContains(response, "200")
        self.assertContains(response, "http://org1.bar/")

    def test_classifier(self):
        c1 = Classifier.create(self.org, self.admin, WitType.slug, "Booker", {}, sync=False)
        c2 = Classifier.create(self.org, self.admin, WitType.slug, "Old Booker", {}, sync=False)
        c2.is_active = False
        c2.save()

        l1 = HTTPLog.objects.create(
            classifier=c1,
            url="http://org1.bar/zap/?text=" + ("0123456789" * 30),
            request="GET /zap",
            response=" OK 200",
            is_error=False,
            log_type=HTTPLog.INTENTS_SYNCED,
            request_time=10,
            org=self.org,
        )
        HTTPLog.objects.create(
            classifier=c2,
            url="http://org2.bar/zap",
            request="GET /zap",
            response=" OK 200",
            is_error=False,
            log_type=HTTPLog.CLASSIFIER_CALLED,
            request_time=10,
            org=self.org,
        )

        list_url = reverse("request_logs.httplog_classifier", args=[c1.uuid])
        log_url = reverse("request_logs.httplog_read", args=[l1.id])

        response = self.assertListFetch(
            list_url, allow_viewers=False, allow_editors=False, allow_org2=False, context_objects=[l1]
        )
        self.assertContains(response, "Intents Synced")
        self.assertContains(response, log_url)
        self.assertNotContains(response, "Classifier Called")

        # view the individual log item
        response = self.assertReadFetch(log_url, allow_viewers=False, allow_editors=False, context_object=l1)
        self.assertContains(response, "200")
        self.assertContains(response, "http://org1.bar/zap")
        self.assertNotContains(response, "http://org2.bar/zap")

        # can't list logs for deleted classifier
        response = self.requestView(reverse("request_logs.httplog_classifier", args=[c2.uuid]), self.admin)
        self.assertEqual(404, response.status_code)

    def test_ticketer(self):
        t1 = Ticketer.create(self.org, self.admin, MailgunType.slug, "Email (bob@acme.com)", {})
        t2 = Ticketer.create(self.org, self.admin, MailgunType.slug, "Old Email", {})
        t2.is_active = False
        t2.save()

        # create some logs
        l1 = HTTPLog.objects.create(
            ticketer=t1,
            url="http://org1.bar/zap",
            request="GET /zap",
            response=" OK 200",
            is_error=False,
            log_type=HTTPLog.TICKETER_CALLED,
            request_time=10,
            org=self.org,
        )

        list_url = reverse("request_logs.httplog_ticketer", args=[t1.uuid])
        log_url = reverse("request_logs.httplog_read", args=[l1.id])

        response = self.assertListFetch(
            list_url, allow_viewers=False, allow_editors=False, allow_org2=False, context_objects=[l1]
        )
        self.assertContains(response, "Ticketing Service Called")
        self.assertContains(response, log_url)

        # view the individual log item
        response = self.assertReadFetch(log_url, allow_viewers=False, allow_editors=False, context_object=l1)
        self.assertContains(response, "200")
        self.assertContains(response, "http://org1.bar/zap")
        self.assertNotContains(response, "http://org2.bar/zap")

        # can't list logs for deleted ticketer
        response = self.requestView(reverse("request_logs.httplog_ticketer", args=[t2.uuid]), self.admin)
        self.assertEqual(404, response.status_code)

    @override_settings(WHATSAPP_ADMIN_SYSTEM_USER_TOKEN="WA_ADMIN_TOKEN")
    def test_http_log(self):
        channel = self.create_channel("WA", "WhatsApp: 1234", "1234")

        exception = RequestException("Network is unreachable", response=MockResponse(100, ""))
        start = timezone.now()

        log1 = HTTPLog.create_from_exception(
            HTTPLog.WHATSAPP_TEMPLATES_SYNCED,
            "https://graph.facebook.com/v14.0/1234/message_templates",
            exception,
            start,
            channel=channel,
        )

        self.login(self.admin)
        log_url = reverse("request_logs.httplog_read", args=[log1.id])
        response = self.client.get(log_url)
        self.assertContains(response, "200")
        self.assertContains(response, "Connection Error")
        self.assertContains(response, "https://graph.facebook.com/v14.0/1234/message_templates")

        log2 = HTTPLog.create_from_exception(
            HTTPLog.WHATSAPP_TEMPLATES_SYNCED,
            f"https://graph.facebook.com/v14.0/1234/message_templates?access_token={settings.WHATSAPP_ADMIN_SYSTEM_USER_TOKEN}",
            exception,
            start,
            channel=channel,
        )
        log2_url = reverse("request_logs.httplog_read", args=[log2.id])
        response = self.client.get(log2_url)
        self.assertContains(response, "200")
        self.assertContains(response, "Connection Error")
        self.assertContains(
            response, f"https://graph.facebook.com/v14.0/1234/message_templates?access_token={ContactURN.ANON_MASK}"
        )

        # and can't be from other org
        self.login(self.admin2)
        response = self.client.get(log_url)
        self.assertLoginRedirect(response)


class HTTPLogCRUDLQuerySetTest(TembaTest, CRUDLTestMixin):
    def test_get_queryset_with_parameters(self):
        HTTPLog.objects.create(
            url="https://org2.bar/zap",
            request="GET /zap",
            response=" OK 200",
            is_error=False,
            log_type=HTTPLog.WEBHOOK_CALLED,
            request_time=10,
            org=self.org,
        )

        log2 = HTTPLog.objects.create(
            url="https://org2.bar/zapzap",
            request="GET /zap",
            response=" OK 200",
            is_error=False,
            log_type=HTTPLog.WEBHOOK_CALLED,
            request_time=10,
            org=self.org,
            flow=self.get_flow("dependencies"),
        )

        webhooks_url = reverse("request_logs.httplog_webhooks")
        log_url = reverse("request_logs.httplog_read", args=[log2.id])

        response = self.assertListFetch(webhooks_url, allow_viewers=False, allow_editors=True, context_objects=[log2])
        self.assertContains(response, "Webhook Calls")
        self.assertContains(response, log_url)

        self.client.get(webhooks_url + "?flow=dependencies")
        self.client.get(webhooks_url + "?time=5")
        self.client.get(webhooks_url + "?status=200")


class ExportTest(TembaTest):
    @patch("temba.request_logs.views.HTTPLogCRUDL.Export.send_file")
    def test_invalid_json_format(self, mock_json_error):
        export_instance = HTTPLogCRUDL.Export()
        factory = RequestFactory()

        request = factory.post("/export/", data="invalid_json", content_type="application/json")
        export_instance.request = request

        response = export_instance.post(export_instance.request)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content, b'{"error": "Invalid JSON format"}')

    @patch("temba.request_logs.views.HTTPLogCRUDL.Export.process_queryset_results")
    @patch("temba.request_logs.views.HTTPLogCRUDL.Export.export_data_to_xls")
    @patch("temba.request_logs.views.HTTPLogCRUDL.Export.send_file")
    def test_post_success(self, mock_send_file, mock_export_data_to_xls, mock_process_queryset_results):
        mock_request = MagicMock()
        mock_request.body.decode.return_value = '{"flow": "some_flow", "time": 10, "status": 200}'
        mock_request.org = self.org
        mock_request.user = MagicMock(email="test2@example.com")
        mock_http_log = MagicMock()
        mock_process_queryset_results.return_value = mock_http_log
        mock_export_data_to_xls.return_value = "xls_content"

        export_instance = HTTPLogCRUDL.Export()

        export_instance.request = mock_request

        response = export_instance.post(mock_request)

        mock_process_queryset_results.assert_called_once()
        mock_export_data_to_xls.assert_called_once_with(mock_http_log)
        mock_send_file.assert_called_once_with("xls_content", "Chamadas Webhook.xlsx", "test2@example.com", "Temba")
        self.assertIsInstance(response, HttpResponse)
        self.assertEqual(response.status_code, 200)

    @patch("temba.request_logs.views.HTTPLogCRUDL.Export.process_queryset_results")
    @patch("temba.request_logs.views.HTTPLogCRUDL.Export.export_data_to_xls")
    @patch("temba.request_logs.views.HTTPLogCRUDL.Export.send_file")
    @patch("temba.request_logs.views.logger")
    def test_post_exception_handling(
        self, mock_logger, mock_send_file, mock_export_data_to_xls, mock_process_queryset_results
    ):
        mock_request = MagicMock()
        mock_request.body.decode.return_value = '{"flow": "some_flow", "time": 10, "status": 200}'
        mock_request.org = self.org
        mock_request.user = MagicMock(email="test@example.com")
        mock_process_queryset_results.side_effect = Exception("Some error message")

        export_instance = HTTPLogCRUDL.Export()

        export_instance.request = mock_request

        response = export_instance.post(mock_request)

        self.assertIsInstance(response, HttpResponse)
        self.assertEqual(response.status_code, 500)

    @patch("temba.request_logs.views.openpyxl.Workbook")
    @patch("temba.request_logs.views.BytesIO", side_effect=BytesIO)
    def test_export_data_to_xls(self, mock_bytesio, mock_workbook):
        mock_query = Mock()
        mock_query.url = "https://example.com"

        export_instance = HTTPLogCRUDL.Export()
        export_instance.export_data_to_xls([mock_query])

        mock_workbook.assert_called_once()
        mock_bytesio.assert_called_once()

    def test_process_queryset_results(self):
        mock_http_log = Mock()
        mock_http_log.url = "https://example.com"
        mock_http_log.status_code = 200
        mock_http_log.request = "mock_request"
        mock_http_log.response = "mock_response"
        mock_http_log.request_time = "2023-11-28T12:00:00Z"
        mock_http_log.num_retries = 1
        mock_http_log.created_on = datetime.strptime("2023-11-28T12:00:00Z", "%Y-%m-%dT%H:%M:%SZ")
        mock_http_log.is_error = False
        mock_http_log.flow = Mock(name="mock_flow")

        mock_queryset = [mock_http_log]

        export_instance = HTTPLogCRUDL.Export()

        processed_data = export_instance.process_queryset_results(mock_queryset)

        self.assertEqual(len(processed_data), 1)

        expected_tuple = (
            "https://example.com",
            mock_http_log.status_code,
            mock_http_log.request,
            mock_http_log.response,
            mock_http_log.request_time,
            mock_http_log.num_retries,
            mock_http_log.created_on.astimezone().replace(tzinfo=None),
            mock_http_log.is_error,
            mock_http_log.flow.name,
        )
        self.assertEqual(processed_data[0], expected_tuple)

    @patch("smtplib.SMTP")
    def test_send_file_email(self, mock_smtp):
        settings.EMAIL_HOST = "your_email_host"
        settings.EMAIL_PORT = 587
        settings.EMAIL_USE_TLS = True
        settings.EMAIL_HOST_USER = "your_email_username"
        settings.EMAIL_HOST_PASSWORD = "your_email_password"
        settings.DEFAULT_FROM_EMAIL = "your_from_email"

        view = HTTPLogCRUDL.Export()

        file_stream = BytesIO(b"Test file content")
        file_name = "example.xlsx"
        user_email = "user@example.com"
        project_name = "Test Project"

        mock_sendmail = MagicMock()
        mock_smtp.return_value.sendmail = mock_sendmail

        view.send_file(file_stream, file_name, [user_email], project_name)

        mock_connection = mock_smtp.return_value
        mock_connection.ehlo.assert_called_once()
        mock_connection.starttls.assert_called_once_with()
        mock_connection.login.assert_called_once_with("your_email_username", "your_email_password")
