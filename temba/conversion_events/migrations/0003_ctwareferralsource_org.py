# Generated manually: add nullable org to CtwaReferralSource (schema only)

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("conversion_events", "0002_ctwa_referral_sources"),
        ("orgs", "0094_unique_contact_count"),
    ]

    operations = [
        migrations.AddField(
            model_name="ctwareferralsource",
            name="org",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="ctwa_referral_sources",
                to="orgs.org",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="ctwareferralsource",
            name="uq_ctwa_referral_source",
        ),
        migrations.AddConstraint(
            model_name="ctwareferralsource",
            constraint=models.UniqueConstraint(
                fields=("org", "source_id", "source_type"),
                name="uq_ctwa_referral_source",
            ),
        ),
        migrations.AddIndex(
            model_name="ctwareferralsource",
            index=models.Index(fields=["org", "-last_seen_at"], name="idx_ctwa_ref_src_org_last_seen"),
        ),
    ]
