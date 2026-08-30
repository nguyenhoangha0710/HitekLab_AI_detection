import argparse
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_config
from app.time_utils import utc_now


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="View an RTSP stream with OpenCV.")
    parser.add_argument("url", help="RTSP URL, for example rtsp://localhost:8554/camera1")
    parser.add_argument("--config", default="config.yaml", help="Path to Video Service config.")
    parser.add_argument("--camera-name", default=None, help="Camera name to display. Overrides config lookup.")
    parser.add_argument("--window-name", default="RTSP Viewer", help="OpenCV window name.")
    parser.add_argument("--retry-delay", type=float, default=2.0, help="Seconds to wait before reconnecting.")
    parser.add_argument("--width", type=int, default=960, help="Display width.")
    parser.add_argument("--height", type=int, default=540, help="Display height.")
    parser.add_argument(
        "--display-fps",
        type=float,
        default=15.0,
        help="Maximum UI display FPS. Use 0 to disable display throttling.",
    )
    parser.add_argument(
        "--read-fps",
        type=float,
        default=0.0,
        help="Maximum RTSP read FPS. Use 0 to read as fast as the stream provides.",
    )
    return parser.parse_args()


def open_capture(url: str) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    return capture


@dataclass(frozen=True)
class LatestFrame:
    frame: np.ndarray
    frame_time: datetime
    frame_count: int


class LatestFrameBuffer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: Optional[LatestFrame] = None

    def update(self, frame: np.ndarray, frame_time: datetime, frame_count: int) -> None:
        with self._lock:
            self._latest = LatestFrame(frame=frame, frame_time=frame_time, frame_count=frame_count)

    def get(self) -> Optional[LatestFrame]:
        with self._lock:
            return self._latest


def throttle_loop(loop_started_at: float, fps: float) -> None:
    if fps <= 0:
        return
    frame_interval = 1.0 / fps
    elapsed = time.monotonic() - loop_started_at
    sleep_for = frame_interval - elapsed
    if sleep_for > 0:
        time.sleep(sleep_for)


def resolve_camera_name(url: str, config_path: str, override: str = None) -> str:
    if override:
        return override

    path = Path(config_path)
    if not path.exists():
        return url

    try:
        config = load_config(str(path))
    except Exception:
        return url

    for camera in config.cameras:
        if camera.source_url == url:
            return camera.name
    return url


def compact_source_label(url: str) -> str:
    return url.replace("rtsp://", "")


def compact_time_label(value) -> str:
    return value.strftime("%H:%M:%S.") + "{:03d}Z".format(value.microsecond // 1000)


def draw_status_bar(
    frame,
    camera_name: str,
    frame_time,
    frame_count: int,
    url: str,
    read_fps: float,
    display_fps: float,
) -> None:
    read_label = "max" if read_fps <= 0 else "{:g}".format(read_fps)
    display_label = "max" if display_fps <= 0 else "{:g}".format(display_fps)
    label = "{} | {} | frame {} | read {} / ui {} | {}".format(
        camera_name,
        compact_time_label(frame_time),
        frame_count,
        read_label,
        display_label,
        compact_source_label(url),
    )
    x = 8
    y = 20
    padding_x = 8
    padding_y = 5
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.5
    thickness = 1
    max_chars = max(20, int(frame.shape[1] / 8.5))
    label = label[:max_chars]
    text_size, _ = cv2.getTextSize(label, font, font_scale, thickness)
    box_width = min(text_size[0] + padding_x * 2, frame.shape[1] - 16)
    box_height = text_size[1] + padding_y * 2

    overlay = frame.copy()
    cv2.rectangle(
        overlay,
        (x, y - text_size[1] - padding_y),
        (x + box_width, y - text_size[1] - padding_y + box_height),
        (0, 0, 0),
        -1,
    )
    cv2.addWeighted(overlay, 0.38, frame, 0.62, 0, frame)
    cv2.putText(
        frame,
        label,
        (x + padding_x, y - 3),
        font,
        font_scale,
        (245, 245, 245),
        thickness,
        cv2.LINE_AA,
    )


def draw_waiting_frame(width: int, height: int, camera_name: str, url: str) -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    text = "Waiting for {} ({})".format(camera_name, compact_source_label(url))
    cv2.putText(
        frame,
        text[:90],
        (16, 32),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (220, 220, 220),
        1,
        cv2.LINE_AA,
    )
    return frame


def read_rtsp_loop(
    url: str,
    retry_delay: float,
    read_fps: float,
    latest_frame_buffer: LatestFrameBuffer,
    stop_event: threading.Event,
) -> None:
    frame_count = 0
    capture = open_capture(url)

    while not stop_event.is_set():
        loop_started_at = time.monotonic()

        if not capture.isOpened():
            print("Stream is not opened. Reconnecting in {}s...".format(retry_delay))
            capture.release()
            time.sleep(retry_delay)
            capture = open_capture(url)
            continue

        ok, frame = capture.read()
        if not ok or frame is None:
            print("Failed to read frame. Reconnecting in {}s...".format(retry_delay))
            capture.release()
            time.sleep(retry_delay)
            capture = open_capture(url)
            continue

        frame_count += 1
        latest_frame_buffer.update(frame, utc_now(), frame_count)
        throttle_loop(loop_started_at, read_fps)

    capture.release()


def main() -> None:
    args = parse_args()
    camera_name = resolve_camera_name(args.url, args.config, args.camera_name)
    latest_frame_buffer = LatestFrameBuffer()
    stop_event = threading.Event()

    print("Opening {}".format(args.url))
    print("Camera: {}".format(camera_name))
    print("Read FPS: {}".format("max" if args.read_fps <= 0 else args.read_fps))
    print("Display FPS: {}".format("max" if args.display_fps <= 0 else args.display_fps))
    print("Press q or ESC to exit.")

    reader = threading.Thread(
        target=read_rtsp_loop,
        args=(args.url, args.retry_delay, args.read_fps, latest_frame_buffer, stop_event),
        daemon=True,
    )
    reader.start()

    try:
        while True:
            loop_started_at = time.monotonic()
            latest = latest_frame_buffer.get()

            if latest is None:
                display = draw_waiting_frame(args.width, args.height, camera_name, args.url)
            else:
                display = cv2.resize(latest.frame, (args.width, args.height), interpolation=cv2.INTER_AREA)
                draw_status_bar(
                    display,
                    camera_name,
                    latest.frame_time,
                    latest.frame_count,
                    args.url,
                    args.read_fps,
                    args.display_fps,
                )

            cv2.imshow(args.window_name, display)
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break

            throttle_loop(loop_started_at, args.display_fps)
    finally:
        stop_event.set()
        reader.join(timeout=2)
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
