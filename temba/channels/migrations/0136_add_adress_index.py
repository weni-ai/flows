from django.db import migrations

SQL = """CREATE INDEX IF NOT EXISTS channels_channel_address_index
            ON public.channels_channel USING btree
            (address COLLATE pg_catalog."default" varchar_ops ASC NULLS LAST)
            WITH (deduplicate_items=False)
            TABLESPACE pg_default;"""


class Migration(migrations.Migration):
    dependencies = [
        ("channels", "0135_alter_channellog_created_on"),
    ]

    operations = [migrations.RunSQL(SQL)]
