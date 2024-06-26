# Generated by Django 3.2.6 on 2021-08-27 19:25

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("channels", "0134_alter_channel_name"),
        ("flows", "0259_auto_20210825_1438"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("orgs", "0088_auto_20210715_1825"),
        ("contacts", "0142_auto_20210803_2000"),
        ("msgs", "0156_auto_20210722_1429"),
        ("tickets", "0022_auto_20210826_1553"),
    ]

    operations = [
        migrations.CreateModel(
            name="Log",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("log_type", models.CharField(max_length=16)),
                ("created_on", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "alert",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="logs",
                        to="channels.alert",
                    ),
                ),
                (
                    "broadcast",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="logs",
                        to="msgs.broadcast",
                    ),
                ),
                (
                    "contact_export",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="logs",
                        to="contacts.exportcontactstask",
                    ),
                ),
                (
                    "contact_import",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="logs",
                        to="contacts.contactimport",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="logs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "flow_start",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="logs",
                        to="flows.flowstart",
                    ),
                ),
                (
                    "message_export",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="logs",
                        to="msgs.exportmessagestask",
                    ),
                ),
                (
                    "org",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="logs", to="orgs.org"),
                ),
                (
                    "results_export",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="logs",
                        to="flows.exportflowresultstask",
                    ),
                ),
                (
                    "ticket",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="logs",
                        to="tickets.ticket",
                    ),
                ),
                (
                    "ticket_event",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="logs",
                        to="tickets.ticketevent",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("is_seen", models.BooleanField(default=False)),
                (
                    "log",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="notifications",
                        to="notifications.log",
                    ),
                ),
                (
                    "org",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, related_name="notifications", to="orgs.org"
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["org", "user", "-id"], name="notificatio_org_id_7a0120_idx"),
        ),
        migrations.AddIndex(
            model_name="log",
            index=models.Index(fields=["org", "-created_on"], name="notificatio_org_id_d0ef64_idx"),
        ),
    ]
