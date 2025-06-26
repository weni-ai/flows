from django.db import models


class CTWA(models.Model):
    """
    Table to store Click to WhatsApp data for lookup
    """

    ctwa_clid = models.CharField(max_length=255, db_index=True, help_text="Click to WhatsApp Click ID")
    channel_uuid = models.UUIDField(db_index=True, help_text="Channel UUID")
    waba = models.CharField(max_length=255, help_text="WhatsApp Business Account ID")
    contact_urn = models.CharField(max_length=255, help_text="Contact URN")
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"CTWA Data - CLID: {self.ctwa_clid}, Channel: {self.channel_uuid}"
