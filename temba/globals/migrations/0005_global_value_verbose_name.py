from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("globals", "0004_auto_20201118_1723"),
    ]

    operations = [
        migrations.AlterField(
            model_name="global",
            name="value",
            field=models.TextField(max_length=10000, verbose_name="Value"),
        ),
    ]
