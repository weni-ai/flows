from datetime import date
from uuid import uuid4

from django.test import SimpleTestCase

from temba.api.v2.internals.conversion_events.serializers import (
    CtwaReferralSourceSerializer,
    ListCtwaReferralSourceQuerySerializer,
)
from temba.conversion_events.models import CtwaReferralSource
from temba.tests import TembaTest


class ListCtwaReferralSourceQuerySerializerTest(SimpleTestCase):
    def test_requires_project_uuid(self):
        serializer = ListCtwaReferralSourceQuerySerializer(data={})
        self.assertFalse(serializer.is_valid())
        self.assertIn("project_uuid", serializer.errors)

    def test_rejects_invalid_project_uuid(self):
        serializer = ListCtwaReferralSourceQuerySerializer(data={"project_uuid": "not-a-uuid"})
        self.assertFalse(serializer.is_valid())
        self.assertIn("project_uuid", serializer.errors)

    def test_rejects_invalid_source_type(self):
        serializer = ListCtwaReferralSourceQuerySerializer(
            data={"project_uuid": str(uuid4()), "source_type": "story"}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("source_type", serializer.errors)

    def test_rejects_invalid_after_date(self):
        serializer = ListCtwaReferralSourceQuerySerializer(
            data={"project_uuid": str(uuid4()), "after": "not-a-date"}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("after", serializer.errors)

    def test_rejects_invalid_before_date(self):
        serializer = ListCtwaReferralSourceQuerySerializer(
            data={"project_uuid": str(uuid4()), "before": "not-a-date"}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("before", serializer.errors)

    def test_rejects_after_greater_than_before(self):
        serializer = ListCtwaReferralSourceQuerySerializer(
            data={
                "project_uuid": str(uuid4()),
                "after": "2026-01-03",
                "before": "2026-01-02",
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("non_field_errors", serializer.errors)

    def test_parses_iso8601_datetimes_to_dates(self):
        serializer = ListCtwaReferralSourceQuerySerializer(
            data={
                "project_uuid": str(uuid4()),
                "after": "2026-01-15T10:00:00Z",
                "before": "2026-01-16T10:00:00Z",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["after"], date(2026, 1, 15))
        self.assertEqual(serializer.validated_data["before"], date(2026, 1, 16))

    def test_accepts_valid_source_type(self):
        serializer = ListCtwaReferralSourceQuerySerializer(
            data={
                "project_uuid": str(uuid4()),
                "source_type": CtwaReferralSource.SOURCE_TYPE_POST,
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["source_type"], CtwaReferralSource.SOURCE_TYPE_POST)


class CtwaReferralSourceSerializerTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.org.proj_uuid = uuid4()
        self.org.save(update_fields=["proj_uuid"])

    def test_serializes_all_model_fields_without_conversion_events(self):
        source, _ = CtwaReferralSource.get_or_create_for_org(
            self.org,
            "ad-1",
            CtwaReferralSource.SOURCE_TYPE_AD,
            source_url="https://example.com/ad",
            headline="Headline",
            body="Body",
        )
        data = CtwaReferralSourceSerializer(source).data

        self.assertEqual(
            set(data.keys()),
            {
                "id",
                "org",
                "project_uuid",
                "source_id",
                "source_type",
                "source_url",
                "headline",
                "body",
                "first_seen_at",
                "last_seen_at",
                "created_at",
                "updated_at",
            },
        )
        self.assertEqual(data["id"], source.id)
        self.assertEqual(data["org"], self.org.id)
        self.assertEqual(data["project_uuid"], str(self.org.proj_uuid))
        self.assertEqual(data["source_id"], "ad-1")
        self.assertEqual(data["source_type"], CtwaReferralSource.SOURCE_TYPE_AD)
        self.assertEqual(data["source_url"], "https://example.com/ad")
        self.assertEqual(data["headline"], "Headline")
        self.assertEqual(data["body"], "Body")
        self.assertNotIn("conversion_events", data)
