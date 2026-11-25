"""
Media files sent inline (multipart/form-data) with a WhatsApp broadcast request.

The type of every file is detected from its bytes, never from the client's file name or content type.
"""

import hashlib
import io
import json
import os
import struct
import threading
import time
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, NamedTuple

import redis
from boto3.exceptions import Boto3Error
from botocore.exceptions import BotoCoreError, ClientError, ReadTimeoutError
from redis.exceptions import RedisError

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

from temba.utils.s3 import S3_UPLOAD_CONNECT_TIMEOUT_SECONDS, S3_UPLOAD_READ_TIMEOUT_SECONDS, media_upload_storage

MIB = 1024 * 1024
KIB = 1024

MAX_BROADCAST_FILES = 10
MAX_BROADCAST_FILES_TOTAL_BYTES = 100 * MIB

MAX_IMAGE_BYTES = 5 * MIB
MAX_STICKER_BYTES = 500 * KIB
MAX_VIDEO_BYTES = 16 * MIB
MAX_AUDIO_BYTES = 16 * MIB
MAX_DOCUMENT_BYTES = 100 * MIB

# how much of each file is given to libmagic
MEDIA_SNIFF_BYTES = 256 * KIB

# how many boxes of one level of an MP4 file are looked at when telling audio from video
MP4_MAX_BOXES_PER_LEVEL = 64


class AllowedMedia(NamedTuple):
    category: str
    extension: str
    max_bytes: int


_OFFICE = "application/vnd.openxmlformats-officedocument"

ALLOWED_BROADCAST_MEDIA: dict[str, AllowedMedia] = {
    "image/jpeg": AllowedMedia("image", "jpg", MAX_IMAGE_BYTES),
    "image/png": AllowedMedia("image", "png", MAX_IMAGE_BYTES),
    "image/webp": AllowedMedia("sticker", "webp", MAX_STICKER_BYTES),
    "video/mp4": AllowedMedia("video", "mp4", MAX_VIDEO_BYTES),
    "video/3gpp": AllowedMedia("video", "3gp", MAX_VIDEO_BYTES),
    "audio/aac": AllowedMedia("audio", "aac", MAX_AUDIO_BYTES),
    "audio/amr": AllowedMedia("audio", "amr", MAX_AUDIO_BYTES),
    "audio/mpeg": AllowedMedia("audio", "mp3", MAX_AUDIO_BYTES),
    "audio/mp4": AllowedMedia("audio", "m4a", MAX_AUDIO_BYTES),
    "audio/ogg": AllowedMedia("audio", "ogg", MAX_AUDIO_BYTES),
    "text/plain": AllowedMedia("document", "txt", MAX_DOCUMENT_BYTES),
    "application/pdf": AllowedMedia("document", "pdf", MAX_DOCUMENT_BYTES),
    "application/msword": AllowedMedia("document", "doc", MAX_DOCUMENT_BYTES),
    "application/vnd.ms-excel": AllowedMedia("document", "xls", MAX_DOCUMENT_BYTES),
    "application/vnd.ms-powerpoint": AllowedMedia("document", "ppt", MAX_DOCUMENT_BYTES),
    f"{_OFFICE}.wordprocessingml.document": AllowedMedia("document", "docx", MAX_DOCUMENT_BYTES),
    f"{_OFFICE}.spreadsheetml.sheet": AllowedMedia("document", "xlsx", MAX_DOCUMENT_BYTES),
    f"{_OFFICE}.presentationml.presentation": AllowedMedia("document", "pptx", MAX_DOCUMENT_BYTES),
}

# types libmagic reports under another name than the one WhatsApp and Courier use
LIBMAGIC_MIME_ALIASES = {
    "audio/x-m4a": "audio/mp4",
    "audio/x-hx-aac-adts": "audio/aac",
}


# what libmagic reports for ISO BMFF files that are checked for having no video
ISO_BMFF_VIDEO_TYPES = {"video/mp4", "video/3gpp"}

# Older libmagic builds (e.g. the ones shipped by Debian bookworm and Ubuntu) don't always recognize Office Open XML
# files and report them as one of these. Such files are opened as ZIP archives to find out which document they are.
OOXML_UNRECOGNIZED_TYPES = {"application/zip", "application/octet-stream"}
ZIP_LOCAL_FILE_SIGNATURE = b"PK\x03\x04"
OOXML_CONTENT_TYPES_PART = "[Content_Types].xml"
OOXML_PART_PREFIXES = (
    ("word/", f"{_OFFICE}.wordprocessingml.document"),
    ("xl/", f"{_OFFICE}.spreadsheetml.sheet"),
    ("ppt/", f"{_OFFICE}.presentationml.presentation"),
)


