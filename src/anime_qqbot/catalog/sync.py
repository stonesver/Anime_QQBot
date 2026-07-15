from dataclasses import dataclass

from anime_qqbot.catalog.models import Season
from anime_qqbot.catalog.ports import AiringProvider, BangumiProvider
from anime_qqbot.catalog.repository import CatalogRepository
from anime_qqbot.clock import Clock


@dataclass(frozen=True)
class SyncReport:
    bangumi_ok: bool
    bangumi_data_ok: bool


class CatalogSyncService:
    def __init__(
        self,
        bangumi: BangumiProvider,
        bangumi_data: AiringProvider,
        repository: CatalogRepository,
        clock: Clock,
    ) -> None:
        self._bangumi = bangumi
        self._bangumi_data = bangumi_data
        self._repository = repository
        self._clock = clock

    async def sync(self, season: Season) -> SyncReport:
        bangumi_ok = await self._sync_bangumi()
        bangumi_data_ok = await self._sync_bangumi_data(season)
        return SyncReport(bangumi_ok, bangumi_data_ok)

    async def _sync_bangumi(self) -> bool:
        now = self._clock.now()
        try:
            subjects = await self._bangumi.calendar()
            occurrences = []
            for subject in subjects:
                occurrences.extend(await self._bangumi.episodes(subject.subject_id))
            await self._repository.save_snapshot("bangumi", subjects, occurrences, now)
        except Exception as error:
            await self._repository.record_failure("bangumi", error, now)
            return False
        return True

    async def _sync_bangumi_data(self, season: Season) -> bool:
        now = self._clock.now()
        starts_on, _ = season.date_range
        try:
            subjects, occurrences = await self._bangumi_data.season(season.year, starts_on.month)
            await self._repository.save_snapshot("bangumi-data", subjects, occurrences, now)
        except Exception as error:
            await self._repository.record_failure("bangumi-data", error, now)
            return False
        return True
