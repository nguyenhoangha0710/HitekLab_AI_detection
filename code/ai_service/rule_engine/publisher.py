import json
import logging
import queue
import threading
import time
import urllib.request
from typing import Callable, List, Optional


LOGGER = logging.getLogger(__name__)


class InMemoryPublisher:
    """Publisher giu event trong bo nho, dung cho unit test."""

    def __init__(self) -> None:
        self.events: List[dict] = []

    def publish(self, event: dict) -> None:
        self.events.append(event)

    def close(self) -> None:
        return None

    def stats(self) -> dict:
        return {"type": "memory", "published": len(self.events)}


class AiEventPublisher:
    """Gui AI Event sang Zone Service bang background thread.

    Luong inference chi `put` vao queue; neu Zone Service cham hoac tat, event
    duoc retry vai lan roi bo qua, khong lam ngung YOLO.
    """

    def __init__(
        self,
        endpoint_url: str,
        timeout_seconds: float = 3.0,
        max_queue_size: int = 500,
        max_retries: int = 2,
        retry_delay_seconds: float = 0.5,
        post_json: Optional[Callable[[str, dict], None]] = None,
        start_thread: bool = True,
        service_api_key: Optional[str] = None,
    ) -> None:
        self.endpoint_url = endpoint_url
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.service_api_key = service_api_key
        self._post_json = post_json or self._http_post_json
        self._queue: "queue.Queue[dict]" = queue.Queue(maxsize=max_queue_size)
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._stats = {"published": 0, "failed": 0, "dropped": 0}
        self._last_error: Optional[str] = None
        self._thread = threading.Thread(target=self._run, name="ai-event-publisher", daemon=True)
        if start_thread:
            self._thread.start()

    def publish(self, event: dict) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            with self._lock:
                self._stats["dropped"] += 1
            LOGGER.warning("AI_EVENT_DROPPED queue_full source_event_id=%s", event.get("source_event_id"))

    def close(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def stats(self) -> dict:
        with self._lock:
            return dict(
                self._stats,
                type="http",
                endpoint_url=self.endpoint_url,
                queue_size=self._queue.qsize(),
                last_error=self._last_error,
            )

    def flush_once(self) -> bool:
        """Xu ly 1 event trong queue (dung cho test). Tra ve False neu queue rong."""
        try:
            event = self._queue.get_nowait()
        except queue.Empty:
            return False
        self._deliver(event)
        return True

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                event = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            self._deliver(event)

    def _deliver(self, event: dict) -> None:
        for attempt in range(self.max_retries + 1):
            try:
                self._post_json(self.endpoint_url, event)
                with self._lock:
                    self._stats["published"] += 1
                    self._last_error = None
                return
            except Exception as exc:
                error = str(exc)
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay_seconds * (attempt + 1))
        with self._lock:
            self._stats["failed"] += 1
            self._last_error = error
        LOGGER.warning(
            "AI_EVENT_PUBLISH_FAILED source_event_id=%s error=%s",
            event.get("source_event_id"),
            error,
        )

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.service_api_key:
            # Zone Service bat AUTH_MODE=jwt -> service noi bo xac thuc bang khoa nay.
            headers["X-Service-Key"] = self.service_api_key
        return headers

    def _http_post_json(self, url: str, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers=self._headers(),
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            response.read()