def _mp4_boxes(file, start: int, end: int) -> Iterator[tuple[bytes, int, int]]:
    """
    Yields (type, body start, body end) of the ISO BMFF boxes between two offsets, reading nothing but their headers.
    It stops at the first malformed box and after MP4_MAX_BOXES_PER_LEVEL boxes.
    """
    offset = start
    for _ in range(MP4_MAX_BOXES_PER_LEVEL):
        file.seek(offset)
        header = file.read(8)
        if len(header) < 8:
            return

        size, box_type = struct.unpack(">I4s", header)
        header_size = 8
        if size == 1:  # the real size follows as 64 bits
            large_size = file.read(8)
            if len(large_size) < 8:
                return
            size, header_size = struct.unpack(">Q", large_size)[0], 16
        elif size == 0:  # the box runs to the end
            size = end - offset

        if size < header_size or offset + size > end:
            return

        yield box_type, offset + header_size, offset + size
        offset += size


def _mp4_child(file, start: int, end: int, box_type: bytes) -> tuple[int, int] | None:
    for child_type, child_start, child_end in _mp4_boxes(file, start, end):
        if child_type == box_type:
            return child_start, child_end
    return None


def _mp4_track_handler(file, start: int, end: int) -> bytes | None:
    """
    Returns the handler type of a track (e.g. b"vide" or b"soun"), or None if it can't be read
    """
    mdia = _mp4_child(file, start, end, b"mdia")
    hdlr = mdia and _mp4_child(file, *mdia, b"hdlr")
    if not hdlr or hdlr[1] - hdlr[0] < 12:
        return None

    file.seek(hdlr[0] + 8)  # after version, flags and pre_defined
    handler = file.read(4)
    return handler if len(handler) == 4 else None


def _is_audio_only_mp4(file) -> bool:
    """
    Whether an ISO BMFF file has tracks and none of them is video. Anything that can't be read to the end, or that goes
    past MP4_MAX_BOXES_PER_LEVEL boxes in a level, is not considered audio only.
    """
    file.seek(0, os.SEEK_END)
    file_end = file.tell()

    moov = _mp4_child(file, 0, file_end, b"moov")
    if not moov:
        return False

    handlers = []
    for box_type, start, end in _mp4_boxes(file, *moov):
        if box_type == b"trak":
            handler = _mp4_track_handler(file, start, end)
            if handler is None:
                return False
            handlers.append(handler)

    return bool(handlers) and b"vide" not in handlers


def _ooxml_type(archive_file) -> str | None:
    """
    Returns the Office Open XML type of a ZIP archive from the names of its parts, or None if it isn't one.
    Only the central directory is read, never the contents of the parts.
    """
    try:
        with zipfile.ZipFile(archive_file) as archive:
            names = archive.namelist()
    except (zipfile.BadZipFile, OSError, ValueError, EOFError):
        return None

    if OOXML_CONTENT_TYPES_PART not in names:
        return None

    for prefix, mime in OOXML_PART_PREFIXES:
        if any(name.startswith(prefix) for name in names):
            return mime
    return None


def detect_media_type(head: bytes, file=None) -> str:
    """
    Detects the type of a file from its first MEDIA_SNIFF_BYTES, returning a normalized mime type. The result is not
    necessarily one of ALLOWED_BROADCAST_MEDIA, so callers must check it.

    libmagic reports every ISO BMFF file with a video brand as a video, even if it only has audio. When the file is
    given and libmagic reports MP4 or 3GPP video, its track headers (which are usually past the bytes in head) are read
    to find out whether it has any video track, and it is audio/mp4 if not.

    Older libmagic builds report some Office Open XML files as a plain ZIP or as unknown data. When the bytes start a
    ZIP archive, its part names are read (from the file when given, since the ZIP directory is at the end of it) to
    find out whether it is a Word, Excel or PowerPoint document. The file position is left at the start.
    """
    import magic  # imported here so that machines without libmagic can still load Django and run unrelated tests

    # libmagic is not consistent about case, e.g. "audio/AMR"
    mime = magic.from_buffer(head, mime=True).lower()
    mime = LIBMAGIC_MIME_ALIASES.get(mime, mime)

    if file is not None and mime in ISO_BMFF_VIDEO_TYPES:
        try:
            if _is_audio_only_mp4(file):
                mime = "audio/mp4"
        finally:
            file.seek(0)

    if mime in OOXML_UNRECOGNIZED_TYPES and head.startswith(ZIP_LOCAL_FILE_SIGNATURE):
        if file is None:
            mime = _ooxml_type(io.BytesIO(head)) or mime
        else:
            try:
                mime = _ooxml_type(file) or mime
            finally:
                file.seek(0)

    return mime


