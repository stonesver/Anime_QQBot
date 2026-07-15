from anime_qqbot.catalog.adapters.bangumi_data import BangumiDataClient


def test_bangumi_id_never_falls_back_to_title_or_other_site() -> None:
    assert BangumiDataClient._bangumi_id([{"site": "bilibili", "id": "1001"}]) is None
    assert BangumiDataClient._bangumi_id([{"site": "bangumi", "id": "not-number"}]) is None
    assert BangumiDataClient._bangumi_id([{"site": "bangumi", "id": "1001"}]) == 1001
