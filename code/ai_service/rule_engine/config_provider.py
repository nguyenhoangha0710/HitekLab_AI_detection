import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Optional, Tuple

from .models import ZoneConfig


LOGGER = logging.getLogger(__name__)


class StaticConfigProvider:
    """Provider co dinh, dung cho unit test hoac chay offline."""

    def __init__(self, zones_by_camera: Optional[Dict[str, List[ZoneConfig]]] = None) -> None:
        self._zones = dict(zones_by_camera or {})

    def get(self, camera_id: str) -> List[ZoneConfig]:
        return list(self._zones.get(camera_id, []))

    def set(self, camera_id: str, zones: List[ZoneConfig]) -> None:
        self._zones[camera_id] = list(zones)

    def invalidate(self, camera_id: Optional[str] = None) -> None:
        return None

    def stats(self) -> dict:
        return {"type": "static", "cameras": len(self._zones)}


class ZoneServiceConfigProvider:
    """Lay zone + rule tu Zone Service va cache theo camera.

    `get()` khong bao gio block luong inference: khi cache het han, provider tra
    ve cau hinh cu va refresh o background thread. Lan dau tien (chua co cache)
    se tra ve danh sach rong cho toi khi refresh xong (thuong < 1 giay).
    """

    def __init__(
        self,
        base_url: str,
        ttl_seconds: float = 10.0,
        timeout_seconds: float = 2.0,
        retry_backoff_seconds: float = 5.0,
        fetch_json: Optional[Callable[[str], object]] = None,
        background: bool = True,
        service_api_key: Optional[str] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.ttl_seconds = ttl_seconds
        self.timeout_seconds = timeout_seconds
        self.retry_backoff_seconds = retry_backoff_seconds
        self.background = background
        self.service_api_key = service_api_key
        self._fetch_json = fetch_json or self._http_get_json
        self._lock = threading.Lock()
        self._cache: Dict[str, Tuple[float, List[ZoneConfig]]] = {}
        self._next_attempt_at: Dict[str, float] = {}
        self._refreshing: set = set()
        self._last_error: Optional[str] = None

    def get(self, camera_id: str) -> List[ZoneConfig]:
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(camera_id)
            is_fresh = cached is not None and now - cached[0] < self.ttl_seconds
            can_retry = now >= self._next_attempt_at.get(camera_id, 0.0)
            should_refresh = not is_fresh and can_retry and camera_id not in self._refreshing
            if should_refresh:
                self._refreshing.add(camera_id)
            zones = list(cached[1]) if cached else []

        if should_refresh:
            if self.background:
                threading.Thread(target=self._refresh, args=(camera_id,), name="rule-config-refresh", daemon=True).start()
            else:
                self._refresh(camera_id)
                with self._lock:
                    cached = self._cache.get(camera_id)
                    zones = list(cached[1]) if cached else []
        return zones

    def invalidate(self, camera_id: Optional[str] = None) -> None:
        with self._lock:
            if camera_id is None:
                self._cache.clear()
                self._next_attempt_at.clear()
            else:
                self._cache.pop(camera_id, None)
                self._next_attempt_at.pop(camera_id, None)

    def stats(self) -> dict:
        with self._lock:
            return {
                "type": "zone_service",
                "base_url": self.base_url,
                "ttl_seconds": self.ttl_seconds,
                "cameras": {
                    camera_id: {"zones": len(zones), "rules": sum(len(zone.rules) for zone in zones)}
                    for camera_id, (_, zones) in self._cache.items()
                },
                "last_error": self._last_error,
            }

    def _refresh(self, camera_id: str) -> None:
        try:
            zones = self._load(camera_id)
            with self._lock:
                self._cache[camera_id] = (time.monotonic(), zones)
                self._next_attempt_at.pop(camera_id, None)
                self._last_error = None
        except Exception as exc:
            LOGGER.warning("RULE_CONFIG_REFRESH_FAILED camera=%s error=%s", camera_id, exc)
            with self._lock:
                self._next_attempt_at[camera_id] = time.monotonic() + self.retry_backoff_seconds
                self._last_error = "{}: {}".format(camera_id, exc)
        finally:
            with self._lock:
                self._refreshing.discard(camera_id)

    def _load(self, camera_id: str) -> List[ZoneConfig]:
        quoted_camera = urllib.parse.quote(camera_id, safe="")
        try:
            zones_data = self._fetch_json("{}/api/cameras/{}/zones".format(self.base_url, quoted_camera))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return []
            raise
        zones: List[ZoneConfig] = []
        for zone_data in zones_data or []:
            if not zone_data.get("enabled", True):
                continue
            quoted_zone = urllib.parse.quote(str(zone_data["id"]), safe="")
            rules_data = self._fetch_json("{}/api/zones/{}/rules".format(self.base_url, quoted_zone)) or []
            zones.append(ZoneConfig.from_api(zone_data, rules_data))
        return zones

    def _http_get_json(self, url: str):
        headers = {"Accept": "application/json"}
        if self.service_api_key:
            headers["X-Service-Key"] = self.service_api_key
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
