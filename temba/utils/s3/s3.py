import re
from functools import lru_cache
from typing import Iterable, NamedTuple
from urllib.parse import unquote, urlparse

import boto3
from botocore.client import Config
from storages.backends.s3 import S3Storage

from django.conf import settings
from django.core.files.storage import DefaultStorage
from django.utils.module_loading import import_string

from temba.utils import json

private_file_storage = DefaultStorage()

_s3_client = None

S3_CLIENT_MAX_RETRY_ATTEMPTS = 3

# limits of every HTTP call made by media_upload_storage(); botocore standard mode retries with exponential backoff
# and jitter, which is safe because uploads are content-addressed and so idempotent
S3_UPLOAD_CONNECT_TIMEOUT_SECONDS = 5
S3_UPLOAD_READ_TIMEOUT_SECONDS = 30
S3_UPLOAD_MAX_RETRY_ATTEMPTS = 2
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
        _s3_client = session.client("s3", config=Config(retries={"max_attempts": S3_CLIENT_MAX_RETRY_ATTEMPTS}))

    return _s3_client


@lru_cache(maxsize=None)
def regional_client(region_name: str | None):
    """
    Returns a shared S3 client bound to the given region, as SigV4 signatures are only valid for the bucket's region
    """
    session = boto3.Session(
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID, aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
    )
    config = Config(
        signature_version="s3v4",
        s3={"addressing_style": "virtual"},
        retries={"max_attempts": S3_CLIENT_MAX_RETRY_ATTEMPTS},
    )
    return session.client("s3", region_name=region_name, config=config)


@lru_cache(maxsize=None)
def media_upload_storage():
    """
    Returns the storage used to upload media files received by the API, created once per process.

    Under S3 it is an instance of the configured storage class with explicit connect and read timeouts and a bounded,
    backed-off retry on every HTTP call, scoped to these uploads so that AWS_S3_CLIENT_CONFIG and every other upload in
    the project stay as they are. Objects are overwritten, as their keys are content-addressed. With any other storage
    (local and test filesystem) the shared private_file_storage is returned. No connection is made here.
    """
    storage_class = import_string(settings.DEFAULT_FILE_STORAGE)
    if not (isinstance(storage_class, type) and issubclass(storage_class, S3Storage)):
        return private_file_storage

    storage = storage_class(file_overwrite=True)

    # merging keeps the signature version, addressing style and proxies that django-storages sets by default
    storage.client_config = storage.client_config.merge(
        Config(
            connect_timeout=S3_UPLOAD_CONNECT_TIMEOUT_SECONDS,
            read_timeout=S3_UPLOAD_READ_TIMEOUT_SECONDS,
            retries={"mode": "standard", "max_attempts": S3_UPLOAD_MAX_RETRY_ATTEMPTS},
        )
    )
    return storage


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


def is_org_object_key(key: str, org_id: int) -> bool:
    """
    Whether an object key sits under one of the org-scoped prefixes, e.g. media/<org_id>/..., for the given org.
    Keys with an empty, "." or ".." segment are refused so a key can never resolve into another org's prefix.
    """
    if any(segment in ("", ".", "..") for segment in key.split("/")):
        return False

    prefixes = {prefix.strip("/") for prefix in settings.S3_ORG_SCOPED_KEY_PREFIXES} - {""}

    return any(key.startswith(f"{prefix}/{org_id}/") for prefix in prefixes)


def presign_org_url(url: str, org_id: int) -> str:
    """
    Like presign_url, but only signs objects whose key belongs to the given org, returning any other URL unchanged
    """
    location = parse_s3_url(url)
    if not location or not is_org_object_key(location.key, org_id):
        return url

    return presign_url(url)


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
