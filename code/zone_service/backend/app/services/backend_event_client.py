"""Client gui AI Event sang Backend API (.NET) de Backend/Risk Engine tao canh bao.

Luong:
    POST {base}/api/v1/auth/token   {"clientId", "clientSecret"} -> {"accessToken", ...}
    POST {base}/api/v1/events       Authorization: Bearer <token> -> 202 {"alertId": "..."|null}

Token duoc cache (mac dinh 12h, tru hao 5 phut). Gap 401 thi xin token moi va gui lai 1 lan.
Moi loi deu duoc tra ve trong BackendEventResult, khong nem exception ra router, de
Backend tat/loi khong lam hong viec luu ai_event cua Zone Service.
"""

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple


LOGGER = logging.getLogger(__name__)

DEFAULT_TOKEN_TTL_SECONDS = 12 * 3600
TOKEN_REFRESH_MARGIN_SECONDS = 300

# (status_code, parsed_json_body)
HttpResponse = Tuple[int, Dict[str, Any]]
HttpPost = Callable[[str, Dict[str, Any], Dict[str, str], float], HttpResponse]


@dataclass
class BackendEventResult:
    ok: bool
    status_code: Optional[int] = None
    alert_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class _Stats:
    sent: int = 0
    accepted: int = 0
    alerts_returned: int = 0
    failed: int = 0
    token_requests: int = 0
    last_status_code: Optional[int] = None
    last_error_code: Optional[str] = None
    last_error_message: Optional[str] = None
    last_sent_at: Optional[float] = None
    error_codes: Dict[str, int] = field(default_factory=dict)


class BackendEventClient:
    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        timeout_seconds: float = 2.0,
        http_post: Optional[HttpPost] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout_seconds = timeout_seconds
        self._http_post = http_post or _urllib_post_json
        self._clock = clock
        self._lock = threading.Lock()
        self._token: Optional[str] = None
        self._token_expires_at = 0.0
        self._stats = _Stats()

    # ------------------------------------------------------------------ public
    def send_event(self, payload: Dict[str, Any]) -> BackendEventResult:
        result = self._send_with_auth(payload)
        with self._lock:
            stats = self._stats
            stats.sent += 1
            stats.last_sent_at = self._clock()
            stats.last_status_code = result.status_code
            if result.ok:
                stats.accepted += 1
                if result.alert_id:
                    stats.alerts_returned += 1
            else:
                stats.failed += 1
                stats.last_error_code = result.error_code
                stats.last_error_message = result.error_message
                key = result.error_code or "HTTP_{}".format(result.status_code or "ERROR")
                stats.error_codes[key] = stats.error_codes.get(key, 0) + 1
        if not result.ok:
            LOGGER.warning(
                "BACKEND_EVENT_FAILED ai_event_id=%s status=%s code=%s message=%s",
                payload.get("aiEventId"),
                result.status_code,
                result.error_code,
                result.error_message,
            )
        return result

    def status(self) -> Dict[str, Any]:
        with self._lock:
            stats = self._stats
            return {
                "base_url": self.base_url,
                "client_id": self.client_id,
                "has_token": self._token is not None,
                "token_expires_in_seconds": max(0, int(self._token_expires_at - self._clock())) if self._token else 0,
                "sent": stats.sent,
                "accepted": stats.accepted,
                "alerts_returned": stats.alerts_returned,
                "failed": stats.failed,
                "token_requests": stats.token_requests,
                "last_status_code": stats.last_status_code,
                "last_error_code": stats.last_error_code,
                "last_error_message": stats.last_error_message,
                "error_codes": dict(stats.error_codes),
            }

    # ----------------------------------------------------------------- private
    def _send_with_auth(self, payload: Dict[str, Any]) -> BackendEventResult:
        try:
            token = self._get_token()
        except Exception as exc:
            return BackendEventResult(ok=False, error_code="AUTH_FAILED", error_message=str(exc))

        for attempt in range(2):
            try:
                status, body = self._http_post(
                    "{}/api/v1/events".format(self.base_url),
                    payload,
                    {"Authorization": "Bearer {}".format(token)},
                    self.timeout_seconds,
                )
            except Exception as exc:
                return BackendEventResult(ok=False, error_code="BACKEND_UNREACHABLE", error_message=str(exc))

            if status == 401 and attempt == 0:
                self._invalidate_token()
                try:
                    token = self._get_token()
                except Exception as exc:
                    return BackendEventResult(ok=False, status_code=401, error_code="AUTH_FAILED", error_message=str(exc))
                continue

            if 200 <= status < 300:
                alert_id = body.get("alertId") if isinstance(body, dict) else None
                return BackendEventResult(ok=True, status_code=status, alert_id=str(alert_id) if alert_id else None)

            error = body.get("error") if isinstance(body, dict) else None
            error = error if isinstance(error, dict) else {}
            return BackendEventResult(
                ok=False,
                status_code=status,
                error_code=error.get("code"),
                error_message=error.get("message") or (json.dumps(body)[:300] if body else None),
            )

        return BackendEventResult(ok=False, status_code=401, error_code="UNAUTHORIZED", error_message="Token rejected twice")

    def _get_token(self) -> str:
        with self._lock:
            if self._token and self._clock() < self._token_expires_at:
                return self._token

        status, body = self._http_post(
            "{}/api/v1/auth/token".format(self.base_url),
            {"clientId": self.client_id, "clientSecret": self.client_secret},
            {},
            self.timeout_seconds,
        )
        with self._lock:
            self._stats.token_requests += 1
        if not (200 <= status < 300) or not isinstance(body, dict) or not body.get("accessToken"):
            raise RuntimeError("Token request failed with HTTP {}".format(status))

        ttl = _token_ttl_seconds(body, self._clock())
        with self._lock:
            self._token = str(body["accessToken"])
            self._token_expires_at = self._clock() + max(60.0, ttl - TOKEN_REFRESH_MARGIN_SECONDS)
            return self._token

    def _invalidate_token(self) -> None:
        with self._lock:
            self._token = None
            self._token_expires_at = 0.0


def _token_ttl_seconds(body: Dict[str, Any], now: float) -> float:
    for key in ("expiresIn", "expires_in"):
        if body.get(key):
            try:
                return float(body[key])
            except (TypeError, ValueError):
                pass
    expires_at = body.get("expiresAt") or body.get("expires_at")
    if expires_at:
        try:
            from datetime import datetime

            parsed = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            return max(0.0, parsed.timestamp() - now)
        except ValueError:
            pass
    return float(DEFAULT_TOKEN_TTL_SECONDS)


def _urllib_post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str], timeout: float) -> HttpResponse:
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, _parse_json(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _parse_json(exc.read())


def _parse_json(raw: bytes) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"raw": raw[:300].decode("utf-8", "replace")}
    return value if isinstance(value, dict) else {"value": value}
