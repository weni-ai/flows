# Generated by Django 2.2.20 on 2021-07-15 18:25

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("channels", "0126_auto_20210105_1444"),
    ]

    operations = [
        migrations.AlterField(
            model_name="channelcount",
            name="channel",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="counts", to="channels.Channel"
            ),
        ),
        migrations.AlterField(
            model_name="channelcount",
            name="count",
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="channelcount",
            name="count_type",
            field=models.CharField(
                choices=[
                    ("IM", "Incoming Message"),
                    ("OM", "Outgoing Message"),
                    ("IV", "Incoming Voice"),
                    ("OV", "Outgoing Voice"),
                    ("LS", "Success Log Record"),
                    ("LE", "Error Log Record"),
                ],
                max_length=2,
            ),
        ),
        migrations.AlterField(
            model_name="channelcount",
            name="day",
            field=models.DateField(null=True),
        ),
        migrations.AlterField(
            model_name="channelcount",
            name="id",
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False),
        ),
        migrations.AlterField(
            model_name="channelcount",
            name="is_squashed",
            field=models.BooleanField(default=False),
        ),
    ]
