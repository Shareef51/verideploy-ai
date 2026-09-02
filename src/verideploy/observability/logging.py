import json, logging
from datetime import datetime, timezone
from typing import Any

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        correlation_id = getattr(record, "correlation_id", None)
        if correlation_id: payload["correlation_id"] = correlation_id
        if record.exc_info: payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"))

def configure_logging(level: str) -> None:
    handler=logging.StreamHandler(); handler.setFormatter(JsonFormatter())
    root=logging.getLogger(); root.handlers=[handler]; root.setLevel(level.upper())
