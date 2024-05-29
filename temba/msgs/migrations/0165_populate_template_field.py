from django.db import migrations
from django.utils import timezone


def populate_template(apps, schema_editor):  # pragma: no cover
    Msg = apps.get_model("msgs", "Msg")

    num_updated = 0
    for msg in Msg.objects.exclude(metadata=None, direction="I"):
        template_name = msg.metadata.get("templating", {}).get("template", {}).get("name")
        if template_name:
            msg.template = template_name
            msg.modified_on = timezone.now()
            msg.save(update_fields=("template", "modified_on"))
            num_updated += 1

    if num_updated:
        print(f"Updated template name for {num_updated} msgs")


def reverse(apps, schema_editor):  # pragma: no cover
    pass


def apply_manual():  # pragma: no cover
    from django.apps import apps

    populate_template(apps, None)


class Migration(migrations.Migration):
    dependencies = [("msgs", "0164_msg_template")]

    operations = [migrations.RunPython(populate_template, reverse)]
