from typing import Iterable
from urllib.parse import urlparse

import boto3
from botocore.config import Config

from django.core.files.storage import DefaultStorage
from django.conf import settings

from temba.utils import json
from . import presigned


class PrivateFileStorage(DefaultStorage):
    default_acl = "private"


private_file_storage = PrivateFileStorage()

_s3_client = None


def client():  # pragma: no cover
    """
    Returns our shared S3 client using pod IAM role credentials or explicit credentials if provided
    """
    global _s3_client
    if not _s3_client:
        # Configure session with explicit credentials if provided, otherwise use pod IAM role
        session_kwargs = {}
        if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
            session_kwargs.update(
                {
                    "aws_access_key_id": settings.AWS_ACCESS_KEY_ID,
                    "aws_secret_access_key": settings.AWS_SECRET_ACCESS_KEY,
                }
            )

        session = boto3.Session(**session_kwargs)

        # Configure the client with retries and endpoint if specified
        client_config = Config(retries={"max_attempts": 3})
        client_kwargs = {"config": client_config}

        # Add custom endpoint if configured (useful for testing or non-AWS S3)
        if getattr(settings, "AWS_S3_ENDPOINT_URL", None):
            client_kwargs["endpoint_url"] = settings.AWS_S3_ENDPOINT_URL

        _s3_client = session.client("s3", **client_kwargs)

    return _s3_client


def split_url(url):
    """
    Given an S3 URL parses it and returns a tuple of the bucket and key suitable for S3 boto calls
    """
    parsed = urlparse(url)
    bucket = parsed.netloc.split(".")[0]
    path = parsed.path.lstrip("/")

    return bucket, path


def get_body(url):
    """
    Given an S3 URL, downloads the object and returns the read body
    """
    bucket, key = split_url(url)
    s3_obj = client().get_object(Bucket=bucket, Key=key)
    return s3_obj["Body"].read()


class EventStreamReader:
    """
    Util for reading payloads from an S3 event stream and reconstructing JSONL records as they become available
    """

    def __init__(self, event_stream):
        self.event_stream = event_stream
        self.buffer = bytearray()

    def __iter__(self) -> Iterable[dict]:
        for event in self.event_stream:
            if "Records" in event:
                self.buffer.extend(event["Records"]["Payload"])

                lines = self.buffer.splitlines(keepends=True)

                # if last line doesn't end with \n then it's incomplete and goes back in the buffer
                if not lines[-1].endswith(b"\n"):
                    self.buffer = bytearray(lines[-1])
                    lines = lines[:-1]

                for line in lines:
                    yield json.loads(line.decode("utf-8"))
