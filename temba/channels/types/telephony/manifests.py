"""
Pure functions that build the KubeVoIP objects of one TPH channel (spec 019, data-model.md).

The isolation between customers lives here: every channel gets its own scope, dial policy, route and SIP user, the route
matches only the channel's DID and the SIP user references only the channel's own dial policy. These functions take no
cluster and no database, so the invariants can be asserted directly.
"""

import re

from django.conf import settings

from . import constants

NON_DIGITS = re.compile(r"\D")


def resource_name(channel_uuid):
    """``tph-`` plus the 32 hexadecimal characters of the UUID. It fits the 40 character limit of ``authUsername``."""
    return constants.RESOURCE_NAME_PREFIX + str(channel_uuid).replace("-", "")


def normalize_did_for_route(address):
    """
    The number a PBX must dial, as used in the call route: the channel address with every non-digit removed
    (``+5511912345678`` becomes ``5511912345678``). This is the single place of that rule (OQ-03, T-STG-3).
    """
    digits = NON_DIGITS.sub("", address or "")
    if not digits:
        raise ValueError("the channel address has no digits")
    return digits


def sip_extension(channel_id):
    """Prefix from settings plus the channel id, zero padded to ``SIP_EXTENSION_LENGTH`` digits."""
    prefix = settings.TPH_SIP_EXTENSION_PREFIX
    return prefix + str(channel_id).zfill(constants.SIP_EXTENSION_LENGTH - len(prefix))


def managed_labels(channel_uuid):
    """The only labels set on objects created by Flows (FR-018)."""
    return {constants.MANAGED_BY_LABEL: constants.MANAGED_BY_VALUE, constants.CHANNEL_UUID_LABEL: str(channel_uuid)}


def label_selector(channel_uuid=None):
    selector = f"{constants.MANAGED_BY_LABEL}={constants.MANAGED_BY_VALUE}"
    if channel_uuid is not None:
        selector += f",{constants.CHANNEL_UUID_LABEL}={channel_uuid}"
    return selector


def _metadata(name, channel_uuid):
    return {"name": name, "namespace": settings.TPH_SIP_K8S_NAMESPACE, "labels": managed_labels(channel_uuid)}


def _api_version():
    return f"{constants.KUBEVOIP_API_GROUP}/{constants.KUBEVOIP_API_VERSION}"


def build_call_scope(channel_uuid):
    name = resource_name(channel_uuid)
    return {
        "apiVersion": _api_version(),
        "kind": constants.KIND_CALL_SCOPE,
        "metadata": _metadata(name, channel_uuid),
        "spec": {"gatewayRef": {"name": settings.TPH_SIP_GATEWAY_NAME}},
    }


def build_dial_policy(channel_uuid):
    name = resource_name(channel_uuid)
    return {
        "apiVersion": _api_version(),
        "kind": constants.KIND_DIAL_POLICY,
        "metadata": _metadata(name, channel_uuid),
        # exactly one scope, the channel's own. Never the shared internal scope
        "spec": {"gatewayRef": {"name": settings.TPH_SIP_GATEWAY_NAME}, "scopes": [{"name": name}]},
    }


def build_call_route(channel_uuid, address):
    name = resource_name(channel_uuid)
    return {
        "apiVersion": _api_version(),
        "kind": constants.KIND_CALL_ROUTE,
        "metadata": _metadata(name, channel_uuid),
        "spec": {
            "gatewayRef": {"name": settings.TPH_SIP_GATEWAY_NAME},
            "scopeRef": {"name": name},
            # the DID only, no wildcard: this credential cannot reach any other number
            "match": {"calledNumber": normalize_did_for_route(address)},
            "target": {
                "asteriskPoolRef": settings.TPH_SIP_ASTERISK_POOL,
                "extension": settings.TPH_SIP_ASTERISK_EXTENSION,
            },
        },
    }


def build_sip_user(channel_uuid, channel_id, address):
    name = resource_name(channel_uuid)
    return {
        "apiVersion": _api_version(),
        "kind": constants.KIND_SIP_USER,
        "metadata": _metadata(name, channel_uuid),
        "spec": {
            "gatewayRef": {"name": settings.TPH_SIP_GATEWAY_NAME},
            "dialPolicyRef": {"name": name},
            "extension": sip_extension(channel_id),
            "authUsername": name,
            "callerId": normalize_did_for_route(address),
            "passwordSecretRef": {"name": settings.TPH_SIP_CREDENTIALS_SECRET, "key": name},
        },
    }


def build_custom_resources(channel_uuid, channel_id, address):
    """The four custom resources in creation order, as ``(kind, body)`` pairs."""
    return [
        (constants.KIND_CALL_SCOPE, build_call_scope(channel_uuid)),
        (constants.KIND_DIAL_POLICY, build_dial_policy(channel_uuid)),
        (constants.KIND_CALL_ROUTE, build_call_route(channel_uuid, address)),
        (constants.KIND_SIP_USER, build_sip_user(channel_uuid, channel_id, address)),
    ]
