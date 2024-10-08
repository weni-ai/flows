from uuid import uuid4

from django.db import models
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _

from temba.channels.models import Channel
from temba.orgs.models import Org


class WhatsappFlow(models.Model):
    STATUS_CHOICES = (
        ("DRAFT", _("drafted")),
        ("PUBLISHED", _("published")),
        ("DEPRECATED", _("deprecated")),
        ("BLOCKED", _("blocked")),
        ("THROTTLED", _("throttled")),
    )

    uuid = models.UUIDField(default=uuid4)
    facebook_flow_id = models.CharField(max_length=50)
    category = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, null=False)
    name = models.CharField(max_length=100)
    validation_errors = models.JSONField()
    org = models.ForeignKey(Org, on_delete=models.PROTECT, related_name="wpp_flows")
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="wpp_flows")
    created_on = models.DateTimeField(default=timezone.now)
    modified_on = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(default=True)
    screens = models.JSONField()
    variables = models.JSONField(default=list, blank=True)

    @classmethod
    def is_status_valid(cls, status) -> bool:
        for choice in WhatsappFlow.STATUS_CHOICES:
            if status == choice[0]:
                return True

        return False

    @classmethod
    def update_status(cls, flow_id: str, new_status: str, old_status: str) -> list:
        whatsapp_flows = cls.objects.filter(facebook_flow_id=flow_id)
        for flow in whatsapp_flows:
            flow.status = new_status

            if old_status == "DEPRECATED":
                flow.is_active = True

            if new_status == "DEPRECATED":
                flow.is_active = False

            flow.save()

        return whatsapp_flows

    @classmethod
    def trim(cls, channel, ids):
        WhatsappFlow.objects.filter(channel=channel).exclude(facebook_flow_id__in=ids).update(is_active=False)

    def __str__(self):
        return f"{self.name}"
