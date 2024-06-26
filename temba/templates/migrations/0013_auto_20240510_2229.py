# Generated by Django 3.2.22 on 2024-05-10 22:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("templates", "0012_auto_20231227_2152"),
    ]

    operations = [
        migrations.AddField(
            model_name="template",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name="templatetranslation",
            name="status",
            field=models.CharField(
                choices=[
                    ("A", "approved"),
                    ("I", "in_appeal"),
                    ("P", "pending"),
                    ("E", "pending_deletion"),
                    ("D", "deleted"),
                    ("S", "disabled"),
                    ("L", "locked"),
                    ("R", "rejected"),
                    ("U", "unsupported_language"),
                ],
                default="P",
                max_length=1,
            ),
        ),
    ]
