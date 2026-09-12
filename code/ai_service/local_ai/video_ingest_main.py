import argparse
import logging
import signal
import threading
from typing import List

from common.config import load_queue_config
from edge_gateway.config import load_video_ingest_config
from edge_gateway.video_ingest import VideoIngestWorker

from .queue_factory import build_frame_queue


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest RTSP cameras directly into AI Frame Broker.")
    parser.add_argument("--config", default="config.yaml", help="Path to AI Service ingest YAML config.")
    parser.add_argument("--max-frames-per-camera", type=int, default=None, help="Optional test limit.")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    args = parse_args()
    queue_config = load_queue_config()
    ingest_config = load_video_ingest_config(args.config)
    frame_queue = build_frame_queue(queue_config)
    stop_event = threading.Event()

    def stop_handler(signum, frame) -> None:
        logging.info("Stop signal received")
        stop_event.set()

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    threads: List[threading.Thread] = []
    workers: List[VideoIngestWorker] = []
    for camera in ingest_config.cameras:
        worker = VideoIngestWorker(camera, ingest_config, frame_queue, stop_event)
        workers.append(worker)
        thread = threading.Thread(
            target=worker.run,
            kwargs={"max_frames": args.max_frames_per_camera},
            name="video-ingest-{}".format(camera.camera_id),
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
        for worker in workers:
            logging.info(
                "Video ingest stopped camera=%s enqueued_frames=%s",
                worker.camera.camera_id,
                worker.enqueued_frames,
            )


if __name__ == "__main__":
    main()
