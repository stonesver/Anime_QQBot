import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx

from anime_qqbot.catalog.adapters.bangumi_data import BangumiDataClient
from anime_qqbot.catalog.models import Season, SeasonName

FIXTURE = Path(__file__).parents[1] / "fixtures" / "bangumi_data" / "season.json"


def test_maps_only_strong_bangumi_ids_and_recurring_broadcasts() -> None:
    payload = json.loads(FIXTURE.read_text())
    subjects, occurrences = BangumiDataClient.parse_document(
        payload, Season(2026, SeasonName.SUMMER), datetime(2026, 7, 15, tzinfo=UTC)
    )

    assert [subject.subject_id for subject in subjects] == [1001, 1002]
    timed = [item for item in occurrences if item.subject_id == 1001]
    assert len(timed) == 13
    assert timed[0].air_at == datetime(2026, 7, 3, 16, 30, tzinfo=UTC)
    date_only = [item for item in occurrences if item.subject_id == 1002]
    assert len(date_only) == 1 and date_only[0].date_only


@respx.mock
async def test_fetches_and_maps_season_document() -> None:
    respx.get("https://example.test/data.json").mock(
        return_value=httpx.Response(200, json=json.loads(FIXTURE.read_text()))
    )
    async with BangumiDataClient(data_url="https://example.test/data.json") as client:
        subjects, occurrences = await client.season(2026, 7)

    assert len(subjects) == 2
    assert occurrences[0].source == "bangumi-data"
    assert occurrences[0].updated_at is not None
