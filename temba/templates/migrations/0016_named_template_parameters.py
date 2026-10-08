from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("templates", "0015_auto_20250821_1729"),
    ]

    operations = [
        migrations.AddField(
            model_name="template",
            name="parameter_format",
            field=models.CharField(default="positional", max_length=16),
        ),
        migrations.AddField(
            model_name="template",
            name="parameter_policies",
            field=models.JSONField(blank=True, default=dict, null=True),
        ),
        migrations.AddField(
            model_name="templatetranslation",
            name="parameter_names",
            field=models.JSONField(blank=True, default=list, null=True),
        ),
    ]
