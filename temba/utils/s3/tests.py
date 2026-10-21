import io
from datetime import datetime
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytz

from django.test import override_settings

from temba.tests import TembaTest
from temba.tests.s3 import S3_SIGNING_SETTINGS, MockEventStream, MockS3Client
from temba.utils.s3 import (
    EventStreamReader,
    S3Location,
    compile_select,
    get_body,
    matches_where,
    parse_s3_url,
    presign_attachment,
    presign_url,
    regional_client,
    split_url,
)


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


@override_settings(**S3_SIGNING_SETTINGS)
class PresignTest(TembaTest):
    def setUp(self):
        super().setUp()

        regional_client.cache_clear()

    def assertPresigned(self, url: str, host: str, path: str, region: str, expires: int = 600) -> dict:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        self.assertEqual(host, parsed.hostname)
        self.assertEqual(path, parsed.path)
        self.assertEqual(["AWS4-HMAC-SHA256"], query["X-Amz-Algorithm"])
        self.assertEqual([str(expires)], query["X-Amz-Expires"])
        self.assertTrue(query["X-Amz-Credential"][0].endswith(f"/{region}/s3/aws4_request"))
        self.assertIn("X-Amz-Signature", query)
        return query

    def test_parse_s3_url(self):
        self.assertEqual(
            S3Location("media-bucket", "media/photo.jpg", None),
            parse_s3_url("https://media-bucket.s3.amazonaws.com/media/photo.jpg"),
        )
        self.assertEqual(
            S3Location("media-bucket", "media/photo.jpg", "sa-east-1"),
            parse_s3_url("https://media-bucket.s3.sa-east-1.amazonaws.com/media/photo.jpg"),
        )
        self.assertEqual(
            S3Location("media-bucket", "media/photo.jpg", "sa-east-1"),
            parse_s3_url("https://media-bucket.s3-sa-east-1.amazonaws.com/media/photo.jpg"),
        )
        self.assertEqual(
            S3Location("my.dotted.bucket", "photo.jpg", "us-west-2"),
            parse_s3_url("https://my.dotted.bucket.s3.us-west-2.amazonaws.com/photo.jpg"),
        )

        # path-style
        self.assertEqual(
            S3Location("media-bucket", "media/photo.jpg", None),
            parse_s3_url("https://s3.amazonaws.com/media-bucket/media/photo.jpg"),
        )
        self.assertEqual(
            S3Location("media-bucket", "media/photo.jpg", "sa-east-1"),
            parse_s3_url("https://s3.sa-east-1.amazonaws.com/media-bucket/media/photo.jpg"),
        )
        self.assertEqual(
            S3Location("media-bucket", "media/photo.jpg", "sa-east-1"),
            parse_s3_url("https://s3-sa-east-1.amazonaws.com/media-bucket/media/photo.jpg"),
        )

        # AWS_BUCKET_DOMAIN maps to AWS_STORAGE_BUCKET_NAME
        self.assertEqual(
            S3Location("static-bucket", "orgs/1/media/photo.jpg", None),
            parse_s3_url("https://static.example.com/orgs/1/media/photo.jpg"),
        )

        # query strings from previously signed URLs are dropped and keys are unquoted
        self.assertEqual(
            S3Location("media-bucket", "media/my photo.jpg", "sa-east-1"),
            parse_s3_url(
                "https://media-bucket.s3.sa-east-1.amazonaws.com/media/my%20photo.jpg?X-Amz-Signature=abc&X-Amz-Expires=1"
            ),
        )

        # not S3 or missing bucket or key
        self.assertIsNone(parse_s3_url("https://example.com/photo.jpg"))
        self.assertIsNone(parse_s3_url("https://media-bucket.s3.amazonaws.com/"))
        self.assertIsNone(parse_s3_url("https://s3.amazonaws.com/media-bucket"))
        self.assertIsNone(parse_s3_url("https://static.example.com/"))
        self.assertIsNone(parse_s3_url("-35.998287,26.478109"))
        self.assertIsNone(parse_s3_url(""))

    def test_presign_url(self):
        # region from the URL wins over AWS_S3_REGION_NAME
        query = self.assertPresigned(
            presign_url("https://media-bucket.s3.us-west-2.amazonaws.com/media/my%20photo.jpg"),
            "media-bucket.s3.us-west-2.amazonaws.com",
            "/media/my%20photo.jpg",
            "us-west-2",
        )
        self.assertNotIn("response-content-disposition", query)

        # region falls back to AWS_S3_REGION_NAME, and previous signatures are replaced
        query = self.assertPresigned(
            presign_url("https://attachments-bucket.s3.amazonaws.com/media/a.ogg?X-Amz-Signature=stale"),
            "attachments-bucket.s3.sa-east-1.amazonaws.com",
            "/media/a.ogg",
            "sa-east-1",
        )
        self.assertNotEqual(["stale"], query["X-Amz-Signature"])

        self.assertPresigned(
            presign_url("https://static.example.com/orgs/1/media/photo.jpg"),
            "static-bucket.s3.sa-east-1.amazonaws.com",
            "/orgs/1/media/photo.jpg",
            "sa-east-1",
        )

        query = self.assertPresigned(
            presign_url(
                "https://media-bucket.s3.amazonaws.com/media/photo.jpg",
                expires=30,
                response_content_disposition="attachment",
            ),
            "media-bucket.s3.sa-east-1.amazonaws.com",
            "/media/photo.jpg",
            "sa-east-1",
            expires=30,
        )
        self.assertEqual(["attachment"], query["response-content-disposition"])

        # URLs outside our buckets are returned unchanged
        self.assertEqual(
            "https://other-bucket.s3.amazonaws.com/photo.jpg",
            presign_url("https://other-bucket.s3.amazonaws.com/photo.jpg"),
        )
        self.assertEqual("https://example.com/photo.jpg", presign_url("https://example.com/photo.jpg"))

    def test_presign_url_reuses_regional_clients(self):
        presign_url("https://media-bucket.s3.amazonaws.com/a.jpg")
        presign_url("https://media-bucket.s3.amazonaws.com/b.jpg")
        presign_url("https://media-bucket.s3.us-west-2.amazonaws.com/c.jpg")

        self.assertEqual(2, regional_client.cache_info().currsize)

    def test_presign_attachment(self):
        signed_attachment = presign_attachment("image/jpeg:https://media-bucket.s3.amazonaws.com/a.jpg")
        content_type, _, url = signed_attachment.partition(":")
        self.assertEqual("image/jpeg", content_type)
        self.assertPresigned(url, "media-bucket.s3.sa-east-1.amazonaws.com", "/a.jpg", "sa-east-1")

        self.assertEqual("geo:-35.998287,26.478109", presign_attachment("geo:-35.998287,26.478109"))
        self.assertEqual(
            "image/jpeg:https://example.com/a.jpg", presign_attachment("image/jpeg:https://example.com/a.jpg")
        )
        self.assertEqual("image/jpeg", presign_attachment("image/jpeg"))


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

    def test_matches_where(self):
        record = {
            "id": 123,
            "responded": True,
            "flow": {"uuid": "1234", "name": "Test"},
            "created_on": "2021-09-28T18:27:30.123456+00:00",
        }

        # no where always matches
        self.assertTrue(matches_where(record))
        self.assertTrue(matches_where(record, where={}))

        # exact match on top-level and nested fields
        self.assertTrue(matches_where(record, where={"id": 123}))
        self.assertFalse(matches_where(record, where={"id": 456}))
        self.assertTrue(matches_where(record, where={"responded": True}))
        self.assertTrue(matches_where(record, where={"flow__uuid": "1234"}))
        self.assertFalse(matches_where(record, where={"flow__uuid": "9999"}))

        # comparison lookups
        self.assertTrue(matches_where(record, where={"id__gt": 100}))
        self.assertFalse(matches_where(record, where={"id__gt": 200}))
        self.assertTrue(matches_where(record, where={"id__gte": 123, "id__lte": 123}))

        # IN lookup
        self.assertTrue(matches_where(record, where={"flow__uuid__in": ("1234", "2345")}))
        self.assertFalse(matches_where(record, where={"flow__uuid__in": ("2345",)}))

        # datetime values compared against ISO string fields
        self.assertTrue(matches_where(record, where={"created_on__gt": datetime(2021, 9, 28, 0, 0, 0, 0, pytz.UTC)}))
        self.assertFalse(matches_where(record, where={"created_on__gt": datetime(2021, 9, 29, 0, 0, 0, 0, pytz.UTC)}))

        # all conditions must match
        self.assertTrue(matches_where(record, where={"flow__uuid": "1234", "responded": True}))
        self.assertFalse(matches_where(record, where={"flow__uuid": "1234", "responded": False}))

        # a missing field never matches any lookup, consistently across operators
        self.assertFalse(matches_where(record, where={"missing__gt": 1}))
        self.assertFalse(matches_where(record, where={"missing": None}))
        self.assertFalse(matches_where(record, where={"missing__in": (1, 2)}))
        self.assertFalse(matches_where(record, where={"missing__in": (None, 1)}))

        # raw expressions can't be evaluated locally
        with self.assertRaises(ValueError):
            matches_where(record, where={"__raw__": "s.id < 3"})
