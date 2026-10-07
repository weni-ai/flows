from django.db import migrations, models


def empty_null_strings(apps, schema_editor):
    ContactIdentityEvent = apps.get_model("contacts", "ContactIdentityEvent")
    ContactIdentityEvent.objects.filter(anchor_type__isnull=True).update(anchor_type="")
    ContactIdentityEvent.objects.filter(attachment_status__isnull=True).update(attachment_status="")


class Migration(migrations.Migration):

    dependencies = [
        ("contacts", "0145_consumer_identity"),
    ]

    operations = [
        migrations.RunPython(empty_null_strings, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="contactidentityevent",
            name="anchor_type",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AlterField(
            model_name="contactidentityevent",
            name="attachment_status",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
    ]
