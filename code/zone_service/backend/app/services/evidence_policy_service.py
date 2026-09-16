from datetime import datetime, timezone
from typing import Optional


def should_capture_alert_evidence(repository, alert_id: Optional[str], payload: dict, interval_seconds: int) -> bool:
    latest = repository.latest_for_alert(alert_id)
    if latest is None:
        return True
    previous = parse_time(latest["captured_at"])
    current = parse_time(payload.get("last_seen_at") or payload["started_at"])
    if previous is None or current is None:
        return False
    return (current - previous).total_seconds() >= interval_seconds


def parse_time(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
