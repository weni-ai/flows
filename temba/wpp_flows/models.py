from uuid import uuid4

from django.db import models
from django.utils import timezone

from temba.channels.models import Channel
from temba.orgs.models import Org


class WhatsappFlows(models.Model):
    STATUS_CHOICES = (
        ("DRAFT", "drafted"),
        ("PUBLISHED", "published"),
        ("DEPRECATED", "deprecated"),
        ("BLOCKED", "blocked"),
        ("THROTTLED", "throttled"),
    )

    uuid = models.UUIDField(default=uuid4)
    facebook_flow_id = models.CharField(max_length=50)
    category = models.JSONField()
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, null=False)
    name = models.CharField(max_length=100)
    validation_errors = models.JSONField()
    org = models.ForeignKey(Org, on_delete=models.PROTECT, related_name="wpp_flows")
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="wpp_flows")
    created_on = models.DateTimeField(default=timezone.now)
    modified_on = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} - {self.facebook_flow_id}"

    @classmethod
    def trim(self, channel, ids):
        WhatsappFlows.objects.filter(channel=channel).exclude(facebook_flow_id__in=ids).update(is_active=False)
