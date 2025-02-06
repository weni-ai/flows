from django.db import migrations

SQL = "ALTER SEQUENCE campaigns_eventfire_id_seq CYCLE;"


class Migration(migrations.Migration):
    dependencies = [
        ("campaigns", "0040_auto_20210714_2159"),
    ]

    operations = [migrations.RunSQL(SQL)]