MULTIPART_CONTENT_TYPE = "multipart/form-data"
PAYLOAD_FIELD = "payload"
FILES_FIELD = "files"

# longest name of an unexpected form field that is repeated back to the caller
MAX_REPORTED_FIELD_NAME_LENGTH = 64


class BroadcastMediaInvalid(Exception):
    """
    The multipart request is invalid. The errors are keyed by "payload" (a list of messages, or the nested errors of a
    field of it) and "files" (a dict of messages by the zero-based position of the file, as a string).
    """

    def __init__(self, errors: dict):
        self.errors = errors
        super().__init__("Invalid broadcast request")


@dataclass
class InlineMedia:
    """
    A file received in the files field of a multipart request
    """

    position: int
    file: UploadedFile = field(repr=False)  # never logged: its name comes from the client
    size: int
    sha256: str
    mime: str

    @property
    def extension(self) -> str:
        return ALLOWED_BROADCAST_MEDIA[self.mime].extension

    def key(self, org_id: int) -> str:
        return f"attachments/{org_id}/broadcasts/{self.sha256}.{self.extension}"

    def attachment(self, org_id: int) -> str:
        """
        The canonical, unsigned attachment of the file. Courier signs it right before each send.
        """
        return f"{self.mime}:{settings.STORAGE_URL}/{self.key(org_id)}"


@dataclass
class PreparedBroadcastRequest:
    is_multipart: bool
    payload: Any  # the JSON body untouched, or the parsed payload field
    media: list[InlineMedia] = field(default_factory=list)

    @property
    def file_sha256s(self) -> list[str]:
        return [m.sha256 for m in self.media]

    def with_attachments(self, org) -> Any:
        """
        Returns the payload with the canonical attachment of each file added at the end of msg.attachments, in order. It
        is returned as it is when there are no files or no msg object, for the serializer to report as for JSON.
        """
        msg = self.payload.get("msg") if isinstance(self.payload, dict) else None
        if not self.media or not isinstance(msg, dict):
            return self.payload

        existing = msg.get("attachments", [])
        if not isinstance(existing, list):
            raise BroadcastMediaInvalid({PAYLOAD_FIELD: {"msg": {"attachments": ["Expected a list of items."]}}})

        attachments = [*existing, *(m.attachment(org.id) for m in self.media)]
        return {**self.payload, "msg": {**msg, "attachments": attachments}}


def _reject_json_constant(name: str):
    raise ValueError(f"{name} is not valid JSON")


def _parse_payload(text: str, errors: list[str]) -> dict | None:
    try:
        payload = json.loads(text, parse_constant=_reject_json_constant)
    except (ValueError, RecursionError):
        errors.append("Payload must be valid JSON.")
        return None

    if not isinstance(payload, dict):
        errors.append("Payload must be a JSON object.")
        return None

    return payload


def _unexpected_field_error(name: str) -> str:
    if len(name) > MAX_REPORTED_FIELD_NAME_LENGTH:
        name = name[:MAX_REPORTED_FIELD_NAME_LENGTH] + "…"
    return f"Unexpected field '{name}'. Only '{PAYLOAD_FIELD}' and '{FILES_FIELD}' are accepted."


def _hash_and_sniff(file: UploadedFile) -> tuple[str, bytes]:
    """
    Reads the file once, returning its SHA-256 and the first MEDIA_SNIFF_BYTES for type detection
    """
    digest = hashlib.sha256()
    head = bytearray()
    for chunk in file.chunks():
        digest.update(chunk)
        if len(head) < MEDIA_SNIFF_BYTES:
            head += chunk[: MEDIA_SNIFF_BYTES - len(head)]

    file.seek(0)
    return digest.hexdigest(), bytes(head)


def _check_file_counts(uploads: list[UploadedFile], file_errors: dict[str, list[str]]):
    """
    Cheap checks on the number and declared size of the files, so a request over the limits is rejected without
    reading any file. Every file past the maximum is reported, and the one that takes the total over its limit.
    """
    for position in range(MAX_BROADCAST_FILES, len(uploads)):
        file_errors.setdefault(str(position), []).append(f"At most {MAX_BROADCAST_FILES} files can be sent.")

    total = 0
    for position, upload in enumerate(uploads):
        total += upload.size
        if total > MAX_BROADCAST_FILES_TOTAL_BYTES:
            message = f"The files add up to more than {_format_size(MAX_BROADCAST_FILES_TOTAL_BYTES)}."
            file_errors.setdefault(str(position), []).append(message)
            break


