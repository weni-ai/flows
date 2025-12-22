from __future__ import annotations

from typing import Iterable, Optional, Sequence

from django.utils import timezone

from temba.channels.models import Channel
from temba.contacts.models import URN, Contact, ContactURN
from temba.msgs.models import Label, Msg
from temba.orgs.models import Org


def create_message_db_only(
    *,
    org: Org,
    direction: str,
    text: Optional[str] = "",
    contact_uuid: Optional[str] = None,
    urn: Optional[str] = None,
    channel_uuid: Optional[str] = None,
    status: Optional[str] = None,
    created_on=None,
    sent_on=None,
    attachments: Optional[Sequence[str]] = None,
    visibility: Optional[str] = None,
    labels: Optional[Iterable[str]] = None,
) -> Msg:
    """
    Creates a message record only, without invoking mailroom/courier.
    The caller is responsible for providing the minimum identifying inputs.
    """
    now = timezone.now()
    attachments = list(attachments or [])
    visibility = visibility or Msg.VISIBILITY_VISIBLE

    # normalize direction
    direction = direction.upper()
    if direction not in ("I", "O"):
        raise ValueError("direction must be one of: I, O, in, out")
    if direction == "IN":
        direction = "I"
    if direction == "OUT":
        direction = "O"

    # resolve contact and contact_urn
    contact: Optional[Contact] = None
    contact_urn: Optional[ContactURN] = None

    if contact_uuid:
        contact = Contact.objects.filter(org=org, uuid=contact_uuid).first()
        if not contact:
            raise ValueError("Contact not found for this project")

    normalized_identity: Optional[str] = None
    if urn:
        normalized_identity = URN.identity(URN.normalize(urn, country_code=org.default_country_code))
        contact_urn = (
            ContactURN.objects.filter(org=org, identity=normalized_identity)
            .select_related("contact", "channel")
            .first()
        )
        if contact_urn and not contact:
            contact = contact_urn.contact

    if not contact:
        raise ValueError("Unable to resolve contact from contact_uuid or urn")

    # resolve channel
    channel = None
    if channel_uuid:
        channel = Channel.objects.filter(org=org, uuid=channel_uuid).first()
        if not channel:
            raise ValueError("Channel not found for this project")
    else:
        # try to infer from contact URN
        if contact_urn and contact_urn.channel:
            channel = contact_urn.channel
        else:
            # fall back to the contact's primary URN channel when possible
            primary_urn = contact.get_urn()
            if primary_urn:
                contact_urn = contact_urn or primary_urn
                channel = primary_urn.channel

    # defaults and state handling
    if direction == Msg.DIRECTION_IN:
        default_status = Msg.STATUS_HANDLED
        msg_type = Msg.TYPE_INBOX
    else:
        default_status = Msg.STATUS_SENT
        msg_type = Msg.TYPE_INBOX

    status = status or default_status
    if (
        direction == Msg.DIRECTION_OUT
        and status
        in (
            Msg.STATUS_WIRED,
            Msg.STATUS_SENT,
            Msg.STATUS_DELIVERED,
        )
        and not sent_on
    ):
        sent_on = now

    msg = Msg.objects.create(
        org=org,
        contact=contact,
        contact_urn=contact_urn,
        channel=channel,
        direction=direction,
        text=text or "",
        attachments=attachments,
        status=status,
        msg_type=msg_type,
        visibility=visibility,
        created_on=created_on or now,
        sent_on=sent_on,
    )

    # attach labels if provided
    if labels:
        label_objs = list(Label.label_objects.filter(org=org, uuid__in=list(labels)))
        if label_objs:
            msg.labels.add(*label_objs)

    return msg
