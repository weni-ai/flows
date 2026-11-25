import hashlib
import io
import json
import struct
import threading
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import ClientError, ConnectTimeoutError, ReadTimeoutError
from django_redis import get_redis_connection
from redis.exceptions import ConnectionError as RedisConnectionError, RedisError, TimeoutError as RedisTimeoutError

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import QueryDict
from django.utils.datastructures import MultiValueDict

from temba.msgs.usecases.broadcast_media import (
    ALLOWED_BROADCAST_MEDIA,
    BROADCAST_MEDIA_DEDUP_KEY_PREFIX,
    BROADCAST_MEDIA_DEDUP_TTL_SECONDS,
    BROADCAST_MEDIA_REDIS_TIMEOUT_SECONDS,
    BROADCAST_MEDIA_WORKER_TIMEOUT_SECONDS,
    LIBMAGIC_MIME_ALIASES,
    MAX_AUDIO_BYTES,
    MAX_BROADCAST_FILES,
    MAX_BROADCAST_FILES_TOTAL_BYTES,
    MAX_DOCUMENT_BYTES,
    MAX_IMAGE_BYTES,
    MAX_STICKER_BYTES,
    MAX_VIDEO_BYTES,
    MEDIA_SNIFF_BYTES,
    MP4_MAX_BOXES_PER_LEVEL,
    S3_UPLOAD_CALL_BUDGET_SECONDS,
    AllowedMedia,
    BroadcastMediaInvalid,
    BroadcastMediaUnavailable,
    InlineMedia,
    PreparedBroadcastRequest,
    _dedup_redis,
    detect_media_type,
    media_size_error,
    read_broadcast_request,
    store_broadcast_media,
)
from temba.tests import TembaTest
from temba.tests.media import audio_only_mp4_bytes, mp4_box, split_mp4_boxes
from temba.utils.s3 import S3_UPLOAD_CONNECT_TIMEOUT_SECONDS, S3_UPLOAD_READ_TIMEOUT_SECONDS, private_file_storage

MIB = 1024 * 1024


def fixture_bytes(name: str, folder: str = "test_media") -> bytes:
    with open(f"{settings.MEDIA_ROOT}/{folder}/{name}", "rb") as f:
        return f.read()


def ftyp(brand: bytes) -> bytes:
    return mp4_box(b"ftyp", brand + b"\x00\x00\x00\x00" + brand + b"isom")


def zip_with(*names: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, "x")
    return buffer.getvalue()


# minimal headers libmagic recognizes, one per allowed type that has no fixture
PNG = (
    b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0) + b"\x00" * 4
)
WEBP = b"RIFF" + struct.pack("<I", 20) + b"WEBPVP8 " + b"\x00" * 16
AAC = b"\xff\xf1\x50\x80\x01\x3f\xfc" + b"\x00" * 200
AMR = b"#!AMR\n" + b"\x3c" * 40
MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" + b"\x00" * 400
OGG = b"OggS\x00\x02" + b"\x00" * 20 + b"\x01\x1e\x01vorbis" + b"\x00" * 40
TEXT = b"hello world\n"
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n"
DOCX = zip_with("[Content_Types].xml", "_rels/.rels", "word/document.xml")
XLSX = zip_with("[Content_Types].xml", "_rels/.rels", "xl/workbook.xml")
PPTX = zip_with("[Content_Types].xml", "_rels/.rels", "ppt/presentation.xml")
GIF = b"GIF89a\x01\x00\x01\x00\x00\x00\x00;"
HTML = b"<!DOCTYPE html><html><body>hello</body></html>"


