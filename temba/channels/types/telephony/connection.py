"""
Connection data a customer needs to point their PBX at the platform (spec 019, contracts/internals-sip-endpoints.md).

Built from the channel config and settings only. Nothing here reads the cluster, and the password is never part of it:
the endpoint that issues a password adds it to the response itself.
"""

import logging

from django.conf import settings

from . import constants, manifests

logger = logging.getLogger(__name__)


def parse_transports(entries):
    """``["tls:5061", "udp:5060"]`` to ``[{"protocol": "tls", "port": 5061}, ...]``. Malformed entries are skipped."""
    transports = []
    for entry in entries:
        protocol, _, port = entry.partition(":")
        if protocol and port.isdigit():
            transports.append({"protocol": protocol.lower(), "port": int(port)})
        else:
            logger.warning("tph sip: ignoring malformed transport setting", extra={"entry": entry})
    return transports


def build_connection_data(channel, status):
    config = channel.config or {}
    return {
        "status": status,
        "domain": settings.TPH_SIP_DOMAIN,
        "transports": parse_transports(settings.TPH_SIP_TRANSPORTS),
        "username": config.get(constants.CONFIG_SIP_USERNAME),
        "did": manifests.normalize_did_for_route(channel.address),
        "signaling_ips": list(settings.TPH_SIP_SIGNALING_IPS),
        "media": {
            "ips": list(settings.TPH_SIP_MEDIA_IPS),
            "rtp_port_range": settings.TPH_SIP_RTP_PORT_RANGE,
        },
        "codecs": list(settings.TPH_SIP_CODECS),
        "dtmf_mode": settings.TPH_SIP_DTMF_MODE,
        "credentials_reset_required": bool(config.get(constants.CONFIG_SIP_RESET_REQUIRED)),
    }
