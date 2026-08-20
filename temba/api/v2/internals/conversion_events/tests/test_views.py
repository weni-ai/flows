from datetime import datetime, timedelta
from functools import wraps
from unittest.mock import patch
from uuid import uuid4

import pytz
from rest_framework.authentication import BasicAuthentication, SessionAuthentication

from django.urls import reverse
from django.utils import timezone

from temba.conversion_events.models import CTWA, CtwaReferralSource
from temba.tests import TembaTest

VIEW_PATH = "temba.api.v2.internals.conversion_events.views.CtwaReferralSourceListView"


def skip_auth_and_permissions(func):
    @patch(f"{VIEW_PATH}.authentication_classes", [SessionAuthentication])
    @patch(f"{VIEW_PATH}.permission_classes", [])
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


class CtwaReferralSourceListViewTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.org.proj_uuid = uuid4()
        self.org.save(update_fields=["proj_uuid"])
        self.org2.proj_uuid = uuid4()
        self.org2.save(update_fields=["proj_uuid"])
        self.url = reverse("internal-ctwa-referral-sources")

    def _create_source(
        self, org, source_id, source_type=CtwaReferralSource.SOURCE_TYPE_AD, last_seen_at=None, **defaults
    ):
        source, _ = CtwaReferralSource.get_or_create_for_org(org, source_id, source_type, **defaults)
        if last_seen_at is not None:
            CtwaReferralSource.objects.filter(id=source.id).update(last_seen_at=last_seen_at)
            source.refresh_from_db()
        return source

    def _get(self, **params):
        self.client.force_login(self.user)
        return self.client.get(self.url, data=params)

    @patch(f"{VIEW_PATH}.authentication_classes", [BasicAuthentication])
    def test_requires_authentication(self):
        resp = self.client.get(self.url, data={"project_uuid": str(self.org.proj_uuid)})
        self.assertEqual(resp.status_code, 401)

    @skip_auth_and_permissions
    def test_missing_project_uuid_returns_400(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 400)
        self.assertIn("project_uuid", resp.json())

    @skip_auth_and_permissions
    def test_unknown_project_returns_404(self):
        resp = self._get(project_uuid=str(uuid4()))
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {"error": "Project not found"})

    @skip_auth_and_permissions
    def test_invalid_source_type_returns_400(self):
        resp = self._get(project_uuid=str(self.org.proj_uuid), source_type="story")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("source_type", resp.json())

    @skip_auth_and_permissions
    def test_invalid_dates_return_400(self):
        resp = self._get(project_uuid=str(self.org.proj_uuid), after="not-a-date")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("after", resp.json())

    @skip_auth_and_permissions
    def test_after_greater_than_before_returns_400(self):
        resp = self._get(
            project_uuid=str(self.org.proj_uuid),
            after="2026-01-03",
            before="2026-01-02",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("non_field_errors", resp.json())

    @skip_auth_and_permissions
    def test_lists_sources_for_project_ordered_by_last_seen_at(self):
        older = self._create_source(
            self.org,
            "older",
            last_seen_at=timezone.now() - timedelta(days=2),
            headline="Older ad",
        )
        newer = self._create_source(
            self.org,
            "newer",
            last_seen_at=timezone.now() - timedelta(days=1),
            headline="Newer ad",
        )
        self._create_source(self.org2, "other-org")

        resp = self._get(project_uuid=str(self.org.proj_uuid))
        self.assertEqual(resp.status_code, 200)

        payload = resp.json()
        self.assertEqual(payload["count"], 2)
        self.assertEqual([item["id"] for item in payload["results"]], [newer.id, older.id])
        self.assertEqual(payload["results"][0]["source_id"], "newer")
        self.assertEqual(payload["results"][0]["headline"], "Newer ad")
        self.assertEqual(payload["results"][0]["project_uuid"], str(self.org.proj_uuid))
        self.assertEqual(payload["results"][0]["org"], self.org.id)
        self.assertNotIn("conversion_events", payload["results"][0])

    @skip_auth_and_permissions
    def test_does_not_include_ctwa_events(self):
        source = self._create_source(self.org, "with-event")
        CTWA.objects.create(
            referral_source=source,
            contact_urn="whatsapp:5511999999999",
            timestamp=timezone.now(),
            channel_uuid=self.channel.uuid,
            waba="waba-1",
            ctwa_clid="clid-1",
        )

        resp = self._get(project_uuid=str(self.org.proj_uuid))
        self.assertEqual(resp.status_code, 200)

        item = resp.json()["results"][0]
        self.assertEqual(item["id"], source.id)
        self.assertNotIn("conversion_events", item)
        self.assertNotIn("ctwa_clid", item)

    @skip_auth_and_permissions
    def test_filters_by_source_type(self):
        ad = self._create_source(self.org, "ad-1", CtwaReferralSource.SOURCE_TYPE_AD)
        self._create_source(self.org, "post-1", CtwaReferralSource.SOURCE_TYPE_POST)

        resp = self._get(project_uuid=str(self.org.proj_uuid), source_type="ad")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([item["id"] for item in resp.json()["results"]], [ad.id])

    @skip_auth_and_permissions
    def test_filters_by_last_seen_at_range(self):
        noon_utc = pytz.UTC.localize(datetime(2026, 1, 15, 12, 0, 0))
        self._create_source(self.org, "before", last_seen_at=noon_utc - timedelta(days=5))
        inside = self._create_source(self.org, "inside", last_seen_at=noon_utc)
        self._create_source(self.org, "after", last_seen_at=noon_utc + timedelta(days=5))

        resp = self._get(
            project_uuid=str(self.org.proj_uuid),
            after="2026-01-15",
            before="2026-01-15",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([item["id"] for item in resp.json()["results"]], [inside.id])

    @skip_auth_and_permissions
    def test_paginates_with_limit_and_offset(self):
        now = timezone.now()
        sources = [
            self._create_source(
                self.org,
                f"source-{index}",
                last_seen_at=now - timedelta(minutes=index),
            )
            for index in range(5)
        ]

        resp = self._get(project_uuid=str(self.org.proj_uuid), limit=2, offset=0)
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["count"], 5)
        self.assertEqual(len(payload["results"]), 2)
        self.assertEqual(payload["results"][0]["id"], sources[0].id)
        self.assertIsNotNone(payload["next"])
        self.assertIsNone(payload["previous"])

        resp = self._get(project_uuid=str(self.org.proj_uuid), limit=2, offset=2)
        payload = resp.json()
        self.assertEqual(len(payload["results"]), 2)
        self.assertEqual(payload["results"][0]["id"], sources[2].id)
        self.assertIsNotNone(payload["previous"])

    @skip_auth_and_permissions
    def test_filters_by_headline_search(self):
        matching = self._create_source(self.org, "sale-ad", headline="Summer sale")
        self._create_source(self.org, "other-ad", headline="Winter promo")
        self._create_source(self.org, "no-headline")

        resp = self._get(project_uuid=str(self.org.proj_uuid), search="sale")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([item["id"] for item in resp.json()["results"]], [matching.id])
