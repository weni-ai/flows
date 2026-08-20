import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional

from django.core.exceptions import ValidationError
from django.utils import timezone

from temba.conversion_events.models import CtwaReferralSource
from temba.orgs.models import Org

logger = logging.getLogger(__name__)


class ProjectNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class ListCtwaReferralSourcesDTO:
    project_uuid: str
    source_type: Optional[str] = None
    after: Optional[date] = None
    before: Optional[date] = None
    search: Optional[str] = None


class ListCtwaReferralSourcesUseCase:
    def execute(self, dto: ListCtwaReferralSourcesDTO):
        logger.info(
            f"Listing CTWA referral sources for project_uuid={dto.project_uuid} "
            f"source_type={dto.source_type} after={dto.after} before={dto.before} search={dto.search}"
        )
        org = self._get_org(dto.project_uuid)
        queryset = (
            CtwaReferralSource.objects.filter(org=org)
            .exclude(
                source_id=CtwaReferralSource.LEGACY_SOURCE_ID,
                source_type=CtwaReferralSource.SOURCE_TYPE_AD,
            )
            .select_related("org")
        )

        if dto.source_type:
            queryset = queryset.filter(source_type=dto.source_type)
        if dto.after:
            queryset = queryset.filter(last_seen_at__gte=self._inclusive_start(dto.after))
        if dto.before:
            queryset = queryset.filter(last_seen_at__lt=self._exclusive_end(dto.before))
        if dto.search:
            queryset = queryset.filter(headline__icontains=dto.search)

        return queryset.order_by("-last_seen_at", "-id")

    def _get_org(self, project_uuid: str) -> Org:
        try:
            return Org.objects.get(proj_uuid=project_uuid)
        except (Org.DoesNotExist, ValidationError, ValueError):
            logger.warning(f"Project not found for project_uuid={project_uuid}")
            raise ProjectNotFoundError()

    def _inclusive_start(self, day: date) -> datetime:
        return timezone.make_aware(datetime.combine(day, time.min))

    def _exclusive_end(self, day: date) -> datetime:
        return timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min))
