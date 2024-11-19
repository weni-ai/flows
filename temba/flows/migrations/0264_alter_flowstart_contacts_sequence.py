from django.db import migrations

SQL = "ALTER SEQUENCE flows_flowstart_contacts_id_seq CYCLE;"


class Migration(migrations.Migration):
    dependencies = [
        ("flows", "0263_flow_is_mutable"),
    ]

    operations = [migrations.RunSQL(SQL)]