def _read_file(position: int, upload: UploadedFile) -> tuple[InlineMedia | None, str | None]:
    if upload.size == 0:
        return None, "The submitted file is empty."

    sha256, head = _hash_and_sniff(upload)
    mime = detect_media_type(head, upload)
    if mime not in ALLOWED_BROADCAST_MEDIA:
        return None, f"Unsupported file type: {mime}."

    error = media_size_error(mime, upload.size)
    if error:
        return None, error

    return InlineMedia(position=position, file=upload, size=upload.size, sha256=sha256, mime=mime), None


def read_broadcast_request(content_type: str, fields, files) -> PreparedBroadcastRequest:
    """
    Reads and validates a broadcast request before anything is stored. Anything but multipart/form-data is a JSON (or
    form) body and is returned untouched. A multipart request must have exactly one payload field with a JSON object
    and up to MAX_BROADCAST_FILES files in its files field. Every error found is raised together as
    BroadcastMediaInvalid.

    The checks run from the cheapest, so a request with too many or too large files is not read file by file.
    """
    if not (content_type or "").lower().startswith(MULTIPART_CONTENT_TYPE):
        return PreparedBroadcastRequest(is_multipart=False, payload=fields)

    payload_errors: list[str] = []
    file_errors: dict[str, list[str]] = {}

    payload_values = fields.getlist(PAYLOAD_FIELD)
    payload = None
    if len(payload_values) > 1:
        payload_errors.append("Only one payload field is accepted.")
    elif payload_values:
        payload = _parse_payload(payload_values[0], payload_errors)
    elif PAYLOAD_FIELD not in files:
        payload_errors.append("This field is required.")

    for name in fields:
        if name == FILES_FIELD:
            payload_errors.append(f"The '{FILES_FIELD}' field must contain files.")
        elif name != PAYLOAD_FIELD:
            payload_errors.append(_unexpected_field_error(name))
    for name in files:
        if name == PAYLOAD_FIELD:
            payload_errors.append("Payload must be a text field, not a file.")
        elif name != FILES_FIELD:
            payload_errors.append(_unexpected_field_error(name))

    uploads = files.getlist(FILES_FIELD)
    media: list[InlineMedia] = []

    _check_file_counts(uploads, file_errors)
    if not file_errors:
        for position, upload in enumerate(uploads):
            item, error = _read_file(position, upload)
            if item:
                media.append(item)
            else:
                file_errors[str(position)] = [error]

    errors = {}
    if payload_errors:
        errors[PAYLOAD_FIELD] = payload_errors
    if file_errors:
        errors[FILES_FIELD] = file_errors
    if errors:
        raise BroadcastMediaInvalid(errors)

    return PreparedBroadcastRequest(is_multipart=True, payload=payload, media=media)


BROADCAST_MEDIA_DEDUP_TTL_SECONDS = 7 * 24 * 60 * 60
BROADCAST_MEDIA_DEDUP_KEY_PREFIX = "broadcast_media"
BROADCAST_MEDIA_REDIS_TIMEOUT_SECONDS = 2

# gunicorn's worker timeout: a request still running after this is killed
BROADCAST_MEDIA_WORKER_TIMEOUT_SECONDS = 120

# how long one save() may keep starting new HTTP calls, see store_broadcast_media
S3_UPLOAD_CALL_BUDGET_SECONDS = 60

# where in the botocore client events the call budget is enforced, i.e. before each request to S3 is sent
BEFORE_SEND_EVENT = "before-send.s3"


class BroadcastMediaUnavailable(Exception):
    """
    The media storage (S3 or the deduplication cache) failed. The stage is one of "dedup_lookup", "upload" and
    "dedup_record". The error that caused it is kept as __cause__, and its message may contain a URL or an object key,
    so it must not be reported as it is.
    """

    def __init__(self, stage: str):
        self.stage = stage
        super().__init__(f"Media storage unavailable at {stage}")


def _now() -> float:
    return time.monotonic()


@lru_cache(maxsize=None)
def _dedup_redis() -> redis.Redis:
    """
    The client of the deduplication cache, created once per process. It is the same Redis as the default cache but
    with timeouts, which that one doesn't have, and it never retries.
    """
    return redis.Redis.from_url(
        settings.CACHES["default"]["LOCATION"],
        socket_timeout=BROADCAST_MEDIA_REDIS_TIMEOUT_SECONDS,
        socket_connect_timeout=BROADCAST_MEDIA_REDIS_TIMEOUT_SECONDS,
    )


