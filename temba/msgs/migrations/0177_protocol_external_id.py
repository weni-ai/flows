from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("msgs", "0176_protocol"),
    ]

    operations = [
        migrations.AddField(
            model_name="protocol",
            name="external_id",
            field=models.CharField(max_length=255, null=True),
        ),
        migrations.AddConstraint(
            model_name="protocol",
            constraint=models.UniqueConstraint(
                fields=("org", "urn", "external_id"),
                name="unique_protocol_external_id",
            ),
        ),
    ]
