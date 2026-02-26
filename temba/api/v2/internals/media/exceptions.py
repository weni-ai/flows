"""
Custom exceptions for the S3 Media Proxy module.
"""


class MediaFileNotFoundException(Exception):
    """Base exception for file not found errors."""

    message = "File not found"

    def __init__(self):
        super().__init__(self.message)


class MediaAccessDeniedException(Exception):
    """Base exception for access denied errors."""

    message = "Access denied"

    def __init__(self):
        super().__init__(self.message)


class EmptyFileIdException(MediaFileNotFoundException):
    """Raised when an empty file_id is provided."""

    message = "Empty file_id provided"


class InvalidFileIdFormatException(MediaAccessDeniedException):
    """Raised when the file_id format is invalid (e.g., too long)."""

    message = "Invalid file_id format"


class S3BucketNotConfiguredException(MediaFileNotFoundException):
    """Raised when the S3 bucket is not configured in settings."""

    message = "S3 bucket not configured"


class PresignedUrlGenerationException(MediaFileNotFoundException):
    """Raised when pre-signed URL generation fails."""

    message = "Unable to generate access URL"
