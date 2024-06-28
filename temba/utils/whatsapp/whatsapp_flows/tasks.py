import requests
from django_redis import get_redis_connection

from django.conf import settings
from django.utils import timezone

from celery import shared_task

from temba.channels.models import Channel
from temba.request_logs.models import HTTPLog
from temba.wpp_flows.models import WhatsappFlows


@shared_task(track_started=True, name="refresh_whatsapp_flows")
def refresh_whatsapp_flows():
    """
    Runs across all WhatsApp flows that have connected FB accounts and syncs the flows which are active.
    """

    r = get_redis_connection()
    if r.get("refresh_whatsapp_flows"):  # pragma: no cover
        return

    with r.lock("refresh_whatsapp_flows", 1800):
        # for every whatsapp channel
        for channel in Channel.objects.filter(is_active=True, channel_type__in=["WA", "WAC"]):
            # update the version only when have it set in the config
            if channel.config.get("wa_waba_id"):
                flows = get_whatsapp_flows(channel)

                if flows:
                    update_whatsapp_flows(flows, channel)


def get_whatsapp_flows(channel):
    token = _get_token(channel)
    waba_id = channel.config.get("wa_waba_id")

    start = timezone.now()
    try:
        whatsapp_flows_data = []
        url = f"{settings.WHATSAPP_API_URL}/{waba_id}/flows"

        headers = {"Authorization": f"Bearer {token}"}
        while url:
            resp = requests.get(url, params=dict(limit=255), headers=headers)
            elapsed = (timezone.now() - start).total_seconds() * 1000
            HTTPLog.create_from_response(
                HTTPLog.WHATSAPP_FLOWS_SYNCED, url, resp, channel=channel, request_time=elapsed
            )
            if resp.status_code != 200:  # pragma: no cover
                return []

            whatsapp_flows_data.extend(resp.json()["data"])
            url = resp.json().get("paging", {}).get("next", None)
        return whatsapp_flows_data
    except requests.RequestException as e:
        HTTPLog.create_from_exception(HTTPLog.WHATSAPP_FLOWS_SYNCED, url, e, start, channel=channel)
        return []


def _get_token(channel):
    wa_user_token = channel.config.get("wa_user_token")

    token = wa_user_token if wa_user_token else settings.WHATSAPP_ADMIN_SYSTEM_USER_TOKEN

    return token


def update_whatsapp_flows(flows, channel):
    seen = []

    for obj in flows:
        flow = WhatsappFlows.objects.filter(facebook_flow_id=obj.get("id"), channel=channel).first()
        if flow:
            print("opa opa")
            print("object retornado fluxo", flow)
            flow.category = (obj.get("categories"),)
            flow.status = (obj.get("status"),)
            flow.name = (obj.get("name"),)
            flow.validation_errors = (obj.get("validation_errors"),)
            flow.modified_on = timezone.now()
            flow.save()

        else:
            WhatsappFlows.objects.create(
                facebook_flow_id=obj.get("id"),
                category=obj.get("categories"),
                status=obj.get("status"),
                name=obj.get("name"),
                validation_errors=obj.get("validation_errors"),
                org=channel.org,
                channel=channel,
                is_active=True,
            )

        seen.append(obj.get("id"))

    WhatsappFlows.trim(channel, seen)
