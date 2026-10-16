from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("msgs", "0178_protocol_blank_strings"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE msgs_protocol ALTER COLUMN close_reason SET DEFAULT '';
                ALTER TABLE msgs_protocol ALTER COLUMN timer_kind SET DEFAULT '';
            """,
            reverse_sql="""
                ALTER TABLE msgs_protocol ALTER COLUMN close_reason DROP DEFAULT;
                ALTER TABLE msgs_protocol ALTER COLUMN timer_kind DROP DEFAULT;
            """,
        ),
    ]
