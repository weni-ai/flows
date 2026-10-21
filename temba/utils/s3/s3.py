import re
from functools import lru_cache
from typing import Iterable, NamedTuple
from urllib.parse import unquote, urlparse

import boto3
from botocore.client import Config

from django.conf import settings
from django.core.files.storage import DefaultStorage

from temba.utils import json

private_file_storage = DefaultStorage()

_s3_client = None

S3_HOST_REGEX = re.compile(r"(?:(?P<bucket>.+)\.)?s3(?:[.-](?P<region>[a-z0-9-]+))?\.amazonaws\.com")


class S3Location(NamedTuple):
    bucket: str
    key: str
    region: str | None


def client():  # pragma: no cover
    """
    Returns our shared S3 client
    """
    global _s3_client
    if not _s3_client:
        session = boto3.Session(
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID, aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        )
        _s3_client = session.client("s3", config=Config(retries={"max_attempts": 3}))

    return _s3_client


@lru_cache(maxsize=None)
def regional_client(region_name: str | None):
    """
    Returns a shared S3 client bound to the given region, as SigV4 signatures are only valid for the bucket's region
    """
    session = boto3.Session(
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID, aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
    )
    config = Config(signature_version="s3v4", s3={"addressing_style": "virtual"}, retries={"max_attempts": 3})
    return session.client("s3", region_name=region_name, config=config)


def parse_s3_url(url: str) -> S3Location | None:
    """
    Parses virtual-hosted, path-style and AWS_BUCKET_DOMAIN URLs into their S3 location, ignoring any query string
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    path = unquote(parsed.path).lstrip("/")

    host_match = S3_HOST_REGEX.fullmatch(host)
    if host_match:
        bucket, region = host_match.group("bucket"), host_match.group("region")
        if not bucket:
            bucket, _, path = path.partition("/")
    elif host == settings.AWS_BUCKET_DOMAIN:
        bucket, region = settings.AWS_STORAGE_BUCKET_NAME, None
    else:
        return None

    return S3Location(bucket, path, region) if bucket and path else None


def signable_buckets() -> set[str]:
    return {settings.AWS_STORAGE_BUCKET_NAME, *settings.S3_MEDIA_BUCKETS, *settings.S3_SIGNED_EXTRA_BUCKETS}


def presign_url(url: str, expires: int | None = None, response_content_disposition: str | None = None) -> str:
    """
    Returns a pre-signed GET URL for objects in our buckets, or the given URL unchanged for anything else
    """
    location = parse_s3_url(url)
    if not location or location.bucket not in signable_buckets():
        return url

    params = {"Bucket": location.bucket, "Key": location.key}
    if response_content_disposition:
        params["ResponseContentDisposition"] = response_content_disposition

    return regional_client(location.region or settings.AWS_S3_REGION_NAME).generate_presigned_url(
        "get_object", Params=params, ExpiresIn=expires or settings.S3_PRESIGNED_URL_EXPIRES
    )


def presign_attachment(attachment: str) -> str:
    """
    Pre-signs the URL of a type:url message attachment
    """
    content_type, _, url = attachment.partition(":")
    if content_type == "geo" or not url:
        return attachment

    return f"{content_type}:{presign_url(url)}"


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

    obj = client().get_object(Bucket=bucket, Key=key)
    return obj["Body"].read()


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
