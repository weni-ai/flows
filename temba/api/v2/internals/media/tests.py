from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse

from temba.tests.base import TembaTest

from .exceptions import (
    EmptyFileIdException,
    InvalidFileIdFormatException,
    PresignedUrlGenerationException,
    S3BucketNotConfiguredException,
)
from .views import PRESIGNED_URL_EXPIRES, S3MediaProxyView


class TestS3MediaProxyView(TembaTest):
    """Tests for the S3 Media Proxy endpoint."""

    def setUp(self):
        super().setUp()
        self.view = S3MediaProxyView()

    def test_validate_object_key_empty(self):
        """Test validation fails for empty object_key."""
        with self.assertRaises(EmptyFileIdException) as context:
            self.view._validate_object_key("")

        self.assertEqual(str(context.exception), EmptyFileIdException.message)

    def test_validate_object_key_too_long(self):
        """Test validation fails for overly long object_key."""
        long_object_key = "a" * 2000
        with self.assertRaises(InvalidFileIdFormatException) as context:
            self.view._validate_object_key(long_object_key)

        self.assertEqual(str(context.exception), InvalidFileIdFormatException.message)

    def test_validate_object_key_valid(self):
        """Test validation passes for valid object_key."""
        # Should not raise any exception
        self.view._validate_object_key("media/image.jpg")

    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_bucket_success(self, mock_settings):
        """Test getting bucket from settings."""
        mock_settings.AWS_STORAGE_BUCKET_NAME = "my-bucket"

        bucket = self.view._get_bucket()

        self.assertEqual(bucket, "my-bucket")

    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_bucket_not_configured(self, mock_settings):
        """Test error when bucket is not configured."""
        mock_settings.AWS_STORAGE_BUCKET_NAME = None

        with self.assertRaises(S3BucketNotConfiguredException) as context:
            self.view._get_bucket()

        self.assertEqual(str(context.exception), S3BucketNotConfiguredException.message)

    @patch("temba.api.v2.internals.media.views.s3")
    def test_generate_presigned_url_success(self, mock_s3):
        """Test successful pre-signed URL generation."""
        mock_client = MagicMock()
        mock_client.generate_presigned_url.return_value = "https://presigned-url.example.com/file"
        mock_s3.client.return_value = mock_client

        url = self.view._generate_presigned_url("test-bucket", "media/image.jpg")

        self.assertEqual(url, "https://presigned-url.example.com/file")
        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "test-bucket", "Key": "media/image.jpg"},
            ExpiresIn=PRESIGNED_URL_EXPIRES,
        )

    @patch("temba.api.v2.internals.media.views.s3")
    def test_generate_presigned_url_failure(self, mock_s3):
        """Test pre-signed URL generation failure."""
        mock_client = MagicMock()
        mock_client.generate_presigned_url.side_effect = Exception("S3 error")
        mock_s3.client.return_value = mock_client

        with self.assertRaises(PresignedUrlGenerationException) as context:
            self.view._generate_presigned_url("test-bucket", "media/image.jpg")

        self.assertEqual(str(context.exception), PresignedUrlGenerationException.message)


class TestS3MediaProxyEndpoint(TembaTest):
    """Integration tests for the S3 Media Proxy endpoint."""

    @patch("temba.api.v2.internals.media.views.s3")
    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_redirect_success(self, mock_settings, mock_s3):
        """Test successful redirect to pre-signed URL."""
        mock_settings.AWS_STORAGE_BUCKET_NAME = "test-bucket"

        mock_client = MagicMock()
        presigned_url = "https://test-bucket.s3.amazonaws.com/presigned?signature=abc123"
        mock_client.generate_presigned_url.return_value = presigned_url
        mock_s3.client.return_value = mock_client

        url = reverse("internals.media_download", kwargs={"object_key": "media/image.jpg"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, presigned_url)

    @patch("temba.api.v2.internals.media.views.s3")
    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_redirect_with_nested_path(self, mock_settings, mock_s3):
        """Test redirect with nested object_key path."""
        mock_settings.AWS_STORAGE_BUCKET_NAME = "test-bucket"

        mock_client = MagicMock()
        presigned_url = "https://test-bucket.s3.amazonaws.com/presigned?signature=abc123"
        mock_client.generate_presigned_url.return_value = presigned_url
        mock_s3.client.return_value = mock_client

        url = reverse("internals.media_download", kwargs={"object_key": "org/123/media/attachments/file.pdf"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, presigned_url)

        # Verify the correct object_key was used
        mock_client.generate_presigned_url.assert_called_once()
        call_args = mock_client.generate_presigned_url.call_args
        self.assertEqual(call_args[1]["Params"]["Bucket"], "test-bucket")
        self.assertEqual(call_args[1]["Params"]["Key"], "org/123/media/attachments/file.pdf")

    @patch("temba.api.v2.internals.media.views.s3")
    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_s3_error_returns_404(self, mock_settings, mock_s3):
        """Test that S3 errors return 404 status."""
        mock_settings.AWS_STORAGE_BUCKET_NAME = "test-bucket"

        mock_client = MagicMock()
        mock_client.generate_presigned_url.side_effect = Exception("S3 connection error")
        mock_s3.client.return_value = mock_client

        url = reverse("internals.media_download", kwargs={"object_key": "media/file.jpg"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_no_bucket_configured_returns_404(self, mock_settings):
        """Test that missing bucket configuration returns 404."""
        mock_settings.AWS_STORAGE_BUCKET_NAME = None

        url = reverse("internals.media_download", kwargs={"object_key": "media/file.jpg"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())


class TestPresignedUrlExpiration(TestCase):
    """Test that the pre-signed URL expiration is correctly configured."""

    def test_presigned_url_expires_is_5_minutes(self):
        """Verify the pre-signed URL expiration is 5 minutes (300 seconds)."""
        self.assertEqual(PRESIGNED_URL_EXPIRES, 300)
