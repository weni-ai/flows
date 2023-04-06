# Generated by Django 3.2.18 on 2023-03-01 19:55

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("msgs", "0162_alter_msg_failed_reason"),
    ]

    operations = [
        migrations.AlterField(
            model_name="msg",
            name="status",
            field=models.CharField(
                choices=[
                    ("I", "Initializing"),
                    ("P", "Pending"),
                    ("Q", "Queued"),
                    ("W", "Wired"),
                    ("S", "Sent"),
                    ("D", "Delivered"),
                    ("H", "Handled"),
                    ("E", "Error"),
                    ("F", "Failed"),
                    ("R", "Resent"),
                    ("V", "Read"),
                ],
                db_index=True,
                default="P",
                max_length=1,
            ),
        ),
    ]
