import uuid

from django_countries.fields import CountryField

from django.db import models
from django.utils import timezone

from temba.channels.models import Channel
from temba.orgs.models import Org


class Template(models.Model):
    """
    Templates represent messages that can be used in flows and have template variables substituted into them. These
    are currently only used for WhatsApp channels.
    """

    CATEGORY_CHOICES = (
        ("ACCOUNT_UPDATE", "account_update"),
        ("PAYMENT_UPDATE", "payment_update"),
        (
            "PERSONAL_FINANCE_UPDATE",
            "personal_finance_update",
        ),
        ("SHIPPING_UPDATE", "shipping_update"),
        ("RESERVATION_UPDATE", "reservation_update"),
        ("ISSUE_RESOLUTION", "issue_resolution"),
        ("APPOINTMENT_UPDATE", "appointment_update"),
        (
            "TRANSPORTATION_UPDATE",
            "transportation_update",
        ),
        ("TICKET_UPDATE", "ticket_update"),
        ("ALERT_UPDATE", "alert_update"),
        ("AUTO_REPLY", "auto_reply"),
        ("TRANSACTIONAL", "transactional"),
        ("MARKETING", "marketing"),
        ("OTP", "otp"),
        ("UTILITY", "utility"),
        ("AUTHENTICATION", "authentication"),
    )

    # the uuid for this template
    uuid = models.UUIDField(default=uuid.uuid4)

    # the name of this template
    name = models.CharField(max_length=512)

    # the organization this template is used in
    org = models.ForeignKey(Org, on_delete=models.PROTECT, related_name="templates")

    # when this template was last modified
    modified_on = models.DateTimeField(default=timezone.now)

    category = models.CharField(max_length=200, choices=CATEGORY_CHOICES, null=True)

    # when this template was created
    created_on = models.DateTimeField(default=timezone.now)

    @classmethod
    def trim(cls, channel):
        org = channel.org
        templates = org.templates.filter(translations=None)
        templates.delete()

    def is_approved(self):
        """
        Returns whether this template has at least one translation and all are approved
        """
        translations = self.translations.all()
        if len(translations) == 0:
            return False

        for tr in translations:
            if tr.status != TemplateTranslation.STATUS_APPROVED:
                return False

        return True

    class Meta:
        unique_together = ("org", "name")


class TemplateTranslation(models.Model):
    """
    TemplateTranslation represents a translation for a template and channel pair.
    """

    STATUS_APPROVED = "A"
    STATUS_PENDING = "P"
    STATUS_REJECTED = "R"
    STATUS_UNSUPPORTED_LANGUAGE = "U"

    STATUS_CHOICES = (
        (STATUS_APPROVED, "approved"),
        (STATUS_PENDING, "pending"),
        (STATUS_REJECTED, "rejected"),
        (STATUS_UNSUPPORTED_LANGUAGE, "unsupported_language"),
    )

    # the template this maps to
    template = models.ForeignKey(Template, on_delete=models.PROTECT, related_name="translations")

    # the channel that synced this template
    channel = models.ForeignKey(Channel, on_delete=models.PROTECT, related_name="template_translations")

    # the content of this template
    content = models.TextField(null=False)

    # how many variables this template contains
    variable_count = models.IntegerField()

    # the current status of this channel template
    status = models.CharField(max_length=1, choices=STATUS_CHOICES, default=STATUS_PENDING, null=False)

    # the language for this template (ISO639-3 or Facebook code)
    language = models.CharField(max_length=6)

    # the country code for this template
    country = CountryField(null=True, blank=True)

    # the namespace for this template
    namespace = models.CharField(max_length=36, default="")

    # the external id for this channel template
    external_id = models.CharField(null=True, max_length=64)

    # whether this channel template is active
    is_active = models.BooleanField(default=True)

    @classmethod
    def trim(cls, channel, existing):
        """
        Trims what channel templates exist for this channel based on the set of templates passed in
        """
        ids = [tc.id for tc in existing]

        TemplateTranslation.objects.filter(channel=channel).exclude(id__in=ids).delete()

    @classmethod
    def get_or_create(
        cls, channel, name, language, country, content, variable_count, status, external_id, namespace, category
    ):
        existing = TemplateTranslation.objects.filter(channel=channel, external_id=external_id).first()

        if not existing:
            template = Template.objects.filter(org=channel.org, name=name).first()
            if not template:
                template = Template.objects.create(
                    org=channel.org,
                    name=name,
                    created_on=timezone.now(),
                    modified_on=timezone.now(),
                    category=category,
                )
            else:
                template.modified_on = timezone.now()
                template.category = category
                template.save(update_fields=["modified_on", "category"])

            existing = TemplateTranslation.objects.create(
                template=template,
                channel=channel,
                content=content,
                variable_count=variable_count,
                status=status,
                language=language,
                country=country,
                external_id=external_id,
                namespace=namespace,
            )

        else:
            if (
                existing.status != status
                or existing.content != content
                or existing.country != country
                or existing.language != language
            ):
                existing.status = status
                existing.content = content
                existing.variable_count = variable_count
                existing.is_active = True
                existing.language = language
                existing.country = country
                existing.namespace = namespace
                existing.save(
                    update_fields=[
                        "status",
                        "language",
                        "content",
                        "country",
                        "is_active",
                        "variable_count",
                        "namespace",
                    ]
                )

                existing.template.modified_on = timezone.now()
                existing.template.save(update_fields=["modified_on"])

        return existing

    def __str__(self):
        return f"{self.template.name} ({self.language} [{self.country}]) {self.status}: {self.content}"


class TemplateButton(models.Model):
    BUTTON_TYPE_CHOICES = (
        ("QUICK_REPLY", "quick_reply"),
        ("PHONE_NUMBER", "phone_number"),
        ("URL", "url"),
    )

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    translation = models.ForeignKey(TemplateTranslation, on_delete=models.CASCADE, related_name="buttons")

    type = models.CharField(max_length=20, choices=BUTTON_TYPE_CHOICES)
    text = models.CharField(max_length=30, null=True)
    country_code = models.IntegerField(null=True)
    phone_number = models.CharField(max_length=20, null=True)
    url = models.CharField(max_length=2000, null=True)


class TemplateHeader(models.Model):
    HEADER_TYPE_CHOICES = (
        ("TEXT", "text"),
        ("IMAGE", "image"),
        ("DOCUMENT", "document"),
        ("VIDEO", "video"),
    )

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    translation = models.ForeignKey(TemplateTranslation, on_delete=models.CASCADE, related_name="headers")
    type = models.CharField(max_length=20, choices=HEADER_TYPE_CHOICES)
    text = models.CharField(max_length=60, default=None, null=True)
