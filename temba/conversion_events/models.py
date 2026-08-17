from django.db import models

from temba.orgs.models import Org


class CtwaReferralSource(models.Model):
    """
    Campaign/source data from the Meta referral object on CTWA click events.
    """

    SOURCE_TYPE_AD = "ad"
    SOURCE_TYPE_POST = "post"
    SOURCE_TYPE_CHOICES = (
        (SOURCE_TYPE_AD, "Ad"),
        (SOURCE_TYPE_POST, "Post"),
    )

    org = models.ForeignKey(
        Org, on_delete=models.PROTECT, related_name="ctwa_referral_sources"
    )
    source_id = models.CharField(max_length=64)
    source_type = models.CharField(max_length=16, choices=SOURCE_TYPE_CHOICES)
    source_url = models.TextField(null=True, blank=True)
    headline = models.TextField(null=True, blank=True)
    body = models.TextField(null=True, blank=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ctwa_referral_sources"
        constraints = [
            models.UniqueConstraint(
                fields=["org", "source_id", "source_type"],
                name="uq_ctwa_referral_source",
            ),
            models.CheckConstraint(
                check=models.Q(source_type__in=["ad", "post"]),
                name="chk_ctwa_referral_source_type",
            ),
        ]
        indexes = [
            models.Index(fields=["source_id"], name="idx_ctwa_ref_src_source_id"),
            models.Index(fields=["-last_seen_at"], name="idx_ctwa_ref_src_last_seen"),
            models.Index(
                fields=["org", "-last_seen_at"], name="idx_ctwa_ref_src_org_last_seen"
            ),
        ]

    def __str__(self):
        return f"CTWA Referral Source - {self.source_type}:{self.source_id}"

    @classmethod
    def get_or_create_for_org(cls, org, source_id, source_type, **defaults):
        if org is None:
            raise ValueError("org is required to create a CtwaReferralSource")
        return cls.objects.get_or_create(
            org=org,
            source_id=source_id,
            source_type=source_type,
            defaults=defaults,
        )


class CTWA(models.Model):
    """
    Click/conversation event with operational context for CTWA conversion lookup.
    """

    ctwa_clid = models.CharField(
        max_length=512,
        null=True,
        blank=True,
        unique=True,
        help_text="Click to WhatsApp Click ID",
    )
    contact_urn = models.CharField(max_length=255, help_text="Contact URN")
    timestamp = models.DateTimeField(help_text="Event timestamp from the webhook")
    channel_uuid = models.UUIDField(help_text="Channel UUID")
    waba = models.CharField(max_length=255, help_text="WhatsApp Business Account ID")
    phone_number_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text="Phone number ID from webhook metadata",
    )
    referral_source = models.ForeignKey(
        CtwaReferralSource,
        on_delete=models.PROTECT,
        related_name="conversion_events",
        db_column="referral_source_id",
    )
    message_id = models.CharField(
        max_length=255, null=True, blank=True, help_text="WhatsApp message ID (wamid)"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["channel_uuid", "contact_urn", "-timestamp"],
                name="idx_conv_ev_ctwa_lookup",
            ),
            models.Index(fields=["referral_source"], name="idx_conv_ev_ctwa_ref"),
            models.Index(fields=["waba", "-timestamp"], name="idx_conv_ev_ctwa_waba"),
        ]

    def __str__(self):
        clid = self.ctwa_clid or "no-clid"
        return f"CTWA Data - CLID: {clid}, Channel: {self.channel_uuid}"
