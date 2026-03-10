"""
S3 Media Proxy View

Provides a permanent URL endpoint that generates pre-signed URLs for private S3 files
and redirects users to access them securely.

This is used to provide permanent links in chat history JSONL files while keeping
the S3 bucket 100% private.
"""

import logging

from botocore.exceptions import ClientError
from rest_framework import status
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from django.conf import settings
from django.http import HttpResponseRedirect

from temba.api.v2.internals.views import APIViewMixin
from temba.utils import s3

from .exceptions import (
    EmptyFileIdException,
    FileNotFoundInAnyBucketException,
    InvalidFileIdFormatException,
    MediaAccessDeniedException,
    MediaFileNotFoundException,
    S3BucketNotConfiguredException,
)

logger = logging.getLogger(__name__)


# Pre-signed URL expiration time in seconds (5 minutes)
PRESIGNED_URL_EXPIRES = 60 * 5


class S3MediaProxyView(APIViewMixin, APIView):
    """
    Endpoint that serves as a redirect proxy for private S3 files.

    This view:
    1. Receives an object_key that identifies a file in S3
    2. Validates the object_key format
    3. Searches for the file across all configured S3 buckets
    4. Generates a pre-signed URL with short expiration (5 minutes)
    5. Returns HTTP 302 redirect to the pre-signed URL

    Buckets are resolved from settings in this order:
    - AWS_STORAGE_BUCKET_NAME (primary bucket)
    - S3_MEDIA_BUCKETS (additional buckets list)

    URL: GET /api/v2/internals/media/download/<object_key>/

    Example:
        If the file path in S3 is "media/image.jpg", the request would be:
        GET /api/v2/internals/media/download/media/image.jpg
    """

    authentication_classes = []
    permission_classes = []
    renderer_classes = [JSONRenderer]

    def get(self, request, object_key: str, *args, **kwargs):
        try:
            self._validate_object_key(object_key)

            buckets = self._get_buckets()

            presigned_url = self._find_and_generate_presigned_url(buckets, object_key)

            return HttpResponseRedirect(presigned_url)

        except MediaFileNotFoundException as e:
            logger.warning(f"Media file not found: {object_key} - {str(e)}")
            return Response(
                {"error": "File not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except MediaAccessDeniedException as e:
            logger.warning(f"Media access denied: {object_key} - {str(e)}")
            return Response(
                {"error": "Access denied"},
                status=status.HTTP_403_FORBIDDEN,
            )
        except Exception:
            logger.exception(f"Error generating presigned URL for file: {object_key}")
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _validate_object_key(self, object_key: str) -> None:
        if not object_key:
            raise EmptyFileIdException()

        if len(object_key) > 1024:
            raise InvalidFileIdFormatException()

    def _get_buckets(self) -> list:
        """
        Collect all configured S3 bucket names, deduplicating while preserving order.

        Returns:
            List of unique bucket names

        Raises:
            S3BucketNotConfiguredException: If no buckets are configured at all
        """
        seen = set()
        buckets = []

        primary = getattr(settings, "AWS_STORAGE_BUCKET_NAME", None)
        if primary:
            seen.add(primary)
            buckets.append(primary)

        for bucket in getattr(settings, "S3_MEDIA_BUCKETS", []):
            if bucket and bucket not in seen:
                seen.add(bucket)
                buckets.append(bucket)

        if not buckets:
            raise S3BucketNotConfiguredException()

        return buckets

    def _find_and_generate_presigned_url(self, buckets: list, key: str) -> str:
        """
        Try each bucket in order; return a pre-signed URL from the first one
        that contains the object.

        Args:
            buckets: Ordered list of bucket names to search
            key: S3 object key

        Returns:
            Pre-signed URL string

        Raises:
            FileNotFoundInAnyBucketException: If the file is not found in any bucket
        """
        s3_client = s3.client()

        for bucket in buckets:
            try:
                s3_client.head_object(Bucket=bucket, Key=key)
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code in ("404", "NoSuchKey"):
                    continue
                logger.warning(f"Error checking {bucket}/{key}: {error_code}")
                continue
            except Exception:
                logger.warning(f"Unexpected error checking {bucket}/{key}", exc_info=True)
                continue

            return s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=PRESIGNED_URL_EXPIRES,
            )

        raise FileNotFoundInAnyBucketException()
