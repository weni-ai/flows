import struct
from contextlib import contextmanager

import sentry_sdk

from django.conf import settings


@contextmanager
def capture_sentry_events():
    """
    Collects the Sentry events raised inside the block as they would be sent, i.e. after every event processor has run,
    and sends nothing. Frame variables are on, as in production, so that a leak through them would show.
    """
    events = []
    client = sentry_sdk.Client(
        dsn="https://public@example.com/1", transport=events.append, default_integrations=False, with_locals=True
    )

    hub = sentry_sdk.Hub.current
    previous = hub.client
    hub.bind_client(client)
    try:
        yield events
    finally:
        hub.bind_client(previous)


def read_test_media(name: str) -> bytes:
    """
    Returns the bytes of a file in media/test_media
    """
    with open(f"{settings.MEDIA_ROOT}/test_media/{name}", "rb") as f:
        return f.read()


def mp4_box(box_type: bytes, body: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(body), box_type) + body


def split_mp4_boxes(data: bytes) -> list[tuple[bytes, bytes]]:
    """
    Splits ISO BMFF data into its (type, body) boxes, without descending into them
    """
    boxes, offset = [], 0
    while offset < len(data):
        size, box_type = struct.unpack(">I4s", data[offset : offset + 8])
        boxes.append((box_type, data[offset + 8 : offset + size]))
        offset += size
    return boxes


def _track_handler(trak_body: bytes) -> bytes:
    mdia = dict(split_mp4_boxes(trak_body))[b"mdia"]
    hdlr = dict(split_mp4_boxes(mdia))[b"hdlr"]
    return hdlr[8:12]  # after version, flags and pre_defined


def audio_only_mp4_bytes() -> bytes:
    """
    Returns the audio-only equivalent of media/test_media/snow.mp4, which is what an .m4a file is. snow.m4a is a copy of
    snow.mp4 and still has its video track, so the video track is dropped here instead. The ftyp box is kept, so
    libmagic still reports video/mp4 and only the tracks tell that no video is left.
    """
    output = []
    for box_type, body in split_mp4_boxes(read_test_media("snow.mp4")):
        if box_type == b"moov":
            children = [
                (child_type, child_body)
                for child_type, child_body in split_mp4_boxes(body)
                if not (child_type == b"trak" and _track_handler(child_body) == b"vide")
            ]
            body = b"".join(mp4_box(child_type, child_body) for child_type, child_body in children)
        output.append(mp4_box(box_type, body))

    return b"".join(output)
