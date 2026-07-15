import json
import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

REDACTED = "***REDACTED***"
SENSITIVE_KEY_PARTS = ("authorization", "password", "secret", "token")


def redact(value: object, *, key: str | None = None) -> object:
    if key is not None and any(part in key.lower() for part in SENSITIVE_KEY_PARTS):
        return REDACTED
    if isinstance(value, Mapping):
        return {
            str(item_key): redact(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact(item) for item in value]
    return value


class RedactingJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.msg if isinstance(record.msg, Mapping) else record.getMessage()
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(message),
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingJsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
