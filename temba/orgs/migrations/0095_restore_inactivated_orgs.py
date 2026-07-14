from django.db import migrations


def restore_inactivated_orgs(apps, schema_editor):
    """
    Orgs marked inactive via project status were incorrectly stored as is_active=False.
    Restore them as active and suspended instead.
    """
    org = apps.get_model("orgs", "Org")
    org.objects.filter(is_active=False, released_on__isnull=True).update(
        is_active=True,
        is_suspended=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("orgs", "0094_unique_contact_count"),
    ]

    operations = [
        migrations.RunPython(restore_inactivated_orgs, migrations.RunPython.noop),
    ]
