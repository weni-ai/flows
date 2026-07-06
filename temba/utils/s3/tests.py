import io
from datetime import datetime
from unittest.mock import patch

import pytz

from temba.tests import TembaTest
from temba.tests.s3 import MockEventStream, MockS3Client
from temba.utils.s3 import EventStreamReader, compile_select, get_body, matches_where, split_url


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
