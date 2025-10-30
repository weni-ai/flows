import logging
from datetime import timedelta

import iso8601
import pytz

from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone

from celery import shared_task

from temba.api.v2.internals.contacts.services import ContactDownloadByStatusService
from temba.assets.models import get_asset_store
from temba.notifications.models import Notification
from temba.utils import chunk_list
from temba.utils.celery import nonoverlapping_task
from temba.utils.export import BaseExportTask, TableExporter

from .models import Contact, ContactGroup, ContactGroupCount, ContactImport, ExportContactsTask
from .search import elastic

logger = logging.getLogger(__name__)


@shared_task(track_started=True)
def release_contacts(user_id, contact_ids):
    """
    Releases the given contacts
    """
    user = User.objects.get(pk=user_id)

    for id_batch in chunk_list(contact_ids, 100):
        batch = Contact.objects.filter(id__in=id_batch, is_active=True).prefetch_related("urns")
        for contact in batch:
            contact.release(user)


@shared_task(track_started=True)
def import_contacts_task(import_id):
    """
    Import contacts from a spreadsheet
    """
    ContactImport.objects.select_related("org", "created_by").get(id=import_id).start()


@shared_task(track_started=True, name="export_contacts_task")
def export_contacts_task(task_id):
    """
    Export contacts to a file and e-mail a link to the user
    """
    ExportContactsTask.objects.select_related("org", "created_by").get(id=task_id).perform()


@shared_task(track_started=True, name="export_contacts_by_status_task")
def export_contacts_by_status_task(export_id: int, broadcast_id: int, msg_status: str):
    try:
        export = ExportContactsTask.objects.select_related("org", "created_by").get(id=export_id)
    except ExportContactsTask.DoesNotExist:
        return

    try:
        export.status = BaseExportTask.STATUS_PROCESSING
        export.save(update_fields=("status", "modified_on"))

        contact_ids = ContactDownloadByStatusService.get_contact_ids_by_broadcast_status(
            broadcast_id=broadcast_id, msg_status=msg_status
        )

        fields, _, group_fields = export.get_export_fields_and_schemes()
        exporter = TableExporter(export, "Contact", [f["label"] for f in fields] + [g["label"] for g in group_fields])

        def chunk_list_local(items, size):
            for i in range(0, len(items), size):
                yield items[i : i + size]

        include_group_memberships = bool(export.group_memberships.exists())
        for batch_ids in chunk_list_local(contact_ids, 1000):
            batch_contacts = (
                Contact.objects.filter(id__in=batch_ids).prefetch_related("org", "all_groups").using("readonly")
            )
            contact_by_id = {c.id: c for c in batch_contacts}
            Contact.bulk_urn_cache_initialize(batch_contacts, using="readonly")

            for cid in batch_ids:
                contact = contact_by_id.get(cid)
                if not contact:
                    continue
                values = []
                for field in fields:
                    value = export.get_field_value(field, contact)
                    values.append(export.prepare_value(value))

                group_values = []
                if include_group_memberships:
                    contact_groups_ids = [g.id for g in contact.all_groups.all()]
                    for col in range(len(group_fields)):
                        field = group_fields[col]
                        group_values.append(field["group_id"] in contact_groups_ids)

                exporter.write_row(values + group_values)

        temp_file, extension = exporter.save_file()

        get_asset_store(model=ExportContactsTask).save(export.id, temp_file, extension)

        if hasattr(temp_file, "delete"):
            temp_file.delete()

        export.status = BaseExportTask.STATUS_COMPLETE
        export.save(update_fields=("status", "modified_on"))
        Notification.export_finished(export)
    except Exception:
        export.status = BaseExportTask.STATUS_FAILED
        export.save(update_fields=("status", "modified_on"))


@nonoverlapping_task(track_started=True, name="release_group_task")
def release_group_task(group_id):
    """
    Releases group
    """
    ContactGroup.all_groups.get(id=group_id)._full_release()


@nonoverlapping_task(track_started=True, name="squash_contactgroupcounts", lock_timeout=7200)
def squash_contactgroupcounts():
    """
    Squashes our ContactGroupCounts into single rows per ContactGroup
    """
    ContactGroupCount.squash()


@shared_task(track_started=True, name="full_release_contact")
def full_release_contact(contact_id):
    contact = Contact.objects.filter(id=contact_id).first()

    if contact and not contact.is_active:
        contact._full_release()


@shared_task(name="check_elasticsearch_lag")
def check_elasticsearch_lag():
    if settings.ELASTICSEARCH_URL:
        es_last_modified_contact = elastic.get_last_modified()

        if es_last_modified_contact:
            # if we have elastic results, make sure they aren't more than five minutes behind
            db_contact = Contact.objects.order_by("-modified_on").first()
            es_modified_on = iso8601.parse_date(es_last_modified_contact["modified_on"], pytz.utc)
            es_id = es_last_modified_contact["id"]

            # no db contact is an error, ES should be empty as well
            if not db_contact:
                logger.error(
                    "db empty but ElasticSearch has contacts. Newest ES(id: %d, modified_on: %s)",
                    es_id,
                    es_modified_on,
                )
                return False

            #  check the lag between the two, shouldn't be more than 5 minutes
            if db_contact.modified_on - es_modified_on > timedelta(minutes=5):
                logger.error(
                    "drift between ElasticSearch and DB. Newest DB(id: %d, modified_on: %s) Newest ES(id: %d, modified_on: %s)",
                    db_contact.id,
                    db_contact.modified_on,
                    es_id,
                    es_modified_on,
                )

                return False

        else:
            # we don't have any ES hits, get our oldest db contact, check it is less than five minutes old
            db_contact = Contact.objects.order_by("modified_on").first()
            if db_contact and timezone.now() - db_contact.modified_on > timedelta(minutes=5):
                logger.error(
                    "ElasticSearch empty with DB contacts older than five minutes. Oldest DB(id: %d, modified_on: %s)",
                    db_contact.id,
                    db_contact.modified_on,
                )

                return False

    return True
