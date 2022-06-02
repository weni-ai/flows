# Generated by Django 2.2.20 on 2021-04-23 18:45

from django.db import migrations
from django.db.models import F, Value
from django.db.models.functions import Replace

ESCAPED_NULL = "\\u0000"


def fix_flow_def_nulls(apps, schema_editor):  # pragma: no cover
    FlowRevision = apps.get_model("flows", "FlowRevision")
    revs = FlowRevision.objects.filter(definition__contains=ESCAPED_NULL)
    num_fixed = revs.update(definition=Replace(F("definition"), Value(ESCAPED_NULL), Value("")))
    if num_fixed:
        print(f"Fixed {num_fixed} flow revisions with NULL characters")


def reverse(apps, schema_editor):  # pragma: no cover
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("flows", "0248_auto_20210316_1617"),
    ]

    operations = [migrations.RunPython(fix_flow_def_nulls, reverse)]