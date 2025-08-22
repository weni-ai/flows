import io
from datetime import datetime
from unittest.mock import patch

import pytz

from temba.tests import TembaTest
from temba.tests.s3 import MockEventStream, MockS3Client
from temba.utils.s3 import EventStreamReader, compile_select, get_body, split_url

from django.test import TestCase, override_settings

from . import presigned


class S3Test(TembaTest):
    def test_buffer(self):
        # empty payload
        stream = MockEventStream(records=[], max_payload_size=256)

        buffer = EventStreamReader(stream)
        self.assertEqual([], list(buffer))

        # single record that fits in single payload
        stream = MockEventStream(records=[{"id": 1, "text": "Hi"}], max_payload_size=256)

        buffer = EventStreamReader(stream)
        self.assertEqual([{"id": 1, "text": "Hi"}], list(buffer))

        # multiple records that will be split across several small payloads
        stream = MockEventStream(
            records=[{"id": 1, "text": "Hi"}, {"id": 2, "text": "Hi"}, {"id": 3, "text": "Hi"}], max_payload_size=5
        )

        buffer = EventStreamReader(stream)
        self.assertEqual([{"id": 1, "text": "Hi"}, {"id": 2, "text": "Hi"}, {"id": 3, "text": "Hi"}], list(buffer))

    def test_split(self):
        bucket, url = split_url("https://foo.s3.aws.amazon.com/test/12345")
        self.assertEqual("foo", bucket)
        self.assertEqual("test/12345", url)

    def test_get_body(self):
        mock_s3 = MockS3Client()
        mock_s3.objects[("foo", "test/12345")] = io.StringIO("12345_content")

        with patch("temba.utils.s3.s3.client", return_value=mock_s3):
            body = get_body("https://foo.s3.aws.amazon.com/test/12345")
            self.assertEqual(body, "12345_content")


class SelectTest(TembaTest):
    def test_compile_select(self):
        self.assertEqual("SELECT s.* FROM s3object s", compile_select())
        self.assertEqual("SELECT m.* FROM s3object m", compile_select(alias="m"))
        self.assertEqual(
            "SELECT s.name, s.contact.uuid FROM s3object s", compile_select(fields=["name", "contact__uuid"])
        )
        self.assertEqual(
            "SELECT c.* FROM s3object c WHERE c.uuid = '12345'", compile_select(alias="c", where={"uuid": "12345"})
        )
        self.assertEqual(
            "SELECT s.* FROM s3object s WHERE s.contact.uuid = '12345'",
            compile_select(where={"contact__uuid": "12345"}),
        )
        self.assertEqual(
            "SELECT s.* FROM s3object s WHERE s.uuid = '12345' AND s.id = 123 AND s.active = TRUE",
            compile_select(where={"uuid": "12345", "id": 123, "active": True}),
        )
        self.assertEqual(
            "SELECT s.* FROM s3object s WHERE CAST(s.created_on AS TIMESTAMP) > CAST('2021-09-28T18:27:30.123456+00:00' AS TIMESTAMP)",
            compile_select(where={"created_on__gt": datetime(2021, 9, 28, 18, 27, 30, 123456, pytz.UTC)}),
        )
        self.assertEqual(
            "SELECT s.* FROM s3object s WHERE CAST(s.modified_on AS TIMESTAMP) <= CAST('2021-09-28T18:27:30.123456+00:00' AS TIMESTAMP)",
            compile_select(where={"modified_on__lte": datetime(2021, 9, 28, 18, 27, 30, 123456, pytz.UTC)}),
        )
        self.assertEqual(
            "SELECT s.* FROM s3object s WHERE s.flow.uuid IN ('1234', '2345')",
            compile_select(where={"flow__uuid__in": ("1234", "2345")}),
        )

        # a where clause can also be raw S3-select-SQL (used by search_archives command)
        self.assertEqual(
            "SELECT s.* FROM s3object s WHERE s.uuid = '2345' AND s.contact.uuid = '1234'",
            compile_select(where={"uuid": "2345", "__raw__": "s.contact.uuid = '1234'"}),
        )
        self.assertEqual(
            "SELECT s.* FROM s3object s WHERE '1ccf09f6-3fe8-4c0d-a073-981632be5a30' IN s.labels[*].uuid[*]",
            compile_select(where={"__raw__": "'1ccf09f6-3fe8-4c0d-a073-981632be5a30' IN s.labels[*].uuid[*]"}),
        )


class PresignedURLTest(TestCase):
    @override_settings(
        AWS_STORAGE_BUCKET_NAME="test-bucket",
    )
    @patch("temba.utils.s3.s3.client")
    def test_generate_presigned_url(self, mock_client):
        # Setup mock S3 client
        mock_s3 = mock_client.return_value
        mock_s3.generate_presigned_url.return_value = "https://test-bucket.s3.amazonaws.com/test.txt?signature=xyz"

        # Test basic URL generation
        url = presigned.generate_presigned_url("test.txt")
        self.assertEqual(url, "https://test-bucket.s3.amazonaws.com/test.txt?signature=xyz")
        
        mock_s3.generate_presigned_url.assert_called_with(
            "get_object",
            Params={"Bucket": "test-bucket", "Key": "test.txt"},
            ExpiresIn=3600,
            HttpMethod="GET"
        )

        # Test with custom headers
        headers = presigned.get_download_headers("myfile.pdf", "application/pdf")
        url = presigned.generate_presigned_url("test.pdf", response_headers=headers)
        
        mock_s3.generate_presigned_url.assert_called_with(
            "get_object",
            Params={
                "Bucket": "test-bucket",
                "Key": "test.pdf",
                "ResponseContentDisposition": "attachment; filename=myfile.pdf",
                "ResponseContentType": "application/pdf"
            },
            ExpiresIn=3600,
            HttpMethod="GET"
        )

    def test_get_download_headers(self):
        # Test basic headers
        headers = presigned.get_download_headers("test.txt")
        self.assertEqual(headers, {
            "ContentDisposition": "attachment; filename=test.txt"
        })

        # Test with content type
        headers = presigned.get_download_headers("test.pdf", "application/pdf")
        self.assertEqual(headers, {
            "ContentDisposition": "attachment; filename=test.pdf",
            "ContentType": "application/pdf"
        })
