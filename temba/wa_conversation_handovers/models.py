from django.db import models
from django.db.models import Q
from django.utils import timezone

from temba.channels.models import Channel
from temba.orgs.models import Org
from temba.utils.models import JSONField


class WAConversationHandover(models.Model):
    CONTEXT_TYPE_HISTORY = "history"
    CONTEXT_TYPE_SUMMARY = "summary"
    CONTEXT_TYPE_CHOICES = (
        (CONTEXT_TYPE_HISTORY, "History"),
        (CONTEXT_TYPE_SUMMARY, "Summary"),
    )

    org = models.ForeignKey(Org, related_name="wa_conversation_handovers", on_delete=models.PROTECT)
    channel = models.ForeignKey(Channel, related_name="wa_conversation_handovers", on_delete=models.PROTECT)
    contact = models.ForeignKey("contacts.Contact", related_name="wa_conversation_handovers", on_delete=models.PROTECT)
    contact_urn = models.CharField(max_length=255)

    context_type = models.CharField(max_length=16, choices=CONTEXT_TYPE_CHOICES)
    context_text = models.TextField()
    context_payload = JSONField(null=True)

    previous_owner_app_id = models.CharField(max_length=64, null=True, blank=True)
    previous_owner_app_role = models.CharField(max_length=64, null=True, blank=True)
    previous_owner_business_id = models.CharField(max_length=64, null=True, blank=True)
    handover_metadata = models.CharField(max_length=255, null=True, blank=True)

    occurred_on = models.DateTimeField()
    created_on = models.DateTimeField(default=timezone.now)
    consumed_on = models.DateTimeField(null=True, blank=True)
    consumed_msg_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "wa_conversation_handover"
        constraints = [
            models.CheckConstraint(
                check=Q(context_type__in=["history", "summary"]),
                name="chk_wa_conv_handover_context_type",
            ),
            models.UniqueConstraint(
                fields=["channel", "contact"],
                condition=Q(consumed_on=None),
                name="uq_wa_conv_handover_pending",
            ),
        ]
        indexes = [
            models.Index(fields=["channel", "contact", "consumed_on"], name="idx_wa_conv_handover_pending"),
            models.Index(fields=["org", "contact_urn", "consumed_on"], name="idx_wa_conv_handover_urn"),
            models.Index(fields=["channel", "contact", "-occurred_on"], name="idx_wa_conv_handover_history"),
        ]
