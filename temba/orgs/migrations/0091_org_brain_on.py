# Generated by Django 3.2.23 on 2024-03-26 13:30

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orgs", "0090_auto_20211209_2120"),
    ]

    operations = [
        migrations.AddField(
            model_name="org",
            name="brain_on",
            field=models.BooleanField(default=False, help_text="Whether this organization use router"),
        ),
    ]
