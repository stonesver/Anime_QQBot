from anime_qqbot.notifications.module import NotificationAudience, merge_audiences


def test_same_group_subject_occurrence_merges_members() -> None:
    rows = [
        NotificationAudience("g", 1, "番剧", None, "2026-07-15", ("b",)),
        NotificationAudience("g", 1, "番剧", None, "2026-07-15", ("a",)),
    ]
    assert merge_audiences(rows)[0].member_openids == ("a", "b")
