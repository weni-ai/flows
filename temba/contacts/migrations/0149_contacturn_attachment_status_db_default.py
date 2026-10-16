from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("contacts", "0148_identity_event_blank_strings"),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE contacts_contacturn ALTER COLUMN attachment_status SET DEFAULT 'not-attached';",
            reverse_sql="ALTER TABLE contacts_contacturn ALTER COLUMN attachment_status DROP DEFAULT;",
        ),
    ]
