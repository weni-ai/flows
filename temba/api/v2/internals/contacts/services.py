from pathlib import Path

import pyexcel
from xlsxlite.writer import XLSXBook

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.temp import NamedTemporaryFile
from django.utils.text import slugify

from temba.contacts.models import Contact, ContactImport
from temba.msgs.models import Msg
from temba.utils.export import TableExporter
from temba.utils.text import decode_stream
from temba.utils.uuid import uuid4


class ContactImportDeduplicationService:
    EXPIRE_SECONDS = 3600
    DUP_PREFIX = "temp/duplicated_contacts"

    @staticmethod
    def _finalize_workbook_to_temp(workbook: XLSXBook, suffix: str = ".xlsx"):
        tmp = NamedTemporaryFile(delete=False, suffix=suffix, mode="wb+")
        workbook.finalize(to_file=tmp)
        tmp.flush()
        tmp.seek(0)
        return tmp

    @staticmethod
    def _get_s3_client():
        try:
            import boto3

            region = getattr(settings, "AWS_S3_REGION_NAME", None) or getattr(settings, "AWS_DEFAULT_REGION", None)
            access_key = getattr(settings, "AWS_ACCESS_KEY_ID", None)
            secret_key = getattr(settings, "AWS_SECRET_ACCESS_KEY", None)
            session_token = getattr(settings, "AWS_SESSION_TOKEN", None)

            return boto3.client(
                "s3",
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                aws_session_token=session_token,
            )
        except Exception:  # pragma: no cover
            return None

    @classmethod
    def _upload_to_s3_and_presign(cls, bucket: str, key: str, tmp_name: str, readable_name: str):
        s3 = cls._get_s3_client()
        if not s3:
            return None, "AWS client not available (check credentials/region)"

        try:
            with open(tmp_name, "rb") as fh:
                s3.upload_fileobj(
                    fh,
                    bucket,
                    key,
                    ExtraArgs={
                        "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "ContentDisposition": f"attachment; filename={readable_name}",
                    },
                )
            url = s3.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": bucket,
                    "Key": key,
                    "ResponseContentDisposition": f"attachment; filename={readable_name}",
                },
                ExpiresIn=cls.EXPIRE_SECONDS,
            )
            return url, None
        except Exception as e:
            return None, f"S3 upload/presign failed: {type(e).__name__}"

    @staticmethod
    def process(org, file, filename: str):
        try:
            file_type = Path(filename).suffix[1:].lower()
        except Exception:
            file_type = "csv"

        # prepare stream
        stream = decode_stream(file) if file_type == "csv" else file
        data = pyexcel.iget_array(file_stream=stream, file_type=file_type)

        # headers
        try:
            headers = [str(h).strip() for h in next(data)]
        except StopIteration:
            raise ValidationError("Import file appears to be empty.")
        if any(h == "" for h in headers):
            raise ValidationError("Import file contains an empty header.")

        # mappings and validation
        mappings = ContactImport._auto_mappings(org, headers)
        ContactImport._validate_mappings(mappings)

        # initialize writers for deduped data and duplicates
        dedup_book = XLSXBook()
        dedup_sheet = dedup_book.add_sheet("Contacts 1")
        dedup_sheet.append_row(*headers)

        dups_book = XLSXBook()
        dups_sheet = dups_book.add_sheet("Duplicated Contacts 1")
        dups_sheet.append_row(*headers)

        seen_uuids = set()
        seen_urns = set()
        num_unique = 0
        num_dups = 0

        for raw_row in data:
            row = ContactImport._parse_row(raw_row, len(mappings))
            uuid, urns = ContactImport._extract_uuid_and_urns(row, mappings, org)

            is_dup = False
            if uuid:
                if uuid in seen_uuids:
                    is_dup = True
                else:
                    seen_uuids.add(uuid)

            if not is_dup:
                for urn in urns:
                    if urn in seen_urns:
                        is_dup = True
                        break

            if is_dup:
                dups_sheet.append_row(*row)
                num_dups += 1
                continue

            # record as unique
            for urn in urns:
                seen_urns.add(urn)
            dedup_sheet.append_row(*row)
            num_unique += 1

            if num_unique > ContactImport.MAX_RECORDS:
                raise ValidationError(
                    "Import files can contain a maximum of %(max)d records.", params={"max": ContactImport.MAX_RECORDS}
                )

        if num_unique == 0:
            raise ValidationError("Import file doesn't contain any records.")

        # build deduplicated temp file
        dedup_tmp = ContactImportDeduplicationService._finalize_workbook_to_temp(dedup_book)

        # if duplicates exist, upload duplicates workbook and get URL
        duplicates_url = None
        duplicates_error = None
        if num_dups > 0:
            dups_tmp = ContactImportDeduplicationService._finalize_workbook_to_temp(dups_book)

            # determine readable file name and key
            default_group_name = ContactImport(org=org, original_filename=filename).get_default_group_name()
            safe_group = slugify(default_group_name) or "import"
            safe_org = slugify(org.name) or f"org-{org.id}"
            readable_name = f"{safe_group}_{safe_org}_duplicated_contacts.xlsx"
            storage_path = f"{ContactImportDeduplicationService.DUP_PREFIX}/{org.id}/{uuid4()}_{readable_name}"

            # Prefer direct S3 upload + presign if bucket configured
            bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", None)
            if bucket:
                duplicates_url, duplicates_error = ContactImportDeduplicationService._upload_to_s3_and_presign(
                    bucket=bucket,
                    key=storage_path,
                    tmp_name=dups_tmp.name,
                    readable_name=readable_name,
                )
            else:
                duplicates_error = "AWS bucket not configured"

            # No fallback to local storage: if S3 upload/presign fails, we return without URL
            # if not duplicates_url: no local fallback by design

        # return mappings, counts, temp file, extension, url and error
        return mappings, num_unique, dedup_tmp, "xlsx", duplicates_url, num_dups, duplicates_error


