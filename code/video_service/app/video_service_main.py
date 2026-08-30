import argparse
import logging
import threading
from typing import List

from .camera_worker import CameraWorker
from .config import load_config
from .frame_sink import build_sink


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read RTSP streams and emit frame metadata for AI Service.")
    parser.add_argument("--config", default="config.yaml", help="Path to Video Service YAML config.")
    parser.add_argument("--sink", default="console", choices=["console", "http"], help="Frame sink mode.")
    parser.add_argument(
        "--max-frames-per-camera",
        type=int,
        default=None,
        help="Optional test limit. Omit in normal while-true service mode.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    args = parse_args()
    config = load_config(args.config)
    sink = build_sink( # Sink là nơi Video Service gửi frame sau khi đọc RTSP và tạo metadata.
        mode=args.sink,
        log_every_n_frames=config.log_every_n_frames,
        outbound_queue_size_per_camera=config.outbound_queue_size_per_camera,
        http_sender_worker_count=config.http_sender_worker_count,
        ai_service_base_url=config.ai_service_base_url,
        ai_frame_endpoint=config.ai_frame_endpoint,
        ai_timeout_seconds=config.ai_timeout_seconds,
    )

    stop_event = threading.Event()

    threads: List[threading.Thread] = []
    workers: List[CameraWorker] = []
    sink.start()
    for camera in config.cameras:
        worker = CameraWorker(camera, config, sink, stop_event)
        workers.append(worker)
        thread = threading.Thread(
            target=worker.run,
            kwargs={"max_frames": args.max_frames_per_camera},
            name="camera-{}".format(camera.camera_id),
            daemon=True,
        )
        thread.start()
        threads.append(thread)

    try:
        while any(thread.is_alive() for thread in threads):
            for thread in threads:
                thread.join(timeout=0.5)
    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received")
    finally:
        stop_event.set()
        for worker in workers:
            worker.stop()
        for thread in threads:
            thread.join(timeout=2.0)
        if args.max_frames_per_camera is not None:
            sink.wait_until_idle(timeout_seconds=max(2.0, config.ai_timeout_seconds + 1.0))
        for stat in sink.stats():
            logging.info(
                "Outbound queue %s: received=%s enqueued=%s sent=%s dropped=%s failed=%s queue_size=%s",
                stat.camera_id,
                stat.received_frames,
                stat.enqueued_frames,
                stat.sent_frames,
                stat.dropped_frames,
                stat.failed_sends,
                stat.queue_size,
            )
        sink.stop()


if __name__ == "__main__":
    main()
