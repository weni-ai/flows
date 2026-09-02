import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

import temba.utils.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("channels", "0137_alter_channel_name"),
        ("contacts", "0143_auto_20210908_2224"),
        ("orgs", "0094_unique_contact_count"),
    ]

    operations = [
        migrations.CreateModel(
            name="WAConversationHandover",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("contact_urn", models.CharField(max_length=255)),
                (
                    "context_type",
                    models.CharField(choices=[("history", "History"), ("summary", "Summary")], max_length=16),
                ),
                ("context_text", models.TextField()),
                ("context_payload", temba.utils.models.JSONField(null=True)),
                ("previous_owner_app_id", models.CharField(blank=True, max_length=64, null=True)),
                ("previous_owner_app_role", models.CharField(blank=True, max_length=64, null=True)),
                ("previous_owner_business_id", models.CharField(blank=True, max_length=64, null=True)),
                ("handover_metadata", models.CharField(blank=True, max_length=255, null=True)),
                ("occurred_on", models.DateTimeField()),
                ("created_on", models.DateTimeField(default=django.utils.timezone.now)),
                ("consumed_on", models.DateTimeField(blank=True, null=True)),
                ("consumed_msg_id", models.BigIntegerField(blank=True, null=True)),
                (
                    "channel",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="wa_conversation_handovers",
                        to="channels.channel",
                    ),
                ),
                (
                    "contact",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="wa_conversation_handovers",
                        to="contacts.contact",
                    ),
                ),
                (
                    "org",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="wa_conversation_handovers",
                        to="orgs.org",
                    ),
                ),
            ],
            options={
                "db_table": "wa_conversation_handover",
            },
        ),
        migrations.AddConstraint(
            model_name="waconversationhandover",
            constraint=models.CheckConstraint(
                check=models.Q(("context_type__in", ["history", "summary"])),
                name="chk_wa_conv_handover_context_type",
            ),
        ),
        migrations.AddConstraint(
            model_name="waconversationhandover",
            constraint=models.UniqueConstraint(
                condition=models.Q(("consumed_on", None)),
                fields=("channel", "contact"),
                name="uq_wa_conv_handover_pending",
            ),
        ),
        migrations.AddIndex(
            model_name="waconversationhandover",
            index=models.Index(fields=["channel", "contact", "consumed_on"], name="idx_wa_conv_handover_pending"),
        ),
        migrations.AddIndex(
            model_name="waconversationhandover",
            index=models.Index(fields=["org", "contact_urn", "consumed_on"], name="idx_wa_conv_handover_urn"),
        ),
        migrations.AddIndex(
            model_name="waconversationhandover",
            index=models.Index(fields=["channel", "contact", "-occurred_on"], name="idx_wa_conv_handover_history"),
        ),
    ]
