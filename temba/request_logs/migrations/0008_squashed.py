# Generated by Django 2.2.10 on 2020-12-04 17:21

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("airtime", "0017_squashed"),
        ("orgs", "0072_squashed"),
        ("classifiers", "0004_squashed"),
        ("tickets", "0004_squashed"),
        ("channels", "0124_squashed"),
    ]

    operations = [
        migrations.CreateModel(
            name="HTTPLog",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "log_type",
                    models.CharField(
                        choices=[
                            ("intents_synced", "Intents Synced"),
                            ("classifier_called", "Classifier Called"),
                            ("ticketer_called", "Ticketing Service Called"),
                            ("airtime_transferred", "Airtime Transferred"),
                            ("whatsapp_templates_synced", "WhatsApp Templates Synced"),
                            ("whatsapp_tokens_synced", "WhatsApp Tokens Synced"),
                            ("whatsapp_contacts_refreshed", "WhatsApp Contacts Refreshed"),
                        ],
                        max_length=32,
                    ),
                ),
                ("url", models.URLField()),
                ("request", models.TextField()),
                ("response", models.TextField(null=True)),
                ("is_error", models.BooleanField()),
                ("request_time", models.IntegerField()),
                ("created_on", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "airtime_transfer",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="http_logs",
                        to="airtime.AirtimeTransfer",
                    ),
                ),
                (
                    "channel",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="http_logs",
                        to="channels.Channel",
                    ),
                ),
                (
                    "classifier",
                    models.ForeignKey(
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="http_logs",
                        to="classifiers.Classifier",
                    ),
                ),
                (
                    "org",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, related_name="http_logs", to="orgs.Org"
                    ),
                ),
                (
                    "ticketer",
                    models.ForeignKey(
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="http_logs",
                        to="tickets.Ticketer",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="httplog",
            index=models.Index(fields=["classifier", "-created_on"], name="request_log_classif_8a1320_idx"),
        ),
        migrations.AddIndex(
            model_name="httplog",
            index=models.Index(fields=["ticketer", "-created_on"], name="request_log_tickete_abc69b_idx"),
        ),
    ]
