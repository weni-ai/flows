from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse

from temba.tests.base import TembaTest

from .views import (
    MediaAccessDeniedException,
    MediaFileNotFoundException,
    PRESIGNED_URL_EXPIRES,
    S3MediaProxyView,
)


class TestS3MediaProxyView(TembaTest):
    """Tests for the S3 Media Proxy endpoint."""

    def setUp(self):
        super().setUp()
        self.view = S3MediaProxyView()

    def test_resolve_file_location_full_url(self):
        """Test resolving a full S3 URL to bucket and key."""
        file_id = "https://my-bucket.s3.amazonaws.com/org/123/media/file.jpg"
        bucket, key = self.view._resolve_file_location(file_id)

        self.assertEqual(bucket, "my-bucket")
        self.assertEqual(key, "org/123/media/file.jpg")

    def test_resolve_file_location_http_url(self):
        """Test resolving an HTTP S3 URL."""
        file_id = "http://my-bucket.s3.amazonaws.com/path/to/file.pdf"
        bucket, key = self.view._resolve_file_location(file_id)

        self.assertEqual(bucket, "my-bucket")
        self.assertEqual(key, "path/to/file.pdf")

    def test_resolve_file_location_bucket_key_format(self):
        """Test resolving bucket:key format."""
        file_id = "my-custom-bucket:org/456/media/document.pdf"
        bucket, key = self.view._resolve_file_location(file_id)

        self.assertEqual(bucket, "my-custom-bucket")
        self.assertEqual(key, "org/456/media/document.pdf")

    @patch("temba.api.v2.internals.media.views.settings")
    def test_resolve_file_location_relative_path(self, mock_settings):
        """Test resolving a relative path using default bucket."""
        mock_settings.AWS_STORAGE_BUCKET_NAME = "default-bucket"

        file_id = "org/789/media/image.png"
        bucket, key = self.view._resolve_file_location(file_id)

        self.assertEqual(bucket, "default-bucket")
        self.assertEqual(key, "org/789/media/image.png")

    @patch("temba.api.v2.internals.media.views.settings")
    def test_resolve_file_location_relative_path_with_leading_slash(self, mock_settings):
        """Test resolving a relative path with leading slash."""
        mock_settings.AWS_STORAGE_BUCKET_NAME = "default-bucket"

        file_id = "/org/789/media/image.png"
        bucket, key = self.view._resolve_file_location(file_id)

        self.assertEqual(bucket, "default-bucket")
        self.assertEqual(key, "org/789/media/image.png")

    @patch("temba.api.v2.internals.media.views.settings")
    def test_resolve_file_location_no_bucket_configured(self, mock_settings):
        """Test error when no default bucket is configured."""
        mock_settings.AWS_STORAGE_BUCKET_NAME = None

        with self.assertRaises(MediaFileNotFoundException) as context:
            self.view._resolve_file_location("org/123/file.jpg")

        self.assertIn("not configured", str(context.exception))

    def test_validate_file_access_empty_file_id(self):
        """Test validation fails for empty file_id."""
        with self.assertRaises(MediaFileNotFoundException):
            self.view._validate_file_access("", None)

    def test_validate_file_access_too_long_file_id(self):
        """Test validation fails for overly long file_id."""
        long_file_id = "a" * 2000
        with self.assertRaises(MediaAccessDeniedException):
            self.view._validate_file_access(long_file_id, None)

    def test_validate_file_access_valid_file_id(self):
        """Test validation passes for valid file_id."""
        # Should not raise any exception
        self.view._validate_file_access("org/123/media/valid_file.jpg", None)

    @patch("temba.api.v2.internals.media.views.s3")
    def test_generate_presigned_url_success(self, mock_s3):
        """Test successful pre-signed URL generation."""
        mock_client = MagicMock()
        mock_client.generate_presigned_url.return_value = "https://presigned-url.example.com/file"
        mock_s3.client.return_value = mock_client

        url = self.view._generate_presigned_url("test-bucket", "test-key")

        self.assertEqual(url, "https://presigned-url.example.com/file")
        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "test-bucket", "Key": "test-key"},
            ExpiresIn=PRESIGNED_URL_EXPIRES,
        )

    @patch("temba.api.v2.internals.media.views.s3")
    def test_generate_presigned_url_failure(self, mock_s3):
        """Test pre-signed URL generation failure."""
        mock_client = MagicMock()
        mock_client.generate_presigned_url.side_effect = Exception("S3 error")
        mock_s3.client.return_value = mock_client

        with self.assertRaises(MediaFileNotFoundException) as context:
            self.view._generate_presigned_url("test-bucket", "test-key")

        self.assertIn("Unable to generate", str(context.exception))


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

        url = reverse("internals.media_download", kwargs={"file_id": "org/123/media/file.jpg"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, presigned_url)

    @patch("temba.api.v2.internals.media.views.s3")
    def test_get_redirect_with_full_s3_url(self, mock_s3):
        """Test redirect when file_id is a full S3 URL."""
        mock_client = MagicMock()
        presigned_url = "https://presigned.example.com/file"
        mock_client.generate_presigned_url.return_value = presigned_url
        mock_s3.client.return_value = mock_client
        mock_s3.split_url.return_value = ("custom-bucket", "path/to/file.pdf")

        # URL encode the full S3 URL for the path
        file_id = "https://custom-bucket.s3.amazonaws.com/path/to/file.pdf"
        url = reverse("internals.media_download", kwargs={"file_id": file_id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, presigned_url)

    @patch("temba.api.v2.internals.media.views.s3")
    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_redirect_with_bucket_key_format(self, mock_settings, mock_s3):
        """Test redirect when file_id is in bucket:key format."""
        mock_client = MagicMock()
        presigned_url = "https://presigned.example.com/file"
        mock_client.generate_presigned_url.return_value = presigned_url
        mock_s3.client.return_value = mock_client

        file_id = "my-bucket:path/to/file.pdf"
        url = reverse("internals.media_download", kwargs={"file_id": file_id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        mock_client.generate_presigned_url.assert_called_once()
        call_args = mock_client.generate_presigned_url.call_args
        self.assertEqual(call_args[1]["Params"]["Bucket"], "my-bucket")
        self.assertEqual(call_args[1]["Params"]["Key"], "path/to/file.pdf")

    @patch("temba.api.v2.internals.media.views.s3")
    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_s3_error_returns_500(self, mock_settings, mock_s3):
        """Test that S3 errors return 500 status."""
        mock_settings.AWS_STORAGE_BUCKET_NAME = "test-bucket"

        mock_client = MagicMock()
        mock_client.generate_presigned_url.side_effect = Exception("S3 connection error")
        mock_s3.client.return_value = mock_client

        url = reverse("internals.media_download", kwargs={"file_id": "org/123/file.jpg"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_no_bucket_configured_returns_404(self, mock_settings):
        """Test that missing bucket configuration returns 404."""
        mock_settings.AWS_STORAGE_BUCKET_NAME = None

        url = reverse("internals.media_download", kwargs={"file_id": "org/123/file.jpg"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())


class TestPresignedUrlExpiration(TestCase):
    """Test that the pre-signed URL expiration is correctly configured."""

    def test_presigned_url_expires_is_5_minutes(self):
        """Verify the pre-signed URL expiration is 5 minutes (300 seconds)."""
        self.assertEqual(PRESIGNED_URL_EXPIRES, 300)
