# Generated manually: require CtwaReferralSource.org after backfill

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("conversion_events", "0004_backfill_ctwareferralsource_org"),
        ("orgs", "0094_unique_contact_count"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ctwareferralsource",
            name="org",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="ctwa_referral_sources",
                to="orgs.org",
            ),
        ),
    ]
