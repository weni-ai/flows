# Generated by Django 3.2.17 on 2023-22-11 16:27

from django.db import migrations

SQL = "ALTER SEQUENCE request_logs_httplog_id_seq CYCLE;"


class Migration(migrations.Migration):
    dependencies = [
        ("request_logs", "0015_alter_httplog_log_type"),
    ]

    operations = [migrations.RunSQL(SQL)]
