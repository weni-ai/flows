from datetime import date, datetime, timedelta
from uuid import uuid4

import pytz

from django.utils import timezone

from temba.api.v2.internals.conversion_events.usecases import (
    ListCtwaReferralSourcesDTO,
    ListCtwaReferralSourcesUseCase,
    ProjectNotFoundError,
)
from temba.conversion_events.models import CtwaReferralSource
from temba.tests import TembaTest


class ListCtwaReferralSourcesUseCaseTest(TembaTest):
    def setUp(self):
        super().setUp()
        self.org.proj_uuid = uuid4()
        self.org.save(update_fields=["proj_uuid"])
        self.org2.proj_uuid = uuid4()
        self.org2.save(update_fields=["proj_uuid"])
        self.usecase = ListCtwaReferralSourcesUseCase()

    def _create_source(
        self, org, source_id, source_type=CtwaReferralSource.SOURCE_TYPE_AD, last_seen_at=None, **defaults
    ):
        source, _ = CtwaReferralSource.get_or_create_for_org(org, source_id, source_type, **defaults)
        if last_seen_at is not None:
            CtwaReferralSource.objects.filter(id=source.id).update(last_seen_at=last_seen_at)
            source.refresh_from_db()
        return source

    def test_execute_raises_project_not_found_for_unknown_uuid(self):
        dto = ListCtwaReferralSourcesDTO(project_uuid=str(uuid4()))
        with self.assertRaises(ProjectNotFoundError):
            self.usecase.execute(dto)

    def test_execute_raises_project_not_found_for_invalid_uuid(self):
        dto = ListCtwaReferralSourcesDTO(project_uuid="not-a-uuid")
        with self.assertRaises(ProjectNotFoundError):
            self.usecase.execute(dto)

    def test_execute_returns_only_sources_for_the_project(self):
        own = self._create_source(self.org, "own-ad")
        self._create_source(self.org2, "other-ad")

        dto = ListCtwaReferralSourcesDTO(project_uuid=str(self.org.proj_uuid))
        results = list(self.usecase.execute(dto))

        self.assertEqual(results, [own])

    def test_execute_orders_by_last_seen_at_descending(self):
        older = self._create_source(self.org, "older", last_seen_at=timezone.now() - timedelta(days=2))
        newer = self._create_source(self.org, "newer", last_seen_at=timezone.now() - timedelta(days=1))

        dto = ListCtwaReferralSourcesDTO(project_uuid=str(self.org.proj_uuid))
        results = list(self.usecase.execute(dto))

        self.assertEqual(results, [newer, older])

    def test_execute_filters_by_source_type(self):
        ad = self._create_source(self.org, "ad-1", CtwaReferralSource.SOURCE_TYPE_AD)
        self._create_source(self.org, "post-1", CtwaReferralSource.SOURCE_TYPE_POST)

        dto = ListCtwaReferralSourcesDTO(
            project_uuid=str(self.org.proj_uuid),
            source_type=CtwaReferralSource.SOURCE_TYPE_AD,
        )
        results = list(self.usecase.execute(dto))

        self.assertEqual(results, [ad])

    def test_execute_filters_by_last_seen_at_date_range(self):
        noon_utc = pytz.UTC.localize(datetime(2026, 1, 15, 12, 0, 0))
        before_range = self._create_source(self.org, "before", last_seen_at=noon_utc - timedelta(days=5))
        inside = self._create_source(self.org, "inside", last_seen_at=noon_utc)
        after_range = self._create_source(self.org, "after", last_seen_at=noon_utc + timedelta(days=5))

        dto = ListCtwaReferralSourcesDTO(
            project_uuid=str(self.org.proj_uuid),
            after=date(2026, 1, 15),
            before=date(2026, 1, 15),
        )
        results = list(self.usecase.execute(dto))

        self.assertEqual(results, [inside])
        self.assertNotIn(before_range, results)
        self.assertNotIn(after_range, results)

    def test_execute_excludes_legacy_ad_placeholder(self):
        valid = self._create_source(self.org, "real-ad")
        self._create_source(self.org, CtwaReferralSource.LEGACY_SOURCE_ID, CtwaReferralSource.SOURCE_TYPE_AD)

        dto = ListCtwaReferralSourcesDTO(project_uuid=str(self.org.proj_uuid))
        results = list(self.usecase.execute(dto))

        self.assertEqual(results, [valid])

    def test_execute_includes_legacy_source_id_when_type_is_post(self):
        post = self._create_source(
            self.org, CtwaReferralSource.LEGACY_SOURCE_ID, CtwaReferralSource.SOURCE_TYPE_POST
        )

        dto = ListCtwaReferralSourcesDTO(project_uuid=str(self.org.proj_uuid))
        results = list(self.usecase.execute(dto))

        self.assertEqual(results, [post])
