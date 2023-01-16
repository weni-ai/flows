# Generated by Django 4.0.4 on 2022-05-10 14:28

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0031_team_ticketdailycount_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="is_system",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="ticketer",
            name="is_system",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="topic",
            name="is_system",
            field=models.BooleanField(default=False),
        ),
    ]