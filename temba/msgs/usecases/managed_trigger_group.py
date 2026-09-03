import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings
from django.db import close_old_connections, connection, transaction
from django.db.utils import IntegrityError
from django.utils import timezone

from temba.contacts.models import Contact, ContactGroup
from temba.mailroom import modifiers
from temba.mailroom.client import MailroomException
from temba.msgs.models import ManagedTriggerGroup
from temba.orgs.models import Org
from temba.triggers.models import Trigger
from temba.triggers.usecases import create_catchall_trigger

logger = logging.getLogger(__name__)

GROUP_NAME_PREFIX = "Trigger · "


class GroupQuotaExceeded(Exception):
    def __init__(self, count: int, limit: int):
        self.count = count
        self.limit = limit
        super().__init__(
            "This workspace has %s groups and the limit is %s. "
            "You must delete existing ones before you can create new ones." % (count, limit)
        )


class ContactResolutionError(Exception):
    def __init__(self, urn: str = None):
        self.urn = urn
        super().__init__("Couldn't resolve or create a contact for one or more URNs")


def managed_trigger_group_display_name(flow) -> str:
    prefix = GROUP_NAME_PREFIX
    remaining = ContactGroup.MAX_NAME_LEN - len(prefix)
    flow_name = (flow.name or "flow").strip()
    if remaining < 1:
        candidate = "Broadcast trigger"
    else:
        candidate = prefix + flow_name[:remaining]
    cleaned = ContactGroup.clean_name(candidate)
    if not ContactGroup.is_valid_name(cleaned):
        return "Broadcast trigger"
    return cleaned


def resolve_or_create_managed_trigger_group(org, user, flow) -> ContactGroup:
    association = ManagedTriggerGroup.objects.select_related("group").filter(org=org, flow=flow).first()
    created_group = False

    if association and association.group.is_active:
        group = association.group
    else:
        limit = org.get_limit(Org.LIMIT_GROUPS)
        count = ContactGroup.user_groups.filter(org=org).count()
        if count >= limit:
            raise GroupQuotaExceeded(count, limit)

        group = ContactGroup.create_static(org, user, managed_trigger_group_display_name(flow))
        created_group = True

        if association:
            association.group = group
            association.modified_on = timezone.now()
            association.save(update_fields=("group", "modified_on"))
        else:
            try:
                with transaction.atomic():
                    association = ManagedTriggerGroup.objects.create(org=org, flow=flow, group=group)
            except IntegrityError:
                association = ManagedTriggerGroup.objects.select_related("group").get(org=org, flow=flow)
                if association.group_id != group.id:
                    group.release(user)
                    group = association.group
                    created_group = False

    _ensure_catchall(org, user, flow, group)
    logger.info(
        "managed_trigger_group resolved org_id=%s flow_uuid=%s group_uuid=%s group_created=%s",
        org.id,
        flow.uuid,
        group.uuid,
        created_group,
    )
    return group


def _ensure_catchall(org, user, flow, group) -> Trigger:
    existing = (
        Trigger.objects.filter(
            org=org,
            flow=flow,
            trigger_type=Trigger.TYPE_CATCH_ALL,
            is_active=True,
            groups=group,
        )
        .order_by("id")
        .first()
    )
    if existing:
        if existing.is_archived:
            existing.restore(user)
            logger.info(
                "managed_trigger_group catchall restored org_id=%s trigger_id=%s group_uuid=%s",
                org.id,
                existing.id,
                group.uuid,
            )
        return existing

    trigger = create_catchall_trigger(org=org, user=user, flow=flow, groups=[group])
    logger.info(
        "managed_trigger_group catchall created org_id=%s trigger_id=%s group_uuid=%s",
        org.id,
        trigger.id,
        group.uuid,
    )
    return trigger


def resolve_contacts_for_urns(org, user, urns: list) -> list:
    unique_urns = list(dict.fromkeys(urns or []))
    resolved = []
    missing = []
    for urn in unique_urns:
        contact = Contact.from_urn(org, urn)
        if contact:
            resolved.append(contact)
        else:
            missing.append(urn)

    created = _create_contacts(org, user, missing)
    return resolved + created


def _create_contacts(org, user, urns: list) -> list:
    if not urns:
        return []

    concurrency = int(getattr(settings, "WHATSAPP_BROADCAST_URN_RESOLVE_CONCURRENCY", 20))
    use_threads = len(urns) > 1 and concurrency > 1 and not connection.in_atomic_block

    if not use_threads:
        return [_create_contact(org, user, urn) for urn in urns]

    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(_create_contact_in_thread, org, user, urn): urn for urn in urns}
        for future in as_completed(futures):
            urn = futures[future]
            try:
                results.append(future.result())
            except ContactResolutionError:
                raise
            except Exception as e:  # pragma: no cover
                raise ContactResolutionError(urn) from e
    return results


def _create_contact(org, user, urn: str) -> Contact:
    try:
        return Contact.create(org, user, name="", language="", urns=[urn], fields={}, groups=[])
    except MailroomException as e:
        raise ContactResolutionError(urn) from e


def _create_contact_in_thread(org, user, urn: str) -> Contact:
    close_old_connections()
    try:
        return _create_contact(org, user, urn)
    finally:
        close_old_connections()


def assign_exclusive_membership(org, user, contacts, target_group: ContactGroup) -> None:
    if not contacts:
        return

    unique = list({c.id: c for c in contacts}.values())
    other_groups = [
        assoc.group
        for assoc in ManagedTriggerGroup.objects.filter(org=org).exclude(group=target_group).select_related("group")
        if assoc.group.is_active
    ]

    mods = [
        modifiers.Groups(
            groups=[modifiers.GroupRef(uuid=str(target_group.uuid), name=target_group.name)],
            modification="add",
        )
    ]
    if other_groups:
        mods.append(
            modifiers.Groups(
                groups=[modifiers.GroupRef(uuid=str(g.uuid), name=g.name) for g in other_groups],
                modification="remove",
            )
        )

    Contact.bulk_modify(user, unique, mods)
    logger.info(
        "managed_trigger_group membership moved org_id=%s group_uuid=%s contact_count=%s other_groups=%s",
        org.id,
        target_group.uuid,
        len(unique),
        len(other_groups),
    )


def prepare_trigger_group_for_broadcast(org, user, flow, urns, contacts) -> ContactGroup:
    """
    Resolve or create the managed trigger group, materialize URNs as contacts, and
    move those contacts plus any referenced contacts into the group exclusively.
    """
    group = resolve_or_create_managed_trigger_group(org, user, flow)
    resolved = resolve_contacts_for_urns(org, user, urns)
    by_id = {c.id: c for c in resolved}
    for contact in contacts or []:
        by_id[contact.id] = contact
    assign_exclusive_membership(org, user, list(by_id.values()), group)
    return group
