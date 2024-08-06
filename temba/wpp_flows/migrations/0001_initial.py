# Generated by Django 3.2.22 on 2024-06-28 22:33

import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("channels", "0135_alter_channellog_created_on"),
        ("orgs", "0092_org_proj_uuid"),
    ]

    operations = [
        migrations.CreateModel(
            name="WhatsappFlow",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("uuid", models.UUIDField(default=uuid.uuid4)),
                ("facebook_flow_id", models.CharField(max_length=50)),
                ("category", models.JSONField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("DRAFT", "drafted"),
                            ("PUBLISHED", "published"),
                            ("DEPRECATED", "deprecated"),
                            ("BLOCKED", "blocked"),
                            ("THROTTLED", "throttled"),
                        ],
                        max_length=30,
                    ),
                ),
                ("name", models.CharField(max_length=100)),
                ("validation_errors", models.JSONField()),
                ("created_on", models.DateTimeField(default=django.utils.timezone.now)),
                ("modified_on", models.DateTimeField(default=django.utils.timezone.now)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "channel",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="wpp_flows", to="channels.channel"
                    ),
                ),
                (
                    "org",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, related_name="wpp_flows", to="orgs.org"
                    ),
                ),
            ],
        ),
    ]