def _dedup_key(org_id: int, sha256: str) -> str:
    return f"{BROADCAST_MEDIA_DEDUP_KEY_PREFIX}:{org_id}:{sha256}"


def _abort_when_set(budget_spent: threading.Event):
    """
    A botocore before-send handler that refuses to send any more requests once the call budget is spent
    """

    def handler(request, **kwargs):
        if budget_spent.is_set():
            # a generic endpoint: the real URL has the object key
            raise ReadTimeoutError(endpoint_url="S3")

    return handler


def _botocore_events(storage):
    """
    The event system of the botocore client the storage uploads with, or None for storages that have none
    """
    connection = getattr(storage, "connection", None)
    client = getattr(getattr(connection, "meta", None), "client", None)
    return getattr(getattr(client, "meta", None), "events", None)


def _upload(storage, org_id: int, media: InlineMedia):
    """
    Saves one file, on this thread, so the temporary file it is read from outlives the call.

    A timer sets an event after S3_UPLOAD_CALL_BUDGET_SECONDS, and a before-send handler makes the next request to S3
    fail once it is set. That stops a save() that goes on making calls (a multipart upload, retries), but it can't stop
    an attempt that is already on the wire, which ends at the connect and read timeouts. The storage and its client are
    shared by every request in the process, so the handler is always taken off again, and the timer cancelled.
    """
    budget_spent = threading.Event()
    timer = threading.Timer(S3_UPLOAD_CALL_BUDGET_SECONDS, budget_spent.set)
    timer.daemon = True
    events = handler = None

    try:
        timer.start()

        events = _botocore_events(storage)
        if events is not None:
            handler = _abort_when_set(budget_spent)
            events.register(BEFORE_SEND_EVENT, handler)

        media.file.content_type = media.mime
        storage.save(media.key(org_id), media.file)  # the name it returns is not needed, the key is known
    except (BotoCoreError, ClientError, Boto3Error, OSError) as e:
        raise BroadcastMediaUnavailable("upload") from e
    finally:
        timer.cancel()
        if handler is not None:
            events.unregister(BEFORE_SEND_EVENT, handler)


def store_broadcast_media(org, media: list[InlineMedia]):
    """
    Stores the files that aren't stored yet for the org, once per distinct content and one after the other.

    A shared cache entry per org and SHA-256 says that the file was already stored. The object is uploaded when there is
    no entry, or the entry isn't the attachment of this request, and the entry is recorded after it. Objects are never
    deleted and their keys are their content, so storing one twice is harmless.

    No upload is started that could, in the worst case, still be running when the worker is killed. Raises
    BroadcastMediaUnavailable on the first failure, without trying the rest.
    """
    started = _now()
    storage = media_upload_storage()
    cache = _dedup_redis()
    done = set()

    # the time one upload can take at most: the call budget, plus the attempt that is on the wire when it ends
    worst_case = S3_UPLOAD_CALL_BUDGET_SECONDS + S3_UPLOAD_CONNECT_TIMEOUT_SECONDS + S3_UPLOAD_READ_TIMEOUT_SECONDS

    for item in media:
        if item.sha256 in done:
            continue
        done.add(item.sha256)

        key = _dedup_key(org.id, item.sha256)
        attachment = item.attachment(org.id)

        try:
            stored = cache.get(key)
        except RedisError as e:
            raise BroadcastMediaUnavailable("dedup_lookup") from e

        if stored is not None and stored.decode() == attachment:
            continue

        if (_now() - started) + worst_case >= BROADCAST_MEDIA_WORKER_TIMEOUT_SECONDS:
            raise BroadcastMediaUnavailable("upload")

        _upload(storage, org.id, item)

        try:
            cache.set(key, attachment, ex=BROADCAST_MEDIA_DEDUP_TTL_SECONDS)
        except RedisError as e:
            raise BroadcastMediaUnavailable("dedup_record") from e


def _format_size(size: int) -> str:
    if size % MIB == 0:
        return f"{size // MIB} MiB"
    if size % KIB == 0:
        return f"{size // KIB} KiB"
    return f"{size} bytes"


def media_size_error(mime: str, size: int) -> str | None:
    """
    Returns an error message if a file of the given size exceeds the limit of its (allowed) type's category
    """
    limit = ALLOWED_BROADCAST_MEDIA[mime].max_bytes
    if size > limit:
        return f"File is too large for {mime}: the limit is {_format_size(limit)}."
    return None
