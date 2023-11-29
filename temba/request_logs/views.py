import json
import logging
import smtplib
from datetime import timedelta
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import BytesIO

import openpyxl
import pytz
from smartmin.views import SmartCRUDL, SmartListView, SmartReadView, SmartXlsView, smart_url

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _

from temba.classifiers.models import Classifier
from temba.orgs.views import OrgObjPermsMixin, OrgPermsMixin
from temba.tickets.models import Ticketer

from .models import HTTPLog

logger = logging.getLogger(__name__)


class BaseObjLogsView(OrgObjPermsMixin, SmartListView):
    """
    Base list view for logs associated with an object (e.g. ticketer, classifier)
    """

    paginate_by = 50
    permission = "request_logs.httplog_list"
    default_order = ("-created_on",)
    template_name = "request_logs/httplog_list.html"
    source_field = None
    source_url = None

    @classmethod
    def derive_url_pattern(cls, path, action):
        return r"^%s/%s/(?P<uuid>[^/]+)/$" % (path, action)

    def get_object_org(self):
        return self.source.org

    @cached_property
    def source(self):
        return get_object_or_404(self.get_source(self.kwargs["uuid"]))

    def get_source(self, uuid):  # pragma: no cover
        pass

    def get_queryset(self, **kwargs):
        return super().get_queryset(**kwargs).filter(**{self.source_field: self.source})

    def derive_select_related(self):
        return (self.source_field,)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["source"] = self.source
        context["source_url"] = smart_url(self.source_url, self.source)
        return context


