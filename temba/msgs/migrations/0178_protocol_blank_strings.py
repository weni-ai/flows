from django.db import migrations, models


def empty_null_strings(apps, schema_editor):
    Protocol = apps.get_model("msgs", "Protocol")
    Protocol.objects.filter(close_reason__isnull=True).update(close_reason="")
    Protocol.objects.filter(timer_kind__isnull=True).update(timer_kind="")


class Migration(migrations.Migration):

    dependencies = [
        ("msgs", "0177_protocol_external_id"),
    ]

    operations = [
        migrations.RunPython(empty_null_strings, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="protocol",
            name="close_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("ai_csat", "AI CSAT"),
                    ("ai_inactivity", "AI inactivity"),
                    ("human_inactivity", "Human inactivity"),
                    ("attendant", "Attendant"),
                    ("ticket_closed", "Ticket closed"),
                ],
                default="",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="protocol",
            name="timer_kind",
            field=models.CharField(blank=True, choices=[("ai", "AI"), ("human", "Human")], default="", max_length=8),
        ),
    ]
