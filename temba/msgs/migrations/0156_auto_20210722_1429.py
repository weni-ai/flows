# Generated by Django 2.2.20 on 2021-07-22 14:29

from django.db import migrations, models
from django.db.models import F


def update_null_sent_on(apps, schema_editor):  # pragma: no cover
    Msg = apps.get_model("msgs", "Msg")
    Msg.objects.filter(status__in=("W", "S", "D"), sent_on=None).update(sent_on=F("created_on"))


class Migration(migrations.Migration):
    dependencies = [
        ("msgs", "0155_auto_20210715_1854"),
    ]

    operations = [
        migrations.RunPython(update_null_sent_on),
        migrations.AddConstraint(
            model_name="msg",
            constraint=models.CheckConstraint(
                check=models.Q(("sent_on__isnull", True), ("status__in", ("W", "S", "D")), _negated=True),
                name="no_sent_status_without_sent_on",
            ),
        ),
    ]
