from django.db import migrations

SQL = """CREATE INDEX IF NOT exists channels_channel_address_index
            ON public.channels_channel USING btree (address varchar_ops NULLS LAST);
        """


class Migration(migrations.Migration):
    dependencies = [
        ("channels", "0135_alter_channellog_created_on"),
    ]

    operations = [migrations.RunSQL(SQL)]
