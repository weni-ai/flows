# Generated by Django 3.2.6 on 2021-09-03 21:01

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


def delete_all_notifications(apps, schema_editor):  # pragma: no cover
    apps.get_model("notifications", "Notification").objects.all().delete()
    apps.get_model("notifications", "Log").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("flows", "0259_auto_20210825_1438"),
        ("contacts", "0142_auto_20210803_2000"),
        ("channels", "0134_alter_channel_name"),
        ("msgs", "0156_auto_20210722_1429"),
        ("notifications", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(delete_all_notifications),
        migrations.RemoveIndex(
            model_name="log",
            name="notificatio_org_id_d0ef64_idx",
        ),
        migrations.RemoveIndex(
            model_name="notification",
            name="notificatio_org_id_7a0120_idx",
        ),
        migrations.RemoveField(
            model_name="notification",
            name="log",
        ),
        migrations.AddField(
            model_name="notification",
            name="channel",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="notifications",
                to="channels.channel",
            ),
        ),
        migrations.AddField(
            model_name="notification",
            name="contact_export",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="notifications",
                to="contacts.exportcontactstask",
            ),
        ),
        migrations.AddField(
            model_name="notification",
            name="contact_import",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="notifications",
                to="contacts.contactimport",
            ),
        ),
        migrations.AddField(
            model_name="notification",
            name="created_on",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name="notification",
            name="message_export",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="notifications",
                to="msgs.exportmessagestask",
            ),
        ),
        migrations.AddField(
            model_name="notification",
            name="notification_type",
            field=models.CharField(max_length=16, null=True),
        ),
        migrations.AddField(
            model_name="notification",
            name="results_export",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="notifications",
                to="flows.exportflowresultstask",
            ),
        ),
        migrations.AddField(
            model_name="notification",
            name="scope",
            field=models.CharField(default=0, max_length=36),
            preserve_default=False,
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["org", "user", "-created_on"], name="notificatio_org_id_17c9ee_idx"),
        ),
        migrations.AddConstraint(
            model_name="notification",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_seen", False)),
                fields=("org", "notification_type", "scope", "user"),
                name="notifications_unseen_of_type",
            ),
        ),
    ]