class ContactDownloadByStatusService:
    @staticmethod
    def _generate_xlsx_for_contacts(org, contact_ids):
        columns = ["Contact UUID", "Name", "URNs", "Language", "Created On", "Last Seen On"]
        exporter = TableExporter(task=None, sheet_name="Contacts", columns=columns)

        # write out contacts in batches to limit memory usage
        def chunk_list(items, size):
            for i in range(0, len(items), size):
                yield items[i : i + size]

        total_ids = list(contact_ids)
        for batch_ids in chunk_list(total_ids, 1000):
            batch_contacts = (
                Contact.objects.filter(id__in=batch_ids)
                .select_related("org")
                .only("id", "uuid", "name", "language", "created_on", "last_seen_on")
                .using("readonly")
            )

            contact_by_id = {c.id: c for c in batch_contacts}

            # cache URNs
            Contact.bulk_urn_cache_initialize(batch_contacts, using="readonly")

            for cid in batch_ids:
                contact = contact_by_id.get(cid)
                if not contact:
                    continue

                urns = contact.get_urns()
                urns_str = ", ".join([u.identity for u in urns]) if urns else ""

                exporter.write_row(
                    [
                        str(contact.uuid),
                        contact.name or "",
                        urns_str,
                        contact.language or "",
                        contact.created_on,
                        contact.last_seen_on,
                    ]
                )

        temp_file, ext = exporter.save_file()
        return temp_file, ext

    @staticmethod
    def get_contact_ids_by_broadcast_status(*, broadcast_id: int, msg_status: str):
        if not broadcast_id:
            raise ValidationError("Broadcast ID is required")
        valid_statuses = [s[0] for s in Msg.STATUS_CHOICES]
        if msg_status not in valid_statuses:
            raise ValidationError("Invalid status")
        msgs = Msg.objects.filter(broadcast_id=broadcast_id, status=msg_status)
        return list(msgs.values_list("contact_id", flat=True).distinct())
