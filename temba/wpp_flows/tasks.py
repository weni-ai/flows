import logging

import requests
from django_redis import get_redis_connection

from django.conf import settings
from django.utils import timezone

from celery import shared_task

from temba.channels.models import Channel
from temba.request_logs.models import HTTPLog
from temba.wpp_flows.models import WhatsappFlow

logger = logging.getLogger(__name__)


@shared_task(track_started=True, name="refresh_whatsapp_flows")
def refresh_whatsapp_flows():
    """
    Runs across all WhatsApp flows that have connected FB accounts and syncs the flows which are active.
    """

    r = get_redis_connection()
    if r.get("refresh_whatsapp_flows"):  # pragma: no cover
        return

    with r.lock("refresh_whatsapp_flows", 1800):
        for channel in Channel.objects.filter(is_active=True, channel_type__in=["WA", "WAC"]):
            if channel.config.get("wa_waba_id"):
                flows = get_whatsapp_flows(channel)

                if flows:
                    update_whatsapp_flows(flows, channel)


def refresh_whatsapp_flows_for_a_channel(channel):
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
                HTTPLog.WHATSAPP_FLOWS_SYNCED,
                url,
                resp,
                channel=channel,
                request_time=elapsed,
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
        flow = WhatsappFlow.objects.filter(facebook_flow_id=obj.get("id"), channel=channel).first()
        assets_data = get_assets_data(channel, obj.get("id"))
        variables = extract_data_keys(assets_data)

        if flow:
            flow.category = obj.get("categories")
            flow.status = obj.get("status")
            flow.name = obj.get("name")
            flow.validation_errors = obj.get("validation_errors")
            flow.screens = assets_data
            flow.variables = variables
            flow.modified_on = timezone.now()
            flow.save()

        else:
            WhatsappFlow.objects.create(
                facebook_flow_id=obj.get("id"),
                category=obj.get("categories"),
                status=obj.get("status"),
                name=obj.get("name"),
                validation_errors=obj.get("validation_errors"),
                screens=assets_data,
                variables=variables,
                org=channel.org,
                channel=channel,
                is_active=True,
            )

        seen.append(obj.get("id"))

    WhatsappFlow.trim(channel, seen)


def get_assets_data(channel, facebook_flow_id):
    token = _get_token(channel)
    url = f"{settings.WHATSAPP_API_URL}/{facebook_flow_id}/assets"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            assets_info = resp.json().get("data", [])

            if assets_info and "download_url" in assets_info[0]:
                download_url = assets_info[0]["download_url"]
                # get JSON of download_url
                json_data = requests.get(download_url).json()
                return json_data
    except requests.RequestException as e:
        start = timezone.now()
        HTTPLog.create_from_exception(HTTPLog.WHATSAPP_FLOWS_SYNCED, url, e, start, channel=channel)

    return {}


def extract_data_keys(json_data):
    keys = []
    screens_ids = []

    def extract_keys(data):
        if isinstance(data, dict):
            if "id" in data and isinstance(data["id"], str):
                screens_ids.append(data["id"])
            for key, value in data.items():
                if key == "data" and isinstance(value, dict):
                    keys.extend(value.keys())
                extract_keys(value)
        elif isinstance(data, list):
            for item in data:
                extract_keys(item)

    extract_keys(json_data)
    return {"screens": list(set(screens_ids)), "variables": list(set(keys))}


def get_whatsapp_flow_by_id(flow_id):
    token = settings.WHATSAPP_ADMIN_SYSTEM_USER_TOKEN
    headers = {"Authorization": f"Bearer {token}"}

    try:
        url = f"{settings.WHATSAPP_API_URL}/{flow_id}?fields=id,name,categories,status,validation_errors,whatsapp_business_account"

        headers = {"Authorization": f"Bearer {token}"}

        resp = requests.get(url, params=dict(limit=255), headers=headers)

        if resp.status_code != 200:  # pragma: no cover
            return []

        return resp.json()
    except requests.RequestException as e:
        logger.error("error getting whatsapp flow by id", e)
        return []


def update_whatsapp_flow_by_id(flow_id):
    flow = get_whatsapp_flow_by_id(flow_id)

    waba_id = flow["whatsapp_business_account"]["id"]
    channels = Channel.objects.filter(is_active=True, channel_type__in=["WA", "WAC"])

    for channel in channels:

        if channel.config.get("wa_waba_id") == waba_id:
            create_single_whatsapp_flow(flow, channel)


def create_single_whatsapp_flow(flow, channel):
    assets_data = get_assets_data(channel, flow.get("id"))
    variables = extract_data_keys(assets_data)

    WhatsappFlow.objects.create(
        facebook_flow_id=flow.get("id"),
        category=flow.get("categories"),
        status=flow.get("status"),
        name=flow.get("name"),
        validation_errors=flow.get("validation_errors"),
        screens=assets_data,
        variables=variables,
        org=channel.org,
        channel=channel,
        is_active=True,
    )


@shared_task(track_started=True, name="refresh_whatsapp_flows_assets")
def refresh_whatsapp_flows_assets():
    """
    Runs across all WhatsApp flows that have connected FB accounts and syncs the flows assets.
    """

    r = get_redis_connection()
    if r.get("refresh_whatsapp_flows_assets"):  # pragma: no cover
        return

    with r.lock("refresh_whatsapp_flows_assets", 1800):
        for flow in WhatsappFlow.objects.filter(is_active=True):
            channel = flow.channel

            assets_data = get_assets_data(channel, flow)
            variables = extract_data_keys(assets_data)
            
            flow.screens = assets_data
            flow.variables = variables
            flow.modified_on = timezone.now()
            flow.save()
