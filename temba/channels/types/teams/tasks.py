import logging

import requests
from django_redis import get_redis_connection

from django.utils import timezone

from celery import shared_task

from temba.channels.models import Channel
from temba.request_logs.models import HTTPLog

from .type import TeamsType

logger = logging.getLogger(__name__)


@shared_task(track_started=True, name="refresh_teams_tokens")
def refresh_teams_tokens():
    r = get_redis_connection()
    if r.get("refresh_teams_tokens"):  # pragma: no cover
        return
    with r.lock("refresh_teams_tokens", 1800):
        # iterate across each of our teams channels and get a new token
        for channel in Channel.objects.filter(is_active=True, channel_type="TM").order_by("id"):
            try:
                # Build candidate endpoints based on per-channel preference
                tenant_id = channel.config.get(TeamsType.CONFIG_TEAMS_TENANT_ID)
                preference = channel.config.get(TeamsType.CONFIG_TEAMS_TOKEN_PREFERENCE, "botframework")

                # Assemble candidates explicitly based on preference
                candidates = []
                if preference == "graph":
                    if tenant_id:
                        candidates.append(
                            (
                                f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
                                "https://graph.microsoft.com/.default",
                                "graph",
                            )
                        )
                    candidates.append(
                        (
                            "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token",
                            "https://api.botframework.com/.default",
                            "botframework",
                        )
                    )
                else:  # default and any other value: botframework first
                    candidates.append(
                        (
                            "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token",
                            "https://api.botframework.com/.default",
                            "botframework",
                        )
                    )
                    if tenant_id:
                        candidates.append(
                            (
                                f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
                                "https://graph.microsoft.com/.default",
                                "graph",
                            )
                        )

                # common pieces
                common_body = {
                    "client_id": channel.config[TeamsType.CONFIG_TEAMS_APPLICATION_ID],
                    "grant_type": "client_credentials",
                    "client_secret": channel.config[TeamsType.CONFIG_TEAMS_APPLICATION_PASSWORD],
                }
                headers = {"Content-Type": "application/x-www-form-urlencoded"}

                token_obtained = None
                for url, scope, source in candidates:
                    request_body = dict(common_body, scope=scope)

                    start = timezone.now()
                    resp = requests.post(url, data=request_body, headers=headers, timeout=15)
                    elapsed = (timezone.now() - start).total_seconds() * 1000

                    HTTPLog.create_from_response(
                        HTTPLog.TEAMS_TOKENS_SYNCED, url, resp, channel=channel, request_time=elapsed
                    )

                    if resp.status_code != 200:
                        continue

                    access_token = (resp.json() or {}).get("access_token")
                    if access_token:
                        token_obtained = access_token
                        # store which source produced the token to aid debugging, but don't rely on it elsewhere
                        channel.config["auth_token"] = access_token
                        channel.config["teams_token_source"] = source  # informational
                        channel.save(update_fields=["config"])
                        break

                if not token_obtained:
                    # Nothing succeeded, move on to next channel
                    continue

            except Exception as e:
                logger.error(f"Error refreshing teams tokens: {str(e)}", exc_info=True)
