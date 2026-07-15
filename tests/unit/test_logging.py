from anime_qqbot.logging import redact


def test_redact_hides_nested_sensitive_values() -> None:
    payload = {
        "authorization": "Bearer abc",
        "nested": {"app_secret": "secret", "count": 2},
        "items": [{"access_token": "token"}, {"title": "safe"}],
    }

    assert redact(payload) == {
        "authorization": "***REDACTED***",
        "nested": {"app_secret": "***REDACTED***", "count": 2},
        "items": [{"access_token": "***REDACTED***"}, {"title": "safe"}],
    }


def test_redact_leaves_non_sensitive_values_unchanged() -> None:
    assert redact({"subject_id": 400602, "title": "葬送的芙莉莲"}) == {
        "subject_id": 400602,
        "title": "葬送的芙莉莲",
    }
