import json
import logging
import threading
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional
from uuid import uuid4

import requests

from .models import FramePacket


LOGGER = logging.getLogger(__name__)


class FrameSink:
    def start(self) -> None:
        pass

    def send(self, packet: FramePacket) -> None:
        raise NotImplementedError

    def wait_until_idle(self, timeout_seconds: float) -> bool:
        return True

    def stats(self):
        return []

    def stop(self) -> None:
        pass


class ConsoleFrameSink(FrameSink):
    def __init__(self, log_every_n_frames: int = 30) -> None:
        self.log_every_n_frames = max(1, log_every_n_frames)

    def send(self, packet: FramePacket) -> None:
        metadata = packet.metadata
        if metadata.sequence_number % self.log_every_n_frames == 0:
            print(json.dumps(metadata.to_dict(), ensure_ascii=False))


class MemoryFrameSink(FrameSink):
    def __init__(self) -> None:
        self.packets: List[FramePacket] = []

    def send(self, packet: FramePacket) -> None:
        self.packets.append(packet)


class AiServiceHttpFrameSink(FrameSink):
    def __init__(self, base_url: str, endpoint: str, timeout_seconds: float = 5) -> None:
        self.url = base_url.rstrip("/") + "/" + endpoint.lstrip("/")
        self.timeout_seconds = timeout_seconds

    def send(self, packet: FramePacket) -> None:
        metadata_json = json.dumps(packet.metadata.to_dict(), ensure_ascii=False)
        files = {
            "metadata": (None, metadata_json, "application/json"),
            "image": ("frame.jpg", packet.image_bytes, "image/jpeg"),
        }
        headers = {"X-Correlation-ID": str(uuid4())}
        response = requests.post(self.url, files=files, headers=headers, timeout=self.timeout_seconds)
        response.raise_for_status()


@dataclass
class OutboundQueueStats:
    camera_id: str
    received_frames: int = 0
    enqueued_frames: int = 0
    sent_frames: int = 0
    dropped_frames: int = 0
    failed_sends: int = 0
    queue_size: int = 0
    last_enqueued_frame_id: Optional[str] = None
    last_sent_frame_id: Optional[str] = None


class QueuedFrameSink(FrameSink):
    def __init__(self, inner: FrameSink, max_size_per_camera: int = 2, sender_worker_count: int = 1) -> None:
        self.inner = inner
        self.max_size_per_camera = max(1, max_size_per_camera)
        self.sender_worker_count = max(1, sender_worker_count)
        self._condition = threading.Condition()
        self._queues: Dict[str, Deque[FramePacket]] = {}
        self._stats: Dict[str, OutboundQueueStats] = {}
        self._camera_order: List[str] = []
        self._next_camera_index = 0
        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []

    def start(self) -> None:
        self.inner.start()
        for index in range(self.sender_worker_count):
            thread = threading.Thread(
                target=self._run_sender,
                name="http-sender-{}".format(index + 1),
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def send(self, packet: FramePacket) -> None:
        camera_id = packet.metadata.camera_id
        with self._condition:
            queue = self._queues.setdefault(camera_id, deque())
            stats = self._stats.setdefault(camera_id, OutboundQueueStats(camera_id=camera_id))
            if camera_id not in self._camera_order:
                self._camera_order.append(camera_id)

            stats.received_frames += 1
            if len(queue) >= self.max_size_per_camera:
                queue.popleft()
                stats.dropped_frames += 1

            queue.append(packet)
            stats.enqueued_frames += 1
            stats.queue_size = len(queue)
            stats.last_enqueued_frame_id = packet.metadata.frame_id
            self._condition.notify()

    def stop(self) -> None:
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        for thread in self._threads:
            thread.join(timeout=2.0)
        self.inner.stop()

    def wait_until_idle(self, timeout_seconds: float) -> bool:
        import time

        expires_at = time.monotonic() + max(0.0, timeout_seconds)
        with self._condition:
            while self._has_packets():
                remaining = expires_at - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=min(0.1, remaining))
            return True

    def stats(self) -> List[OutboundQueueStats]:
        with self._condition:
            for camera_id, queue in self._queues.items():
                if camera_id in self._stats:
                    self._stats[camera_id].queue_size = len(queue)
            return [self._stats[camera_id] for camera_id in sorted(self._stats)]

    def _run_sender(self) -> None:
        while not self._stop_event.is_set():
            packet = self._pop_next(timeout=0.5)
            if packet is None:
                continue
            self._send_packet(packet)

    def _pop_next(self, timeout: float) -> Optional[FramePacket]:
        with self._condition:
            if not self._has_packets():
                self._condition.wait(timeout=timeout)

            if not self._has_packets():
                return None

            for _ in range(len(self._camera_order)):
                camera_id = self._camera_order[self._next_camera_index % len(self._camera_order)]
                self._next_camera_index = (self._next_camera_index + 1) % len(self._camera_order)
                queue = self._queues.get(camera_id)
                if queue:
                    packet = queue.popleft()
                    self._stats[camera_id].queue_size = len(queue)
                    self._condition.notify_all()
                    return packet
            return None

    def _has_packets(self) -> bool:
        return any(bool(queue) for queue in self._queues.values())

    def _send_packet(self, packet: FramePacket) -> None:
        camera_id = packet.metadata.camera_id
        try:
            self.inner.send(packet)
        except requests.RequestException as exc:
            LOGGER.warning("Failed to send frame %s to AI Service: %s", packet.metadata.frame_id, exc)
            with self._condition:
                self._stats[camera_id].failed_sends += 1
            return

        with self._condition:
            stats = self._stats[camera_id]
            stats.sent_frames += 1
            stats.last_sent_frame_id = packet.metadata.frame_id
            self._condition.notify_all()


def build_sink(
    mode: str,
    log_every_n_frames: int,
    outbound_queue_size_per_camera: int,
    http_sender_worker_count: int,
    ai_service_base_url: Optional[str],
    ai_frame_endpoint: str,
    ai_timeout_seconds: float,
) -> FrameSink:
    if mode == "http":
        if not ai_service_base_url:
            raise ValueError("ai_service.base_url is required when --sink http is used")
        http_sink = AiServiceHttpFrameSink(ai_service_base_url, ai_frame_endpoint, ai_timeout_seconds)
        return QueuedFrameSink(http_sink, outbound_queue_size_per_camera, http_sender_worker_count)
    if mode == "console":
        return ConsoleFrameSink(log_every_n_frames)
    raise ValueError("Unsupported sink mode: {}".format(mode))
