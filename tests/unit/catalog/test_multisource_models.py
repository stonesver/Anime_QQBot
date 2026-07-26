from datetime import UTC, datetime
from datetime import date as _date_type
from uuid import UUID, uuid4

import pytest

from anime_qqbot.catalog.models import (
    AiringOccurrence,
    AnimeId,
    ExternalEntry,
    ExternalEntryId,
    LinkEvidenceType,
    LinkStatus,
    SourceLink,
    SourceName,
    SourceSnapshot,
)


class TestAnimeId:
    def test_internal_id_wraps_uuid(self) -> None:
        raw = UUID("12345678-1234-5678-1234-567812345678")

        anime_id = AnimeId(raw)

        assert isinstance(anime_id, UUID)
        assert anime_id == raw

    def test_factory_produces_unique_ids(self) -> None:
        first = AnimeId(uuid4())
        second = AnimeId(uuid4())

        assert first != second

    def test_internal_id_is_immutable(self) -> None:
        anime_id = AnimeId(uuid4())

        with pytest.raises((AttributeError, TypeError)):
            anime_id.int = 0  # type: ignore[misc]


class TestSourceName:
    def test_providers_are_distinct(self) -> None:
        assert SourceName.BANGUMI != SourceName.ANILIST
        assert SourceName.ANILIST != SourceName.MIKAN
        assert SourceName.BANGUMI != SourceName.MIKAN

    def test_provider_values_are_stable_strings(self) -> None:
        assert SourceName.BANGUMI.value == "bangumi"
        assert SourceName.ANILIST.value == "anilist"
        assert SourceName.MIKAN.value == "mikan"


class TestExternalEntry:
    def _make(self) -> ExternalEntry:
        return ExternalEntry(
            id=ExternalEntryId(uuid4()),
            source=SourceName.BANGUMI,
            external_id="12345",
            url="https://bgm.tv/subject/12345",
        )

    def test_composite_identity_requires_source_and_external_id(self) -> None:
        entry = self._make()

        assert entry.source == SourceName.BANGUMI
        assert entry.external_id == "12345"
        assert (entry.source, entry.external_id) == (SourceName.BANGUMI, "12345")

    def test_disabled_defaults_to_false(self) -> None:
        entry = self._make()

        assert entry.disabled is False

    def test_external_id_must_be_non_empty(self) -> None:
        with pytest.raises(ValueError):
            ExternalEntry(
                id=ExternalEntryId(uuid4()),
                source=SourceName.BANGUMI,
                external_id="",
                url=None,
            )

    def test_url_is_optional(self) -> None:
        entry = ExternalEntry(
            id=ExternalEntryId(uuid4()),
            source=SourceName.MIKAN,
            external_id="2581",
            url=None,
        )

        assert entry.url is None


class TestLinkStatus:
    def test_default_is_unresolved(self) -> None:
        assert LinkStatus.default_for_new_matches() == LinkStatus.UNRESOLVED

    def test_only_confirmed_drives_notifications(self) -> None:
        assert LinkStatus.CONFIRMED.notifies() is True
        assert LinkStatus.PROBABLE.notifies() is False
        assert LinkStatus.UNRESOLVED.notifies() is False
        assert LinkStatus.REJECTED.notifies() is False

    def test_rejected_can_be_distinguished(self) -> None:
        assert LinkStatus.REJECTED.is_terminal_negative() is True
        assert LinkStatus.CONFIRMED.is_terminal_negative() is False
        assert LinkStatus.UNRESOLVED.is_terminal_negative() is False


class TestSourceLink:
    def _make(self, **overrides: object) -> SourceLink:
        base: dict[str, object] = {
            "external_entry_id": ExternalEntryId(uuid4()),
            "status": LinkStatus.PROBABLE,
            "evidence_type": LinkEvidenceType.TITLE_SEASON_YEAR,
            "confidence": 0.72,
            "method": "v1.strict_title",
            "created_at": datetime(2026, 7, 15, tzinfo=UTC),
        }
        base.update(overrides)
        return SourceLink(**base)  # type: ignore[arg-type]

    def test_confidence_is_bounded(self) -> None:
        with pytest.raises(ValueError):
            self._make(confidence=1.5)
        with pytest.raises(ValueError):
            self._make(confidence=-0.1)

    def test_default_status_is_unresolved(self) -> None:
        link = self._make(status=LinkStatus.UNRESOLVED)

        assert link.status == LinkStatus.UNRESOLVED

    def test_reviewed_timestamps_are_optional(self) -> None:
        link = self._make()

        assert link.reviewed_at is None
        assert link.reviewed_by is None

    def test_evidence_payload_is_optional(self) -> None:
        link = self._make()

        assert link.evidence == ()

    def test_reviewed_at_must_be_tz_aware(self) -> None:
        with pytest.raises(ValueError):
            self._make(reviewed_at=datetime(2026, 7, 15, 12, 0))  # noqa: DTZ001


class TestSourceSnapshot:
    def _make(self, **overrides: object) -> SourceSnapshot:
        base: dict[str, object] = {
            "external_entry_id": ExternalEntryId(uuid4()),
            "version": 3,
            "payload": {"title": "Demo", "score": 8.4},
            "source_time": datetime(2026, 7, 15, 10, 0, tzinfo=UTC),
            "fetched_at": datetime(2026, 7, 15, 10, 5, tzinfo=UTC),
        }
        base.update(overrides)
        return SourceSnapshot(**base)  # type: ignore[arg-type]

    def test_version_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            self._make(version=0)

    def test_timestamps_must_be_tz_aware(self) -> None:
        with pytest.raises(ValueError):
            self._make(fetched_at=datetime(2026, 7, 15, 10, 5))  # noqa: DTZ001
        with pytest.raises(ValueError):
            self._make(source_time=datetime(2026, 7, 15, 10, 0))  # noqa: DTZ001

    def test_expires_at_optional(self) -> None:
        snapshot = self._make()

        assert snapshot.expires_at is None

    def test_payload_is_a_mapping(self) -> None:
        snapshot = self._make(payload={"k": "v"})

        assert snapshot.payload == {"k": "v"}


class TestAiringOccurrenceInvariants:
    def _date(self) -> _date_type:
        return _date_type(2026, 7, 15)

    def test_date_only_means_no_exact_time(self) -> None:
        occurrence = AiringOccurrence(
            subject_id=1,
            air_date=self._date(),
            air_at=None,
            episode=7,
            source="bangumi",
        )

        assert occurrence.date_only is True

    def test_exact_time_requires_tz_aware_datetime(self) -> None:
        with pytest.raises(ValueError):
            AiringOccurrence(
                subject_id=1,
                air_date=self._date(),
                air_at=datetime(2026, 7, 15, 12, 0),  # noqa: DTZ001
                episode=3,
                source="bangumi",
            )

    def test_in_timezone_converts_aware_datetime(self) -> None:
        from zoneinfo import ZoneInfo

        occurrence = AiringOccurrence(
            subject_id=1,
            air_date=self._date(),
            air_at=datetime(2026, 7, 15, 12, 0, tzinfo=UTC),
            episode=3,
            source="anilist",
        )

        local = occurrence.in_timezone(ZoneInfo("Asia/Shanghai"))

        assert local is not None
        assert local.hour == 20
        assert local.date() == self._date()

    def test_updated_at_window_is_optional(self) -> None:
        occurrence = AiringOccurrence(
            subject_id=1,
            air_date=self._date(),
            air_at=None,
            episode=1,
            source="bangumi",
        )

        assert occurrence.updated_at is None
