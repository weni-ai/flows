import uuid
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
from rest_framework.test import APIClient

from django.test import TestCase, override_settings
from django.urls import reverse

from temba.tests.base import TembaTest

from .exceptions import (
    EmptyFileIdException,
    FileNotFoundInAnyBucketException,
    InvalidFileIdFormatException,
    S3BucketNotConfiguredException,
)
from .views import PRESIGNED_URL_EXPIRES, S3MediaProxyView


class TestS3MediaProxyView(TembaTest):
    """Tests for the S3 Media Proxy endpoint."""

    def setUp(self):
        super().setUp()
        self.view = S3MediaProxyView()

    def test_validate_object_key_empty(self):
        with self.assertRaises(EmptyFileIdException) as context:
            self.view._validate_object_key("")

        self.assertEqual(str(context.exception), EmptyFileIdException.message)

    def test_validate_object_key_too_long(self):
        long_object_key = "a" * 2000
        with self.assertRaises(InvalidFileIdFormatException) as context:
            self.view._validate_object_key(long_object_key)

        self.assertEqual(str(context.exception), InvalidFileIdFormatException.message)

    def test_validate_object_key_valid(self):
        self.view._validate_object_key("media/image.jpg")

    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_buckets_primary_only(self, mock_settings):
        mock_settings.AWS_STORAGE_BUCKET_NAME = "primary-bucket"
        mock_settings.S3_MEDIA_BUCKETS = []

        buckets = self.view._get_buckets()

        self.assertEqual(buckets, ["primary-bucket"])

    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_buckets_additional_come_before_primary(self, mock_settings):
        mock_settings.AWS_STORAGE_BUCKET_NAME = "primary-bucket"
        mock_settings.S3_MEDIA_BUCKETS = ["media-bucket", "attachments-bucket"]

        buckets = self.view._get_buckets()

        self.assertEqual(buckets, ["media-bucket", "attachments-bucket", "primary-bucket"])

    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_buckets_deduplicates(self, mock_settings):
        mock_settings.AWS_STORAGE_BUCKET_NAME = "my-bucket"
        mock_settings.S3_MEDIA_BUCKETS = ["my-bucket", "other-bucket"]

        buckets = self.view._get_buckets()

        self.assertEqual(buckets, ["my-bucket", "other-bucket"])

    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_buckets_no_primary_uses_additional(self, mock_settings):
        mock_settings.AWS_STORAGE_BUCKET_NAME = None
        mock_settings.S3_MEDIA_BUCKETS = ["media-bucket"]

        buckets = self.view._get_buckets()

        self.assertEqual(buckets, ["media-bucket"])

    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_buckets_none_configured(self, mock_settings):
        mock_settings.AWS_STORAGE_BUCKET_NAME = None
        mock_settings.S3_MEDIA_BUCKETS = []

        with self.assertRaises(S3BucketNotConfiguredException):
            self.view._get_buckets()

    @patch("temba.api.v2.internals.media.views.s3")
    def test_find_in_first_bucket(self, mock_s3):
        mock_client = MagicMock()
        mock_client.head_object.return_value = {}
        mock_client.generate_presigned_url.return_value = "https://presigned.example.com/file"
        mock_s3.client.return_value = mock_client

        url = self.view._find_and_generate_presigned_url(["bucket-a", "bucket-b"], "media/image.jpg")

        self.assertEqual(url, "https://presigned.example.com/file")
        mock_client.head_object.assert_called_once_with(Bucket="bucket-a", Key="media/image.jpg")
        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "bucket-a", "Key": "media/image.jpg"},
            ExpiresIn=PRESIGNED_URL_EXPIRES,
        )

    @patch("temba.api.v2.internals.media.views.s3")
    def test_find_in_second_bucket(self, mock_s3):
        mock_client = MagicMock()
        not_found_error = ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        mock_client.head_object.side_effect = [not_found_error, {}]
        mock_client.generate_presigned_url.return_value = "https://presigned.example.com/file"
        mock_s3.client.return_value = mock_client

        url = self.view._find_and_generate_presigned_url(["bucket-a", "bucket-b"], "media/image.jpg")

        self.assertEqual(url, "https://presigned.example.com/file")
        self.assertEqual(mock_client.head_object.call_count, 2)
        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "bucket-b", "Key": "media/image.jpg"},
            ExpiresIn=PRESIGNED_URL_EXPIRES,
        )

    @patch("temba.api.v2.internals.media.views.s3")
    def test_find_not_in_any_bucket(self, mock_s3):
        mock_client = MagicMock()
        not_found_error = ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        mock_client.head_object.side_effect = not_found_error
        mock_s3.client.return_value = mock_client

        with self.assertRaises(FileNotFoundInAnyBucketException):
            self.view._find_and_generate_presigned_url(["bucket-a", "bucket-b"], "media/missing.jpg")

        self.assertEqual(mock_client.head_object.call_count, 2)

    @patch("temba.api.v2.internals.media.views.s3")
    def test_find_skips_bucket_on_unexpected_error(self, mock_s3):
        """If head_object raises a non-404 error, skip that bucket and try the next."""
        mock_client = MagicMock()
        access_denied = ClientError({"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadObject")
        mock_client.head_object.side_effect = [access_denied, {}]
        mock_client.generate_presigned_url.return_value = "https://presigned.example.com/file"
        mock_s3.client.return_value = mock_client

        url = self.view._find_and_generate_presigned_url(["restricted-bucket", "open-bucket"], "media/image.jpg")

        self.assertEqual(url, "https://presigned.example.com/file")
        self.assertEqual(mock_client.head_object.call_count, 2)


@override_settings(
    OIDC_OP_TOKEN_ENDPOINT="https://example.com/token",
    OIDC_OP_USER_ENDPOINT="https://example.com/user",
    OIDC_RP_CLIENT_ID="test-client-id",
    OIDC_RP_CLIENT_SECRET="test-client-secret",
)
class TestS3MediaProxyEndpoint(TembaTest):
    """Integration tests for the S3 Media Proxy endpoint."""

    def setUp(self):
        super().setUp()
        self.org.proj_uuid = uuid.uuid4()
        self.org.save(update_fields=("proj_uuid",))
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _download_url(self, object_key):
        return reverse("internals.media_download", kwargs={"object_key": object_key})

    def _get(self, object_key, *, project_uuid="default", client=None, **extra_params):
        client = client or self.client
        params = dict(extra_params)
        if project_uuid == "default":
            params["project_uuid"] = str(self.org.proj_uuid)
        elif project_uuid is not None:
            params["project_uuid"] = project_uuid
        return client.get(self._download_url(object_key), params)

    def _mock_found(self, mock_settings, mock_s3, presigned_url):
        mock_settings.AWS_STORAGE_BUCKET_NAME = "test-bucket"
        mock_settings.S3_MEDIA_BUCKETS = []

        mock_client = MagicMock()
        mock_client.head_object.return_value = {}
        mock_client.generate_presigned_url.return_value = presigned_url
        mock_s3.client.return_value = mock_client
        return mock_client

    @patch("temba.api.v2.internals.media.views.s3")
    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_redirect_success(self, mock_settings, mock_s3):
        mock_settings.AWS_STORAGE_BUCKET_NAME = "test-bucket"
        mock_settings.S3_MEDIA_BUCKETS = []

        mock_client = MagicMock()
        mock_client.head_object.return_value = {}
        presigned_url = "https://test-bucket.s3.amazonaws.com/presigned?signature=abc123"
        mock_client.generate_presigned_url.return_value = presigned_url
        mock_s3.client.return_value = mock_client

        response = self._get("media/image.jpg")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, presigned_url)

    @patch("temba.api.v2.internals.media.views.s3")
    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_redirect_found_in_fallback_bucket(self, mock_settings, mock_s3):
        """File not in S3_MEDIA_BUCKETS but found in AWS_STORAGE_BUCKET_NAME (fallback)."""
        mock_settings.AWS_STORAGE_BUCKET_NAME = "primary-bucket"
        mock_settings.S3_MEDIA_BUCKETS = ["media-bucket"]

        mock_client = MagicMock()
        not_found = ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        mock_client.head_object.side_effect = [not_found, {}]
        presigned_url = "https://primary-bucket.s3.amazonaws.com/presigned?signature=xyz"
        mock_client.generate_presigned_url.return_value = presigned_url
        mock_s3.client.return_value = mock_client

        response = self._get("attachments/file.pdf")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, presigned_url)
        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "primary-bucket", "Key": "attachments/file.pdf"},
            ExpiresIn=PRESIGNED_URL_EXPIRES,
        )

    @patch("temba.api.v2.internals.media.views.s3")
    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_not_found_in_any_bucket(self, mock_settings, mock_s3):
        mock_settings.AWS_STORAGE_BUCKET_NAME = "bucket-a"
        mock_settings.S3_MEDIA_BUCKETS = ["bucket-b", "bucket-c"]

        mock_client = MagicMock()
        not_found = ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        mock_client.head_object.side_effect = not_found
        mock_s3.client.return_value = mock_client

        response = self._get("media/missing.jpg")

        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())
        self.assertEqual(mock_client.head_object.call_count, 3)

    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_no_bucket_configured_returns_404(self, mock_settings):
        mock_settings.AWS_STORAGE_BUCKET_NAME = None
        mock_settings.S3_MEDIA_BUCKETS = []

        response = self._get("media/file.jpg")

        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_invalid_object_key_returns_403(self, mock_settings):
        mock_settings.AWS_STORAGE_BUCKET_NAME = "test-bucket"
        mock_settings.S3_MEDIA_BUCKETS = []

        long_key = "a" * 2000
        response = self._get(long_key)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "Access denied")

    @patch("temba.api.v2.internals.media.views.S3MediaProxyView._validate_object_key")
    def test_get_unexpected_error_returns_500(self, mock_validate):
        mock_validate.side_effect = RuntimeError("unexpected failure")

        response = self._get("media/file.jpg")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"], "Internal server error")

    def test_get_unauthenticated_returns_401(self):
        client = APIClient()
        response = self._get("media/image.jpg", client=client)

        self.assertEqual(response.status_code, 401)

    def test_get_user_not_in_org_returns_403(self):
        client = APIClient()
        client.force_authenticate(user=self.non_org_user)
        response = self._get("media/image.jpg", client=client)

        self.assertEqual(response.status_code, 403)

    def test_get_viewer_returns_403(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        response = self._get("media/image.jpg", client=client)

        self.assertEqual(response.status_code, 403)

    @patch("temba.api.v2.internals.media.views.s3")
    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_editor_redirect_success(self, mock_settings, mock_s3):
        mock_settings.AWS_STORAGE_BUCKET_NAME = "test-bucket"
        mock_settings.S3_MEDIA_BUCKETS = []

        mock_client = MagicMock()
        mock_client.head_object.return_value = {}
        presigned_url = "https://test-bucket.s3.amazonaws.com/presigned?signature=editor"
        mock_client.generate_presigned_url.return_value = presigned_url
        mock_s3.client.return_value = mock_client

        client = APIClient()
        client.force_authenticate(user=self.editor)
        response = self._get("media/image.jpg", client=client)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, presigned_url)

    @patch("temba.api.v2.internals.media.views.s3")
    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_agent_redirect_success(self, mock_settings, mock_s3):
        presigned_url = "https://test-bucket.s3.amazonaws.com/presigned?signature=agent"
        self._mock_found(mock_settings, mock_s3, presigned_url)

        client = APIClient()
        client.force_authenticate(user=self.agent)
        response = self._get("media/image.jpg", client=client)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, presigned_url)

    def test_get_surveyor_returns_403(self):
        client = APIClient()
        client.force_authenticate(user=self.surveyor)
        response = self._get("media/image.jpg", client=client)

        self.assertEqual(response.status_code, 403)

    @patch("temba.api.v2.internals.media.views.s3")
    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_json_response_returns_url(self, mock_settings, mock_s3):
        presigned_url = "https://test-bucket.s3.amazonaws.com/presigned?signature=json"
        self._mock_found(mock_settings, mock_s3, presigned_url)

        response = self._get("media/image.jpg", response="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"url": presigned_url})
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("temba.api.v2.internals.media.views.s3")
    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_json_response_not_found_returns_404(self, mock_settings, mock_s3):
        mock_settings.AWS_STORAGE_BUCKET_NAME = "test-bucket"
        mock_settings.S3_MEDIA_BUCKETS = []

        mock_client = MagicMock()
        mock_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
        )
        mock_s3.client.return_value = mock_client

        response = self._get("media/missing.jpg", response="json")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"error": "File not found"})

    @patch("temba.api.v2.internals.media.views.s3")
    @patch("temba.api.v2.internals.media.views.settings")
    def test_get_unknown_response_value_still_redirects(self, mock_settings, mock_s3):
        presigned_url = "https://test-bucket.s3.amazonaws.com/presigned?signature=foo"
        self._mock_found(mock_settings, mock_s3, presigned_url)

        response = self._get("media/image.jpg", response="foo")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, presigned_url)

    def test_get_missing_project_returns_400(self):
        response = self._get("media/file.jpg", project_uuid=None)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Project UUID not provided")

    def test_get_unknown_project_returns_403(self):
        response = self._get("media/file.jpg", project_uuid="00000000-0000-0000-0000-000000000000")

        self.assertEqual(response.status_code, 403)


class TestPresignedUrlExpiration(TestCase):
    def test_presigned_url_expires_is_5_minutes(self):
        self.assertEqual(PRESIGNED_URL_EXPIRES, 300)
