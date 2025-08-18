# Generated manually

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("channels", "0137_alter_channel_name"),
    ]

    operations = [
        migrations.RunSQL(
            """
            ALTER TABLE channels_channellog
            ALTER COLUMN msg_id TYPE bigint
            USING msg_id::bigint;
            """,
            """
            ALTER TABLE channels_channellog
            ALTER COLUMN msg_id TYPE integer
            USING msg_id::integer;
            """,
        ),
    ]
