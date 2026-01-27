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
    1. Receives a file_id that identifies a file in S3
    2. Validates that the requester has access to the file (placeholder for context validation)
    3. Generates a pre-signed URL with short expiration (5 minutes)
    4. Returns HTTP 302 redirect to the pre-signed URL

    This allows permanent URLs in chat history exports while keeping the S3 bucket private.

    URL: GET /api/v2/internals/media/download/<file_id>/
    """

    authentication_classes = []  # Public endpoint - security via file_id obscurity + validation
    permission_classes = []
    renderer_classes = [JSONRenderer]

    def get(self, request, file_id: str, *args, **kwargs):
        """
        Handle GET request to download/redirect to S3 file.

        Args:
            request: The HTTP request
            file_id: Unique identifier for the file (can be a full S3 key or an encoded identifier)

        Returns:
            HTTP 302 redirect to pre-signed S3 URL, or error response
        """
        try:
            # Validate file access (placeholder for context validation)
            self._validate_file_access(file_id, request)

            # Translate file_id to S3 bucket and key
            bucket, key = self._resolve_file_location(file_id)

            # Generate pre-signed URL
            presigned_url = self._generate_presigned_url(bucket, key)

            # Return 302 redirect to the pre-signed URL
            return HttpResponseRedirect(presigned_url)

        except MediaFileNotFoundException as e:
            logger.warning(f"Media file not found: {file_id} - {str(e)}")
            return Response(
                {"error": "File not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except MediaAccessDeniedException as e:
            logger.warning(f"Media access denied: {file_id} - {str(e)}")
            return Response(
                {"error": "Access denied"},
                status=status.HTTP_403_FORBIDDEN,
            )
        except Exception:
            logger.exception(f"Error generating presigned URL for file: {file_id}")
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _validate_file_access(self, file_id: str, request) -> None:
        """
        Validate that the requester has access to the requested file.

        This is a placeholder for future implementation where we verify:
        - The file_id belongs to a valid archived chat context
        - The requester has permission to access this context
        - Any rate limiting or abuse prevention

        Args:
            file_id: The file identifier
            request: The HTTP request for extracting auth context if needed

        Raises:
            MediaAccessDeniedException: If access should be denied
            MediaFileNotFoundException: If the file context doesn't exist
        """
        # TODO: Implement context validation
        # Example validations to consider:
        # 1. Check if file_id matches a known pattern (e.g., org_id/archive_type/filename)
        # 2. Validate that the referenced org/archive exists
        # 3. Check if the request has valid auth token for the org
        # 4. Rate limiting per IP/user
        #
        # For now, we allow all requests but log them for monitoring
        if not file_id:
            raise EmptyFileIdException()

        # Basic validation: file_id should not be empty and should have reasonable length
        if len(file_id) > 1024:
            raise InvalidFileIdFormatException()

    def _resolve_file_location(self, file_id: str) -> tuple:
        """
        Translate the file_id to an S3 bucket and object key.

        The file_id can be:
        1. A full S3 URL (https://bucket.s3.amazonaws.com/key)
        2. A relative path that will be combined with the default bucket
        3. A prefixed path (bucket:key format)

        Args:
            file_id: The file identifier

        Returns:
            Tuple of (bucket, key)

        Raises:
            MediaFileNotFoundException: If the file_id cannot be resolved
        """
        # Case 1: Full S3 URL
        if file_id.startswith("http://") or file_id.startswith("https://"):
            return s3.split_url(file_id)

        # Case 2: bucket:key format
        if ":" in file_id and not file_id.startswith("/"):
            parts = file_id.split(":", 1)
            if len(parts) == 2:
                return parts[0], parts[1]

        # Case 3: Relative path - use default storage bucket
        bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", None)
        if not bucket:
            raise S3BucketNotConfiguredException()

        # Remove leading slash if present
        key = file_id.lstrip("/")

        return bucket, key

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
