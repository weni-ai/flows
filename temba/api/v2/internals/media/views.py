"""
S3 Media Proxy View

Provides a permanent URL endpoint that generates pre-signed URLs for private S3 files
and redirects users to access them securely.

This is used to provide permanent links in chat history JSONL files while keeping
the S3 bucket 100% private.
"""

import logging

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
    InvalidFileIdFormatException,
    MediaAccessDeniedException,
    MediaFileNotFoundException,
    PresignedUrlGenerationException,
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
    3. Generates a pre-signed URL with short expiration (5 minutes)
    4. Returns HTTP 302 redirect to the pre-signed URL

    This allows permanent URLs in chat history exports while keeping the S3 bucket private.

    URL: GET /api/v2/internals/media/download/<object_key>/

    Example:
        If the file path in S3 is "media/image.jpg", the request would be:
        GET /api/v2/internals/media/download/media/image.jpg/
    """

    authentication_classes = []  # Public endpoint - security via object_key obscurity + validation
    permission_classes = []
    renderer_classes = [JSONRenderer]

    def get(self, request, object_key: str, *args, **kwargs):
        """
        Handle GET request to download/redirect to S3 file.

        Args:
            request: The HTTP request
            object_key: The S3 object key (path + filename in the bucket)

        Returns:
            HTTP 302 redirect to pre-signed S3 URL, or error response
        """
        try:
            # Validate object_key
            self._validate_object_key(object_key)

            # Get bucket from settings
            bucket = self._get_bucket()

            # Generate pre-signed URL
            presigned_url = self._generate_presigned_url(bucket, object_key)

            # Return 302 redirect to the pre-signed URL
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
        """
        Validate the S3 object key format.

        Args:
            object_key: The S3 object key to validate

        Raises:
            EmptyFileIdException: If object_key is empty
            InvalidFileIdFormatException: If object_key format is invalid
        """
        if not object_key:
            raise EmptyFileIdException()

        # Basic validation: object_key should have reasonable length
        if len(object_key) > 1024:
            raise InvalidFileIdFormatException()

    def _get_bucket(self) -> str:
        """
        Get the S3 bucket name from settings.

        Returns:
            The S3 bucket name

        Raises:
            S3BucketNotConfiguredException: If bucket is not configured
        """
        bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", None)
        if not bucket:
            raise S3BucketNotConfiguredException()
        return bucket

    def _generate_presigned_url(self, bucket: str, key: str) -> str:
        """
        Generate a pre-signed URL for the S3 object.

        Args:
            bucket: S3 bucket name
            key: S3 object key

        Returns:
            Pre-signed URL string

        Raises:
            MediaFileNotFoundException: If the object doesn't exist or URL generation fails
        """
        try:
            s3_client = s3.client()

            # Generate pre-signed URL with content disposition for download
            s3_params = {
                "Bucket": bucket,
                "Key": key,
            }

            presigned_url = s3_client.generate_presigned_url(
                "get_object",
                Params=s3_params,
                ExpiresIn=PRESIGNED_URL_EXPIRES,
            )

            return presigned_url

        except Exception as e:
            logger.error(f"Failed to generate presigned URL for {bucket}/{key}: {str(e)}")
            raise PresignedUrlGenerationException() from e
