from django.db import migrations
from django.utils import timezone

from temba.msgs.models import Msg


def batch_queryset(queryset, batch_size=1000):  # pragma: no cover
    total = queryset.count()

    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        yield (start, end, total, queryset[start:end])


queryset = Msg.objects.exclude(metadata=None, direction="I", template__isnull=False)


def populate_template(apps, schema_editor):  # pragma: no cover
    for start, end, total, batch in batch_queryset(queryset, batch_size=500):
        print(f"Batch of {start} to {end} in a total of {total} elements:")

        msgs_to_update = []
        for msg in batch:
            template_name = msg.metadata.get("templating", {}).get("template", {}).get("name")
            if template_name:
                msg.template = template_name
                msg.modified_on = timezone.now()
                msgs_to_update.append(msg)
        if msgs_to_update:
            Msg.objects.bulk_update(msgs_to_update, ["template", "modified_on"])


def reverse(apps, schema_editor):  # pragma: no cover
    from django.apps import apps

    populate_template(apps, schema_editor)


def apply_manual():  # pragma: no cover
    populate_template()


class Migration(migrations.Migration):
    dependencies = [("msgs", "0164_msg_template")]

    operations = [migrations.RunPython(populate_template, reverse)]
