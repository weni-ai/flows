import logging

from django.shortcuts import get_object_or_404

from temba.wpp_flows.models import WhatsappFlow

logger = logging.getLogger(__name__)


def update_whatsapp_flows_status(webhook):
    entry = webhook.get("entry", [])[0]
    flow_id = entry.get("id")
    new_status = entry["changes"][0]["value"]["new_status"]

    if new_status not in WhatsappFlow.STATUS_CHOICES:
        logger.error(f"Status {new_status} not find in flows", exc_info=True)
        return False

    flow = get_object_or_404(WhatsappFlow, facebook_flow_id=flow_id)
    flow.status = new_status
    flow.save()

    print(f"Flow ID {flow_id} atualizado para {new_status} com sucesso.")
