# Generated by Django 2.2.20 on 2021-07-15 18:54

from django.db import migrations, models

SQL = """DROP INDEX msgs_msg_org_created_id_where_outbound_visible_sent"""


class Migration(migrations.Migration):
    dependencies = [
        ("msgs", "0154_auto_20210715_1825"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="msg",
            index=models.Index(
                condition=models.Q(("direction", "O"), ("status__in", ("W", "S", "D")), ("visibility", "V")),
                fields=["org", "-sent_on", "-id"],
                name="msgs_outgoing_visible_sent",
            ),
        ),
        migrations.RunSQL(SQL),
    ]
