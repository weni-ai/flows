# Generated by Django 3.2.8 on 2021-11-15 20:48

from django.db import migrations

SQL = "DROP INDEX msgs_msg_uuid_not_null"


class Migration(migrations.Migration):
    dependencies = [
        ("msgs", "0158_scheduled_bcast_cleanup"),
    ]

    operations = [migrations.RunSQL(SQL)]