class DetectMediaTypeTest(TembaTest):
    def test_allowed_types_from_bytes(self):
        cases = [
            (fixture_bytes("steve.marten.jpg"), "image/jpeg"),
            (PNG, "image/png"),
            (WEBP, "image/webp"),
            (fixture_bytes("snow.mp4"), "video/mp4"),
            (ftyp(b"3gp4"), "video/3gpp"),
            (AAC, "audio/aac"),
            (AMR, "audio/amr"),
            (MP3, "audio/mpeg"),
            (ftyp(b"M4A "), "audio/mp4"),
            (OGG, "audio/ogg"),
            (TEXT, "text/plain"),
            (PDF, "application/pdf"),
            (fixture_bytes("simple.xls", folder="test_imports"), "application/vnd.ms-excel"),
            (
                DOCX,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            (XLSX, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            (
                PPTX,
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ),
        ]
        for head, expected in cases:
            with self.subTest(expected):
                detected = detect_media_type(head)
                self.assertEqual(expected, detected)
                self.assertIn(detected, ALLOWED_BROADCAST_MEDIA)

    def test_legacy_word_and_powerpoint(self):
        # libmagic needs real OLE2 streams to tell these apart, so only the table is exercised here
        for mime in ("application/msword", "application/vnd.ms-powerpoint"):
            with self.subTest(mime), patch("magic.from_buffer", return_value=mime):
                self.assertEqual(mime, detect_media_type(b"ole2"))
                self.assertIn(mime, ALLOWED_BROADCAST_MEDIA)

    def test_every_allowed_type_is_covered(self):
        self.assertEqual(
            {
                "image/jpeg",
                "image/png",
                "image/webp",
                "video/mp4",
                "video/3gpp",
                "audio/aac",
                "audio/amr",
                "audio/mpeg",
                "audio/mp4",
                "audio/ogg",
                "text/plain",
                "application/pdf",
                "application/msword",
                "application/vnd.ms-excel",
                "application/vnd.ms-powerpoint",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            },
            set(ALLOWED_BROADCAST_MEDIA),
        )

    def test_aliases(self):
        self.assertEqual(
            {"audio/x-m4a": "audio/mp4", "audio/x-hx-aac-adts": "audio/aac"},
            LIBMAGIC_MIME_ALIASES,
        )

        for alias, mime in LIBMAGIC_MIME_ALIASES.items():
            with self.subTest(alias), patch("magic.from_buffer", return_value=alias):
                self.assertEqual(mime, detect_media_type(b"anything"))

        # libmagic is not consistent about case, e.g. "audio/AMR"
        with patch("magic.from_buffer", return_value="Audio/AMR"):
            self.assertEqual("audio/amr", detect_media_type(b"anything"))

    def test_rejected_types(self):
        for name, head in (
            ("gif", GIF),
            ("html", HTML),
            ("wav", fixture_bytes("allo.wav")),
            ("unknown", b"\x00\x01\x02\x03" * 64),
            ("empty", b""),
        ):
            with self.subTest(name):
                self.assertNotIn(detect_media_type(head), ALLOWED_BROADCAST_MEDIA)

    def test_type_comes_from_bytes_not_from_the_client(self):
        upload = SimpleUploadedFile("photo.bin", fixture_bytes("steve.marten.jpg"), "application/octet-stream")
        mime = detect_media_type(upload.read(MEDIA_SNIFF_BYTES))

        self.assertEqual("image/jpeg", mime)
        self.assertEqual("jpg", ALLOWED_BROADCAST_MEDIA[mime].extension)

        # a name that claims another type changes nothing
        upload = SimpleUploadedFile("report.pdf", fixture_bytes("steve.marten.jpg"), "application/pdf")
        mime = detect_media_type(upload.read(MEDIA_SNIFF_BYTES))

        self.assertEqual("image/jpeg", mime)
        self.assertEqual("jpg", ALLOWED_BROADCAST_MEDIA[mime].extension)

    def test_extensions(self):
        self.assertEqual(
            {
                "image/jpeg": "jpg",
                "image/png": "png",
                "image/webp": "webp",
                "video/mp4": "mp4",
                "video/3gpp": "3gp",
                "audio/aac": "aac",
                "audio/amr": "amr",
                "audio/mpeg": "mp3",
                "audio/mp4": "m4a",
                "audio/ogg": "ogg",
                "text/plain": "txt",
                "application/pdf": "pdf",
                "application/msword": "doc",
                "application/vnd.ms-excel": "xls",
                "application/vnd.ms-powerpoint": "ppt",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
            },
            {mime: media.extension for mime, media in ALLOWED_BROADCAST_MEDIA.items()},
        )


class CountingFile(io.BytesIO):
    """A file that counts how many bytes are read from it"""

    bytes_read = 0

    def read(self, size=-1):
        data = super().read(size)
        self.bytes_read += len(data)
        return data


class AudioOnlyMp4Test(TembaTest):
    def detect(self, data: bytes, file=None) -> str:
        return detect_media_type(data[:MEDIA_SNIFF_BYTES], file or SimpleUploadedFile("f", data))

    def test_audio_only_is_audio(self):
        # snow.m4a is a copy of snow.mp4 and still has a video track, so this is the same file without it
        data = audio_only_mp4_bytes()

        # libmagic alone calls it a video, and its moov box is past the bytes it is given
        self.assertEqual("video/mp4", detect_media_type(data[:MEDIA_SNIFF_BYTES]))
        self.assertGreater(len(data), MEDIA_SNIFF_BYTES)

        self.assertEqual("audio/mp4", self.detect(data))

    def test_video_stays_video(self):
        for name in ("snow.mp4", "snow.m4a"):
            with self.subTest(name):
                self.assertEqual("video/mp4", self.detect(fixture_bytes(name)))

    def test_mdat_after_moov(self):
        data = audio_only_mp4_bytes()
        boxes = split_mp4_boxes(data)
        by_type = dict(boxes)
        reordered = b"".join(mp4_box(t, by_type[t]) for t in (b"ftyp", b"moov", b"free", b"mdat"))

        self.assertEqual("audio/mp4", self.detect(reordered))

    def test_only_headers_are_read(self):
        data = audio_only_mp4_bytes()
        file = CountingFile(data)

        self.assertEqual("audio/mp4", self.detect(data, file))

        # the 680 KB of media data is skipped over
        self.assertLess(file.bytes_read, 2048)

    def test_box_limit_per_level(self):
        data = audio_only_mp4_bytes()
        by_type = dict(split_mp4_boxes(data))
        filler = mp4_box(b"free", b"")
        self.assertEqual(64, MP4_MAX_BOXES_PER_LEVEL)

        def with_moov_at(position: int) -> bytes:
            # the ftyp box is first, then fillers, so that moov is the box at the given 1-based position
            boxes = (
                [mp4_box(b"ftyp", by_type[b"ftyp"])] + [filler] * (position - 2) + [mp4_box(b"moov", by_type[b"moov"])]
            )
            return b"".join(boxes)

        # moov is the last box that is looked at
        self.assertEqual("audio/mp4", self.detect(with_moov_at(MP4_MAX_BOXES_PER_LEVEL)))

        # one box further and the walk has already stopped, which leaves libmagic's type as it is
        self.assertEqual("video/mp4", self.detect(with_moov_at(MP4_MAX_BOXES_PER_LEVEL + 1)))

    def test_track_limit_per_level(self):
        data = audio_only_mp4_bytes()
        by_type = dict(split_mp4_boxes(data))
        moov = dict(split_mp4_boxes(by_type[b"moov"]))
        filler = mp4_box(b"free", b"")
        audio_trak = mp4_box(b"trak", moov[b"trak"])

        def with_trak_after(fillers: int) -> bytes:
            children = mp4_box(b"mvhd", moov[b"mvhd"]) + filler * fillers + audio_trak
            return mp4_box(b"ftyp", by_type[b"ftyp"]) + mp4_box(b"moov", children)

        self.assertEqual("audio/mp4", self.detect(with_trak_after(MP4_MAX_BOXES_PER_LEVEL - 2)))
        self.assertEqual("video/mp4", self.detect(with_trak_after(MP4_MAX_BOXES_PER_LEVEL - 1)))

    def test_malformed_files_keep_libmagic_type(self):
        data = audio_only_mp4_bytes()
        head = mp4_box(b"ftyp", dict(split_mp4_boxes(data))[b"ftyp"])

        for name, broken in (
            ("truncated moov", data[:-100]),
            ("no moov", b"".join(mp4_box(t, b) for t, b in split_mp4_boxes(data) if t != b"moov")),
            ("box larger than file", head + struct.pack(">I4s", 2**31, b"moov") + b"\x00" * 64),
            ("box smaller than its header", head + struct.pack(">I4s", 4, b"moov") + b"\x00" * 64),
            ("64-bit size cut short", head + struct.pack(">I4s", 1, b"moov") + b"\x00" * 4),
            ("no tracks", head + mp4_box(b"moov", mp4_box(b"mvhd", b"\x00" * 100))),
            ("track without handler", head + mp4_box(b"moov", mp4_box(b"trak", mp4_box(b"mdia", b"")))),
        ):
            with self.subTest(name):
                self.assertEqual("video/mp4", self.detect(broken))

    def test_large_box_sizes(self):
        data = audio_only_mp4_bytes()
        by_type = dict(split_mp4_boxes(data))

        # a 64-bit size (size field 1 followed by the real size) and a box that runs to the end of the file (size 0)
        moov_body = by_type[b"moov"]
        moov_64 = struct.pack(">I4sQ", 1, b"moov", 16 + len(moov_body)) + moov_body
        self.assertEqual("audio/mp4", self.detect(mp4_box(b"ftyp", by_type[b"ftyp"]) + moov_64))

        moov_to_end = struct.pack(">I4s", 0, b"moov") + moov_body
        self.assertEqual("audio/mp4", self.detect(mp4_box(b"ftyp", by_type[b"ftyp"]) + moov_to_end))

    def test_other_types_are_left_alone(self):
        # the walk only applies to what libmagic reports as MP4 or 3GPP video
        self.assertEqual("image/jpeg", self.detect(fixture_bytes("steve.marten.jpg")))
        self.assertEqual("audio/mp4", self.detect(ftyp(b"M4A ")))

    def test_3gpp_without_video(self):
        data = audio_only_mp4_bytes()
        by_type = dict(split_mp4_boxes(data))
        three_gp = ftyp(b"3gp4") + mp4_box(b"moov", by_type[b"moov"])

        self.assertEqual("video/3gpp", detect_media_type(three_gp))
        self.assertEqual("audio/mp4", self.detect(three_gp))


def multipart(payloads=(), files=(), fields=None, file_fields=None):
    """
    Builds the form fields and files of a multipart request: payloads are the values of its payload fields, files the
    ones of its files fields, and fields and file_fields add others under the given names.
    """
    form = QueryDict(mutable=True)
    for payload in payloads:
        form.appendlist("payload", payload)
    for name, value in (fields or {}).items():
        form.appendlist(name, value)

    uploads = MultiValueDict()
    for upload in files:
        uploads.appendlist("files", upload)
    for name, upload in (file_fields or {}).items():
        uploads.appendlist(name, upload)

    return form, uploads


def upload(data: bytes, name: str = "file.bin", content_type: str = "application/octet-stream"):
    return SimpleUploadedFile(name, data, content_type)


class ReadBroadcastRequestTest(TembaTest):
    PAYLOAD = {"groups": ["g1"], "msg": {"text": "Hi", "attachments": ["image/png:https://example.com/a.png"]}}

    def read(self, payloads=None, files=(), **kwargs) -> PreparedBroadcastRequest:
        payloads = [json.dumps(self.PAYLOAD)] if payloads is None else payloads
        form, uploads = multipart(payloads, files, **kwargs)
        return read_broadcast_request("multipart/form-data; boundary=x", form, uploads)

    def assertInvalid(self, expected: dict, *args, **kwargs):
        with self.assertRaises(BroadcastMediaInvalid) as cm:
            self.read(*args, **kwargs)
        self.assertEqual(expected, cm.exception.errors)

    def test_json_is_passed_through(self):
        for content_type in ("application/json", "application/x-www-form-urlencoded", "text/plain", ""):
            with self.subTest(content_type):
                data = {"groups": ["g1"], "msg": {"text": "Hi"}}
                prepared = read_broadcast_request(content_type, data, None)

                self.assertFalse(prepared.is_multipart)
                self.assertIs(data, prepared.payload)
                self.assertEqual([], prepared.media)
                self.assertEqual([], prepared.file_sha256s)

                # nothing is added to the payload
                self.assertEqual(data, prepared.with_attachments(self.org))

    def test_multipart_without_files(self):
        prepared = self.read()

        self.assertTrue(prepared.is_multipart)
        self.assertEqual(self.PAYLOAD, prepared.payload)
        self.assertEqual([], prepared.media)
        self.assertEqual(self.PAYLOAD, prepared.with_attachments(self.org))

    def test_payload_errors(self):
        cases = [
            ("missing", [], "This field is required."),
            ("duplicated", ["{}", "{}"], "Only one payload field is accepted."),
            ("not json", ["{not json"], "Payload must be valid JSON."),
            ("empty", [""], "Payload must be valid JSON."),
            ("nan", ['{"a": NaN}'], "Payload must be valid JSON."),
            ("array", ['[{"msg": {}}]'], "Payload must be a JSON object."),
            ("string", ['"text"'], "Payload must be a JSON object."),
            ("null", ["null"], "Payload must be a JSON object."),
            ("number", ["1"], "Payload must be a JSON object."),
        ]
        for name, payloads, message in cases:
            with self.subTest(name):
                self.assertInvalid({"payload": [message]}, payloads)

    def test_unknown_fields(self):
        message = "Unexpected field {}. Only 'payload' and 'files' are accepted."

        self.assertInvalid({"payload": [message.format("'extra'")]}, fields={"extra": "x"})

        # a file under another name, such as the singular
        jpeg = upload(fixture_bytes("steve.marten.jpg"))
        self.assertInvalid({"payload": [message.format("'file'")]}, files=[jpeg], file_fields={"file": jpeg})

        # a long name is cut
        self.assertInvalid({"payload": [message.format("'" + "x" * 64 + "…'")]}, fields={"x" * 100: "x"})

    def test_fields_of_the_wrong_kind(self):
        jpeg = upload(fixture_bytes("steve.marten.jpg"))

        # files given as text, e.g. -F files=photo.jpg without the @
        self.assertInvalid({"payload": ["The 'files' field must contain files."]}, fields={"files": "photo.jpg"})

        # a payload that is a file, which is not accepted and is not reported as missing as well
        self.assertInvalid(
            {"payload": ["Payload must be a text field, not a file."]}, payloads=[], file_fields={"payload": jpeg}
        )

        # nor is one that is also given as text
        self.assertInvalid(
            {"payload": ["Payload must be a text field, not a file."]}, file_fields={"payload": upload(b"{}")}
        )

    def test_empty_file(self):
        self.assertInvalid({"files": {"0": ["The submitted file is empty."]}}, files=[upload(b"")])

    def test_too_many_files(self):
        jpeg = fixture_bytes("steve.marten.jpg")

        # the ten allowed
        prepared = self.read(files=[upload(jpeg) for _ in range(MAX_BROADCAST_FILES)])
        self.assertEqual(10, len(prepared.media))

        # every file past the tenth is reported, and none of them is read
        files = [upload(jpeg) for _ in range(12)]
        self.assertInvalid(
            {
                "files": {
                    "10": ["At most 10 files can be sent."],
                    "11": ["At most 10 files can be sent."],
                }
            },
            files=files,
        )

    def test_total_size(self):
        def sized(size: int):
            # the size the parser reported, so the request can be rejected without reading anything
            f = upload(PDF)
            f.size = size
            return f

        # the file that takes the total over the limit is the one reported
        self.assertInvalid(
            {"files": {"2": ["The files add up to more than 100 MiB."]}},
            files=[sized(40 * MIB), sized(40 * MIB), sized(40 * MIB)],
        )
        self.assertInvalid(
            {"files": {"1": ["The files add up to more than 100 MiB."]}},
            files=[sized(60 * MIB), sized(40 * MIB + 1)],
        )

        # exactly the limit is allowed
        prepared = self.read(files=[sized(60 * MIB), sized(40 * MIB)])
        self.assertEqual(2, len(prepared.media))
        self.assertEqual(MAX_BROADCAST_FILES_TOTAL_BYTES, sum(m.size for m in prepared.media))

        # too many bytes are not read: the files are not even looked at
        files = [sized(60 * MIB), sized(41 * MIB)]
        with patch("temba.msgs.usecases.broadcast_media.detect_media_type") as detect:
            self.assertInvalid({"files": {"1": ["The files add up to more than 100 MiB."]}}, files=files)
        detect.assert_not_called()

    def test_every_error_is_reported_at_once(self):
        jpeg = fixture_bytes("steve.marten.jpg")
        mp4 = fixture_bytes("snow.mp4")
        files = [
            upload(fixture_bytes("allo.wav")),  # 0: wav
            upload(jpeg),  # 1: fine
            upload(b""),  # 2: empty
            upload(GIF),  # 3: gif
            upload(jpeg + b"\x00" * (MAX_IMAGE_BYTES + 1 - len(jpeg))),  # 4: one byte over the image limit
            upload(HTML),  # 5: html
            upload(mp4),  # 6: fine
            upload(mp4 + b"\x00" * (17 * MIB)),  # 7: video over the limit
        ]

        self.assertInvalid(
            {
                "payload": ["Payload must be valid JSON."],
                "files": {
                    "0": ["Unsupported file type: audio/x-wav."],
                    "2": ["The submitted file is empty."],
                    "3": ["Unsupported file type: image/gif."],
                    "4": ["File is too large for image/jpeg: the limit is 5 MiB."],
                    "5": ["Unsupported file type: text/html."],
                    "7": ["File is too large for video/mp4: the limit is 16 MiB."],
                },
            },
            ["{broken"],
            files,
        )

    def test_limits_are_inclusive(self):
        jpeg = fixture_bytes("steve.marten.jpg")

        at_limit = self.read(files=[upload(jpeg + b"\x00" * (MAX_IMAGE_BYTES - len(jpeg)))])
        self.assertEqual(MAX_IMAGE_BYTES, at_limit.media[0].size)
        self.assertEqual("image/jpeg", at_limit.media[0].mime)

        self.assertInvalid(
            {"files": {"0": ["File is too large for image/jpeg: the limit is 5 MiB."]}},
            files=[upload(jpeg + b"\x00" * (MAX_IMAGE_BYTES + 1 - len(jpeg)))],
        )

    def test_media(self):
        jpeg = fixture_bytes("steve.marten.jpg")
        mp4 = fixture_bytes("snow.mp4")

        prepared = self.read(
            files=[upload(jpeg, "photo.bin", "application/octet-stream"), upload(mp4, "x.jpg", "image/jpeg")]
        )

        self.assertEqual(2, len(prepared.media))
        first, second = prepared.media

        self.assertEqual(0, first.position)
        self.assertEqual(len(jpeg), first.size)
        self.assertEqual(hashlib.sha256(jpeg).hexdigest(), first.sha256)
        self.assertEqual("image/jpeg", first.mime)
        self.assertEqual("jpg", first.extension)

        # the client's name and type don't matter
        self.assertEqual(1, second.position)
        self.assertEqual(hashlib.sha256(mp4).hexdigest(), second.sha256)
        self.assertEqual("video/mp4", second.mime)
        self.assertEqual("mp4", second.extension)

        self.assertEqual([first.sha256, second.sha256], prepared.file_sha256s)

        # the file is ready to be stored
        self.assertEqual(jpeg, first.file.read())

    def test_canonical_url(self):
        jpeg = fixture_bytes("steve.marten.jpg")
        sha256 = hashlib.sha256(jpeg).hexdigest()

        media = self.read(files=[upload(jpeg, "photo.bin")]).media[0]

        self.assertEqual(f"attachments/{self.org.id}/broadcasts/{sha256}.jpg", media.key(self.org.id))
        self.assertEqual(
            f"image/jpeg:{settings.STORAGE_URL}/attachments/{self.org.id}/broadcasts/{sha256}.jpg",
            media.attachment(self.org.id),
        )
        self.assertNotIn("?", media.attachment(self.org.id))
        self.assertNotIn("X-Amz-", media.attachment(self.org.id))

        # keyed by org
        self.assertIn(f"/attachments/{self.org2.id}/broadcasts/", media.attachment(self.org2.id))

    def test_file_is_read_in_one_pass(self):
        # bigger than the bytes given to libmagic and than one chunk
        jpeg = fixture_bytes("steve.marten.jpg")
        data = jpeg + b"\x00" * (3 * MIB)
        f = upload(data)

        with patch("temba.msgs.usecases.broadcast_media.detect_media_type", wraps=detect_media_type) as detect:
            with patch.object(f, "chunks", wraps=f.chunks) as chunks:
                prepared = self.read(files=[f])

        self.assertEqual(1, chunks.call_count)
        self.assertEqual(hashlib.sha256(data).hexdigest(), prepared.media[0].sha256)
        self.assertEqual(1, detect.call_count)
        self.assertEqual(MEDIA_SNIFF_BYTES, len(detect.call_args.args[0]))
        self.assertEqual(data[:MEDIA_SNIFF_BYTES], detect.call_args.args[0])

    def test_with_attachments(self):
        jpeg = fixture_bytes("steve.marten.jpg")
        mp4 = fixture_bytes("snow.mp4")
        audio = audio_only_mp4_bytes()
        media = self.read(files=[upload(jpeg), upload(mp4), upload(audio)]).media

        payload = {"groups": ["g1"], "msg": {"text": "Hi", "attachments": ["U1", "U2"]}}
        prepared = self.read([json.dumps(payload)], files=[upload(jpeg), upload(mp4), upload(audio)])

        attachments = prepared.with_attachments(self.org)["msg"]["attachments"]
        self.assertEqual(["U1", "U2"] + [m.attachment(self.org.id) for m in media], attachments)
        self.assertEqual(
            ["U1", "U2", "image/jpeg", "video/mp4", "audio/mp4"],
            attachments[:2] + [a.split(":")[0] for a in attachments[2:]],
        )

        # the parsed payload is not changed, the rest of it is kept
        self.assertEqual(["U1", "U2"], prepared.payload["msg"]["attachments"])
        self.assertEqual(
            {"groups": ["g1"], "msg": {"text": "Hi", "attachments": attachments}}, prepared.with_attachments(self.org)
        )

    def test_with_attachments_when_there_are_none(self):
        jpeg = upload(fixture_bytes("steve.marten.jpg"))

        for name, payload in (
            ("absent", {"groups": ["g1"], "msg": {"text": "Hi"}}),
            ("empty", {"groups": ["g1"], "msg": {"text": "Hi", "attachments": []}}),
        ):
            with self.subTest(name):
                jpeg.seek(0)
                prepared = self.read([json.dumps(payload)], files=[jpeg])

                result = prepared.with_attachments(self.org)
                self.assertEqual([prepared.media[0].attachment(self.org.id)], result["msg"]["attachments"])
                self.assertEqual("Hi", result["msg"]["text"])

    def test_with_attachments_with_a_bad_msg(self):
        jpeg = upload(fixture_bytes("steve.marten.jpg"))

        # msg missing or not an object is left for the serializer to report, as for JSON
        for name, payload in (
            ("missing", {"groups": ["g1"]}),
            ("string", {"groups": ["g1"], "msg": "Hi"}),
            ("list", {"groups": ["g1"], "msg": ["Hi"]}),
            ("null", {"groups": ["g1"], "msg": None}),
        ):
            with self.subTest(name):
                jpeg.seek(0)
                prepared = self.read([json.dumps(payload)], files=[jpeg])
                self.assertEqual(payload, prepared.with_attachments(self.org))

    def test_with_attachments_when_attachments_is_not_a_list(self):
        jpeg = upload(fixture_bytes("steve.marten.jpg"))

        for value in ("image/png:https://example.com/a.png", {"a": 1}, 5, True, None):
            payload = {"groups": ["g1"], "msg": {"text": "Hi", "attachments": value}}

            # with files there is nothing to append to
            with self.subTest(f"files {value}"):
                jpeg.seek(0)
                prepared = self.read([json.dumps(payload)], files=[jpeg])

                with self.assertRaises(BroadcastMediaInvalid) as cm:
                    prepared.with_attachments(self.org)
                self.assertEqual(
                    {"payload": {"msg": {"attachments": ["Expected a list of items."]}}}, cm.exception.errors
                )

            # without them it is left for the serializer, as for JSON
            with self.subTest(f"no files {value}"):
                prepared = self.read([json.dumps(payload)])
                self.assertEqual(payload, prepared.with_attachments(self.org))


class FakeBotocoreEvents:
    """The part of a botocore client's event system that the upload uses"""

    def __init__(self):
        self.handlers = []

    def register(self, event_name, handler):
        self.handlers.append((event_name, handler))

    def unregister(self, event_name, handler):
        self.handlers.remove((event_name, handler))

    def send(self, url="https://bucket.s3.amazonaws.com/some/key"):
        """What botocore does just before each HTTP request is sent"""
        for _, handler in list(self.handlers):
            handler(request=SimpleNamespace(url=url))


class FakeStorage:
    """A storage with a botocore client, whose save() is whatever the test says"""

    def __init__(self, events, save):
        self.events = events
        self.save = save
        self.connection = SimpleNamespace(
            meta=SimpleNamespace(client=SimpleNamespace(meta=SimpleNamespace(events=events)))
        )


class FakeTimer:
    """A threading.Timer that only fires when the test says so"""

    instances = []

    def __init__(self, interval, function):
        self.interval = interval
        self.function = function
        self.started = False
        self.cancelled = False
        self.daemon = False
        FakeTimer.instances.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.function()


class StoreBroadcastMediaTest(TembaTest):
    def setUp(self):
        super().setUp()

        _dedup_redis.cache_clear()
        FakeTimer.instances = []

        # S3 is only stubbed at the storage, which under the test settings is the shared private storage
        patcher = patch.object(private_file_storage, "save", return_value="saved")
        self.save = patcher.start()
        self.addCleanup(patcher.stop)

        self.redis = _dedup_redis()
        self.jpeg = fixture_bytes("steve.marten.jpg")
        self.jpeg_sha256 = hashlib.sha256(self.jpeg).hexdigest()

    def tearDown(self):
        _dedup_redis.cache_clear()

        super().tearDown()

    def media(self, *datas: bytes) -> list[InlineMedia]:
        form, uploads = multipart([json.dumps({"msg": {"text": "Hi"}})], [upload(data) for data in datas])
        return read_broadcast_request("multipart/form-data", form, uploads).media

    def dedup_key(self, org, sha256: str) -> str:
        return f"broadcast_media:{org.id}:{sha256}"

    def dedup_keys(self) -> list:
        return self.redis.keys(f"{BROADCAST_MEDIA_DEDUP_KEY_PREFIX}:*")

    def clear_dedup(self):
        for key in self.dedup_keys():
            self.redis.delete(key)

    def other_jpeg(self) -> bytes:
        return self.jpeg + b"\x00"

    def test_constants(self):
        self.assertEqual(7 * 24 * 60 * 60, BROADCAST_MEDIA_DEDUP_TTL_SECONDS)
        self.assertEqual("broadcast_media", BROADCAST_MEDIA_DEDUP_KEY_PREFIX)
        self.assertEqual(2, BROADCAST_MEDIA_REDIS_TIMEOUT_SECONDS)
        self.assertEqual(120, BROADCAST_MEDIA_WORKER_TIMEOUT_SECONDS)
        self.assertEqual(60, S3_UPLOAD_CALL_BUDGET_SECONDS)

    def test_dedup_redis_has_timeouts_and_no_retry(self):
        kwargs = self.redis.connection_pool.connection_kwargs

        self.assertEqual(BROADCAST_MEDIA_REDIS_TIMEOUT_SECONDS, kwargs["socket_timeout"])
        self.assertEqual(BROADCAST_MEDIA_REDIS_TIMEOUT_SECONDS, kwargs["socket_connect_timeout"])
        self.assertFalse(kwargs.get("retry_on_timeout", False))

        # same database as the default cache, and created once
        self.assertEqual(get_redis_connection().connection_pool.connection_kwargs["db"], kwargs["db"])
        self.assertIs(self.redis, _dedup_redis())

    def test_miss_uploads_and_records(self):
        media = self.media(self.jpeg)
        key = self.dedup_key(self.org, self.jpeg_sha256)
        self.assertIsNone(self.redis.get(key))

        with patch.object(self.redis, "set", wraps=self.redis.set) as redis_set:
            store_broadcast_media(self.org, media)

        # uploaded with the object key and the detected type
        self.save.assert_called_once()
        self.assertEqual(
            (f"attachments/{self.org.id}/broadcasts/{self.jpeg_sha256}.jpg", media[0].file), self.save.call_args.args
        )
        self.assertEqual("image/jpeg", media[0].file.content_type)

        # and then recorded, with the expiry
        redis_set.assert_called_once_with(key, media[0].attachment(self.org.id), ex=7 * 24 * 60 * 60)
        self.assertEqual(media[0].attachment(self.org.id).encode(), self.redis.get(key))
        self.assertAlmostEqual(7 * 24 * 60 * 60, self.redis.ttl(key), delta=10)

    def test_the_object_is_uploaded_before_it_is_recorded(self):
        key = self.dedup_key(self.org, self.jpeg_sha256)
        seen = []
        self.save.side_effect = lambda *args: seen.append(self.redis.get(key))

        store_broadcast_media(self.org, self.media(self.jpeg))

        self.assertEqual([None], seen)
        self.assertIsNotNone(self.redis.get(key))

    def test_hit_skips_the_upload(self):
        media = self.media(self.jpeg)
        self.redis.set(self.dedup_key(self.org, self.jpeg_sha256), media[0].attachment(self.org.id), ex=60)

        with patch.object(self.redis, "set", wraps=self.redis.set) as redis_set:
            store_broadcast_media(self.org, media)

        self.save.assert_not_called()
        redis_set.assert_not_called()

    def test_stored_value_that_differs_is_a_miss(self):
        media = self.media(self.jpeg)
        key = self.dedup_key(self.org, self.jpeg_sha256)
        self.redis.set(key, f"image/png:{settings.STORAGE_URL}/attachments/{self.org.id}/broadcasts/x.png", ex=60)

        store_broadcast_media(self.org, media)

        self.save.assert_called_once()
        self.assertEqual(media[0].attachment(self.org.id).encode(), self.redis.get(key))

    def test_same_content_twice_in_one_call_uploads_once(self):
        media = self.media(self.jpeg, self.jpeg)
        self.assertEqual(2, len(media))

        store_broadcast_media(self.org, media)

        self.save.assert_called_once()

    def test_distinct_files_are_uploaded_in_order(self):
        other = self.other_jpeg()
        media = self.media(self.jpeg, other, self.jpeg)

        store_broadcast_media(self.org, media)

        self.assertEqual(
            [media[0].key(self.org.id), media[1].key(self.org.id)], [c.args[0] for c in self.save.call_args_list]
        )

    def test_dedup_is_per_org(self):
        media = self.media(self.jpeg)
        store_broadcast_media(self.org, media)
        self.save.assert_called_once()

        # same org again: nothing to do
        store_broadcast_media(self.org, self.media(self.jpeg))
        self.save.assert_called_once()

        # another org stores it under its own prefix and its own entry
        store_broadcast_media(self.org2, self.media(self.jpeg))
        self.assertEqual(2, self.save.call_count)
        self.assertEqual(f"attachments/{self.org2.id}/broadcasts/{self.jpeg_sha256}.jpg", self.save.call_args.args[0])
        self.assertIsNotNone(self.redis.get(self.dedup_key(self.org2, self.jpeg_sha256)))

    def test_storage_failures(self):
        errors = [
            ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "PutObject"),
            S3UploadFailedError("Failed to upload"),
            ReadTimeoutError(endpoint_url="https://example.com"),
            ConnectTimeoutError(endpoint_url="https://example.com"),
            OSError("disk full"),
        ]
        for error in errors:
            with self.subTest(type(error).__name__):
                self.save.reset_mock()
                self.save.side_effect = error
                self.clear_dedup()

                with self.assertRaises(BroadcastMediaUnavailable) as cm:
                    store_broadcast_media(self.org, self.media(self.jpeg, self.other_jpeg()))

                self.assertEqual("upload", cm.exception.stage)
                self.assertIs(error, cm.exception.__cause__)

                # once: the second file is not tried, and nothing is recorded
                self.save.assert_called_once()
                self.assertEqual([], self.dedup_keys())

    def test_redis_failures(self):
        media = self.media(self.jpeg, self.other_jpeg())

        for name, command, stage, uploads in (
            ("get connection", "get", "dedup_lookup", 0),
            ("set timeout", "set", "dedup_record", 1),
        ):
            for error in (RedisConnectionError("down"), RedisTimeoutError("slow"), RedisError("other")):
                with self.subTest(f"{name} {type(error).__name__}"):
                    self.save.reset_mock()

                    with patch.object(self.redis, command, side_effect=error):
                        with self.assertRaises(BroadcastMediaUnavailable) as cm:
                            store_broadcast_media(self.org, media)

                    self.assertEqual(stage, cm.exception.stage)
                    self.assertIs(error, cm.exception.__cause__)
                    self.assertEqual(uploads, self.save.call_count)

    def test_budget_checked_before_each_upload(self):
        # an upload may start only if it, in the worst case, still ends before the worker is killed
        worst_case = S3_UPLOAD_CALL_BUDGET_SECONDS + S3_UPLOAD_CONNECT_TIMEOUT_SECONDS + S3_UPLOAD_READ_TIMEOUT_SECONDS
        latest_start = BROADCAST_MEDIA_WORKER_TIMEOUT_SECONDS - worst_case
        self.assertEqual(25, latest_start)

        for elapsed, allowed in (
            (0, True),
            (latest_start - 0.01, True),
            (latest_start, False),
            (latest_start + 60, False),
        ):
            with self.subTest(elapsed=elapsed):
                self.save.reset_mock()
                self.clear_dedup()

                clock = SimpleNamespace(now=1000.0)

                def first_upload(*args):
                    clock.now += elapsed  # the first upload takes this long

                self.save.side_effect = first_upload

                with patch("temba.msgs.usecases.broadcast_media._now", side_effect=lambda: clock.now):
                    if allowed:
                        store_broadcast_media(self.org, self.media(self.jpeg, self.other_jpeg()))
                        self.assertEqual(2, self.save.call_count)
                    else:
                        with self.assertRaises(BroadcastMediaUnavailable) as cm:
                            store_broadcast_media(self.org, self.media(self.jpeg, self.other_jpeg()))

                        # the next file is not started
                        self.assertEqual("upload", cm.exception.stage)
                        self.assertEqual(1, self.save.call_count)

    def test_nothing_is_stored_when_the_first_upload_is_refused(self):
        clock = SimpleNamespace(now=1000.0)
        times = iter([1000.0, 1000.0 + BROADCAST_MEDIA_WORKER_TIMEOUT_SECONDS])
        media = self.media(self.jpeg)

        with patch("temba.msgs.usecases.broadcast_media._now", side_effect=lambda: next(times, clock.now)):
            with self.assertRaises(BroadcastMediaUnavailable) as cm:
                store_broadcast_media(self.org, media)

        self.assertEqual("upload", cm.exception.stage)
        self.save.assert_not_called()
        self.assertEqual([], self.dedup_keys())

    @patch("temba.msgs.usecases.broadcast_media.threading", SimpleNamespace(Event=threading.Event, Timer=FakeTimer))
    def test_call_budget_aborts_the_next_send(self):
        events = FakeBotocoreEvents()
        calls = []

        def save(key, file):
            calls.append(key)

            # the timer is armed and the handler is registered while the upload runs
            (timer,) = FakeTimer.instances
            self.assertTrue(timer.started)
            self.assertEqual(S3_UPLOAD_CALL_BUDGET_SECONDS, timer.interval)
            self.assertTrue(timer.daemon)
            self.assertEqual(["before-send.s3"], [name for name, _ in events.handlers])

            # a first send goes out, and its attempt returns on its own even though the budget is spent by then
            events.send()
            timer.fire()

            # but the next send is aborted before it is made
            events.send(url="https://bucket.s3.amazonaws.com/attachments/1/broadcasts/abc.jpg")

        storage = FakeStorage(events, save)
        media = self.media(self.jpeg, self.other_jpeg())

        with patch("temba.msgs.usecases.broadcast_media.media_upload_storage", return_value=storage):
            with self.assertRaises(BroadcastMediaUnavailable) as cm:
                store_broadcast_media(self.org, media)

        self.assertEqual("upload", cm.exception.stage)
        self.assertIsInstance(cm.exception.__cause__, ReadTimeoutError)

        # the abort says nothing about what was being sent
        self.assertNotIn("attachments", str(cm.exception.__cause__))
        self.assertNotIn("abc.jpg", str(cm.exception.__cause__))

        # the next file is not started, nothing is recorded, and nothing is left behind
        self.assertEqual([media[0].key(self.org.id)], calls)
        self.assertEqual([], self.dedup_keys())
        self.assertEqual([], events.handlers)
        self.assertTrue(FakeTimer.instances[0].cancelled)

    @patch("temba.msgs.usecases.broadcast_media.threading", SimpleNamespace(Event=threading.Event, Timer=FakeTimer))
    def test_handler_and_timer_are_cleaned_up_after_each_upload(self):
        events = FakeBotocoreEvents()
        results = iter([None, ClientError({"Error": {"Code": "SlowDown", "Message": "x"}}, "PutObject")])
        registered = []

        def save(key, file):
            registered.append(len(events.handlers))
            result = next(results)
            if result:
                raise result

        storage = FakeStorage(events, save)

        # the first file is stored, and the second fails; the handler of each upload is gone afterwards
        with patch("temba.msgs.usecases.broadcast_media.media_upload_storage", return_value=storage):
            with self.assertRaises(BroadcastMediaUnavailable):
                store_broadcast_media(self.org, self.media(self.jpeg, self.other_jpeg()))

        self.assertEqual([1, 1], registered)
        self.assertEqual([], events.handlers)
        self.assertEqual(2, len(FakeTimer.instances))
        self.assertTrue(all(t.started and t.cancelled for t in FakeTimer.instances))

    @patch("temba.msgs.usecases.broadcast_media.threading", SimpleNamespace(Event=threading.Event, Timer=FakeTimer))
    def test_a_late_send_of_a_later_upload_is_not_aborted(self):
        # the event of one upload does not carry over: a handler left registered would abort a later request
        events = FakeBotocoreEvents()

        def save(key, file):
            events.send()

        storage = FakeStorage(events, save)

        with patch("temba.msgs.usecases.broadcast_media.media_upload_storage", return_value=storage):
            store_broadcast_media(self.org, self.media(self.jpeg))
            FakeTimer.instances[0].fire()  # fires after the upload has finished
            store_broadcast_media(self.org, self.media(self.other_jpeg()))

        self.assertEqual([], events.handlers)

    def test_storage_without_a_client(self):
        # filesystem storage has nothing to register a handler on, and is stored as is
        store_broadcast_media(self.org, self.media(self.jpeg))

        self.save.assert_called_once()

    def test_no_files(self):
        store_broadcast_media(self.org, [])

        self.save.assert_not_called()
        self.assertEqual([], self.dedup_keys())


class MediaLimitsTest(TembaTest):
    def test_constants(self):
        self.assertEqual(10, MAX_BROADCAST_FILES)
        self.assertEqual(100 * MIB, MAX_BROADCAST_FILES_TOTAL_BYTES)
        self.assertEqual(5 * MIB, MAX_IMAGE_BYTES)
        self.assertEqual(500 * 1024, MAX_STICKER_BYTES)
        self.assertEqual(16 * MIB, MAX_VIDEO_BYTES)
        self.assertEqual(16 * MIB, MAX_AUDIO_BYTES)
        self.assertEqual(100 * MIB, MAX_DOCUMENT_BYTES)
        self.assertEqual(256 * 1024, MEDIA_SNIFF_BYTES)

    def test_limit_per_category(self):
        by_category = {
            "image/jpeg": MAX_IMAGE_BYTES,
            "image/png": MAX_IMAGE_BYTES,
            "image/webp": MAX_STICKER_BYTES,
            "video/mp4": MAX_VIDEO_BYTES,
            "video/3gpp": MAX_VIDEO_BYTES,
            "audio/aac": MAX_AUDIO_BYTES,
            "audio/amr": MAX_AUDIO_BYTES,
            "audio/mpeg": MAX_AUDIO_BYTES,
            "audio/mp4": MAX_AUDIO_BYTES,
            "audio/ogg": MAX_AUDIO_BYTES,
            "text/plain": MAX_DOCUMENT_BYTES,
            "application/pdf": MAX_DOCUMENT_BYTES,
            "application/msword": MAX_DOCUMENT_BYTES,
            "application/vnd.ms-excel": MAX_DOCUMENT_BYTES,
            "application/vnd.ms-powerpoint": MAX_DOCUMENT_BYTES,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": MAX_DOCUMENT_BYTES,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": MAX_DOCUMENT_BYTES,
            "application/vnd.openxmlformats-officedocument.presentationml.presentation": MAX_DOCUMENT_BYTES,
        }
        self.assertEqual(set(by_category), set(ALLOWED_BROADCAST_MEDIA))

        for mime, limit in by_category.items():
            with self.subTest(mime):
                self.assertEqual(limit, ALLOWED_BROADCAST_MEDIA[mime].max_bytes)
                self.assertIsNone(media_size_error(mime, 1))
                self.assertIsNone(media_size_error(mime, limit))
                self.assertIsNotNone(media_size_error(mime, limit + 1))

    def test_size_error_message_for_any_limit(self):
        # none of the limits is like this, but the message must make sense for whichever is set
        for limit, text in ((1500, "1500 bytes"), (2048, "2 KiB"), (3 * 1024 * 1024, "3 MiB")):
            with patch.dict(ALLOWED_BROADCAST_MEDIA, {"application/pdf": AllowedMedia("document", "pdf", limit)}):
                self.assertEqual(
                    f"File is too large for application/pdf: the limit is {text}.",
                    media_size_error("application/pdf", limit + 1),
                )

    def test_size_error_messages(self):
        self.assertEqual(
            "File is too large for image/jpeg: the limit is 5 MiB.", media_size_error("image/jpeg", 5 * MIB + 1)
        )
        self.assertEqual(
            "File is too large for image/webp: the limit is 500 KiB.", media_size_error("image/webp", 500 * 1024 + 1)
        )
        self.assertEqual(
            "File is too large for video/mp4: the limit is 16 MiB.", media_size_error("video/mp4", 17 * MIB)
        )
