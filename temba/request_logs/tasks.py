import logging
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.timesince import timesince

from celery import shared_task

from temba.utils.celery import nonoverlapping_task

from .models import HTTPLog

logger = logging.getLogger(__name__)


@nonoverlapping_task(track_started=True, name="trim_http_logs_task")
def trim_http_logs_task():
    trim_before = timezone.now() - settings.RETENTION_PERIODS["httplog"]
    num_deleted = 0
    start = timezone.now()

    logger.info(f"Deleting http logs which ended before {trim_before.isoformat()}...")

    while True:
        http_log_ids = HTTPLog.objects.filter(created_on__lte=trim_before).values_list("id", flat=True)[:1000]

        if not http_log_ids:
            break

        HTTPLog.objects.filter(id__in=http_log_ids).delete()
        num_deleted += len(http_log_ids)

        if num_deleted % 10000 == 0:  # pragma: no cover
            logger.debug(f" > Deleted {num_deleted} http logs")

    logger.info(f"Deleted {num_deleted} http logs in {timesince(start)}")


@shared_task(track_started=True, name="generate_sent_webhook_data")
def send_webhook_data(file_stream, file_name, user_email, project_name):
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
        smtp_connection.sendmail(from_email, str(user_email), message.as_string())
        smtp_connection.quit()  # pragma: no cover

    except Exception as e:
        logger.exception(f"Fail to send messages report: {e}")