class HTTPLogCRUDL(SmartCRUDL):
    model = HTTPLog
    actions = ("webhooks", "classifier", "ticketer", "read", "export")

    class Webhooks(OrgPermsMixin, SmartListView):
        title = _("Webhook Calls")
        default_order = ("-created_on",)
        select_related = ("flow",)

        fields = ("flow", "url", "status_code", "request_time", "created_on")

        def get_gear_links(self):
            return [dict(title=_("Flows"), style="button-light", href=reverse("flows.flow_list")),
                    dict(title=_("Export"), style="button-primary", button=True, on_click="exportLogs()")]

        def get_queryset(self, **kwargs):
            queryset = super().get_queryset(**kwargs).filter(org=self.request.org, flow__isnull=False)

            flow = self.request.GET.get("flow")
            created_on = self.request.GET.get("time")
            status_code = self.request.GET.get("status")

            if flow:
                queryset = queryset.filter(flow__name=flow)

            if created_on:
                time_range = timedelta(minutes=int(created_on))
                start_time = timezone.now() - time_range
                queryset = queryset.filter(created_on__gte=start_time)

            if status_code:
                queryset = queryset.filter(status_code=status_code)

            return queryset

        def has_permission(self, request, *args, **kwargs):
            if self.derive_org():
                if self.derive_org().config.get("can_view_httplogs"):  # pragma: no cover
                    return True
            return super().has_permission(request, *args, **kwargs)
        
        def get_context_data(self, **kwargs):
            context = super().get_context_data(**kwargs)
            context["flows"] = self.model.objects.filter(org=self.request.org, log_type=self.model.WEBHOOK_CALLED).values_list("flow__name", "flow__uuid", named=True).distinct()
            context["status_codes"] = self.model.objects.filter(org=self.request.org, log_type=self.model.WEBHOOK_CALLED).values_list("status_code", flat=True).distinct()
            return context

    class Classifier(BaseObjLogsView):
        source_field = "classifier"
        source_url = "uuid@classifiers.classifier_read"
        title = _("Recent Classifier Events")

        def get_source(self, uuid):
            return Classifier.objects.filter(uuid=uuid, is_active=True)

    class Ticketer(BaseObjLogsView):
        source_field = "ticketer"
        source_url = "@tickets.ticket_list"
        title = _("Recent Ticketing Service Events")

        def get_source(self, uuid):
            return Ticketer.objects.filter(uuid=uuid, is_active=True)

    class Read(OrgObjPermsMixin, SmartReadView):
        fields = ("description", "created_on")

        def has_permission(self, request, *args, **kwargs):
            if self.derive_org():
                if self.derive_org().config.get("can_view_httplogs"):  # pragma: no cover
                    return True
            return super().has_permission(request, *args, **kwargs)

        @property
        def permission(self):
            return "request_logs.httplog_webhooks" if self.get_object().flow else "request_logs.httplog_read"

        def get_gear_links(self):
            links = []
            if self.object.classifier:
                links.append(
                    dict(
                        title=_("Classifier Log"),
                        style="button-light",
                        href=reverse("request_logs.httplog_classifier", args=[self.object.classifier.uuid]),
                    )
                )
            return links

    class Export(OrgPermsMixin, SmartXlsView, SmartListView):
        def post(self, request, *args, **kwargs):
            try:
                data = json.loads(request.body.decode("utf-8"))
            except json.JSONDecodeError:
                return JsonResponse({"error": "Invalid JSON format"}, status=400)
            flow = data.get("flow")
            created_on = data.get("time")
            status_code = data.get("status")
            org = self.request.org
            user = self.request.user

            filename = "Chamadas Webhook.xlsx"

            queryset = HTTPLog.objects.filter(org=org, flow__isnull=False)

            if flow:
                queryset = queryset.filter(flow__name=flow)

            if created_on:
                time_range = timedelta(minutes=int(created_on))
                start_time = timezone.now() - time_range
                queryset = queryset.filter(created_on__gte=start_time)

            if status_code:
                queryset = queryset.filter(status_code=status_code)

            try:
                processed_data = self.process_queryset_results(queryset)
                xls_file = self.export_data_to_xls(processed_data)
                self.send_file(xls_file, filename, str(user), org.name)
                return HttpResponse(status=200)
            except Exception as e:
                logger.info(f"Fail to generate report: ORG {org.id}: {e}")
                return HttpResponse(status=500)

        def has_permission(self, request, *args, **kwargs):
            if self.derive_org():
                if self.derive_org().config.get("can_view_httplogs"):  # pragma: no cover
                    return True
            return super().has_permission(request, *args, **kwargs)

        def export_data_to_xls(self, queryset):
            workbook = openpyxl.Workbook()
            sheet = workbook.active

            header = [
                "URL",
                "Status",
                "Request",
                "Response",
                "Request Time",
                "Num Retries",
                "Created On",
                "Is Error",
                "Flow",
            ]
            sheet.append(header)

            for row in queryset:
                sheet.append(row)

            output = BytesIO()
            workbook.save(output)
            output.seek(0)

            # Verificar se o arquivo esta correto
            """output_bytes = output.getvalue()
            byte_stream = BytesIO(output_bytes)
            dados_excel = pd.read_excel(byte_stream)
            dados_excel.to_excel('/home/linhares/work/rapidpro/teste-xls.xlsx', index=False)
            print(dados_excel)"""
            return output

        def process_queryset_results(self, data):
            processed_data = []

            for row in data:
                processed_data.append(
                    (
                        row.url,
                        row.status_code,
                        row.request,
                        row.response,
                        row.request_time,
                        row.num_retries,
                        row.created_on.astimezone(pytz.utc).replace(tzinfo=None),
                        row.is_error,
                        row.flow.name if row.flow else "",
                    )
                )

            return processed_data

        # Exist a code in rp-apps that do almost the same thig. Refact to use the same code in future
        def send_file(self, file_stream, file_name, user_email, project_name):
            email_subject = "Exportação de dados de Webhooks"

            email_host = settings.EMAIL_HOST
            email_port = settings.EMAIL_PORT
            email_username = settings.EMAIL_HOST_USER
            email_password = settings.EMAIL_HOST_PASSWORD
            email_use_tls = settings.EMAIL_USE_TLS
            from_email = settings.DEFAULT_FROM_EMAIL

            email_body = render_to_string(
                "request_logs/httplog_mail_body.haml",
                {"project_name": project_name},
            )
            try:
                message = MIMEMultipart()
                message["Subject"] = email_subject
                message["From"] = from_email
                message["To"] = user_email

                body = MIMEText(email_body, "html", "utf-8")
                message.attach(body)

                attachment = MIMEBase("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                attachment.set_payload(file_stream.getvalue())
                encoders.encode_base64(attachment)
                attachment.add_header("Content-Disposition", f"attachment; filename={file_name}")
                message.attach(attachment)

                smtp_connection = smtplib.SMTP(host=email_host, port=email_port)
                smtp_connection.ehlo()

                if email_use_tls:
                    smtp_connection.starttls()

                smtp_connection.login(email_username, email_password)
                smtp_connection.sendmail
                result = smtp_connection.sendmail(from_email, str(user_email), message.as_string())
                smtp_connection.quit()

                if result:
                    for recipient, error_message in result.items():
                        logger.info(f"Fail send message to {recipient}, error: {error_message}")

            except Exception as e:
                logger.exception(f"Fail to send messages report: {e}")
