import argparse
import logging
import os
import signal
import threading
from typing import List

from .config import load_video_ingest_config
from .live_viewer import LiveFrameHub, start_live_viewer_server
from .transport.modal_http_sender import ModalFrameSender
from .transport.modal_websocket_sender import ModalWebSocketFrameSender
from .video_ingest import VideoIngestWorker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Edge Gateway: read RTSP and send frames to Modal AI Server or local viewer.")
    parser.add_argument("--config", default="config.yaml", help="Path to edge/video ingest YAML config.")
    parser.add_argument("--modal-ingest-url", default=os.getenv("MODAL_INGEST_URL", ""), help="Modal /ingest endpoint URL.")
    parser.add_argument("--modal-ws-url", default=os.getenv("MODAL_WS_URL", ""), help="Modal /ws/ingest endpoint URL.")
    parser.add_argument("--transport", choices=["websocket", "http", "viewer"], default=os.getenv("MODAL_TRANSPORT", "websocket"))
    parser.add_argument("--timeout-seconds", type=float, default=float(os.getenv("MODAL_INGEST_TIMEOUT_SECONDS", "10")))
    parser.add_argument("--confidence", type=float, default=float(os.getenv("YOLO_CONFIDENCE", "0.35")))
    parser.add_argument("--yolo-classes", default=os.getenv("YOLO_CLASSES", "person,car"))
    parser.add_argument("--tenant-id", default=os.getenv("TENANT_ID"))
    parser.add_argument("--viewer-host", default=os.getenv("EDGE_VIEWER_HOST", "0.0.0.0"))
    parser.add_argument("--viewer-port", type=int, default=int(os.getenv("EDGE_VIEWER_PORT", "8002")))
    parser.add_argument("--max-frames-per-camera", type=int, default=None, help="Optional test limit.")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    args = parse_args()
    ingest_config = load_video_ingest_config(args.config)
    viewer_thread = None
    if args.transport == "viewer":
        sender = LiveFrameHub(ingest_config.cameras)
        viewer_thread = start_live_viewer_server(
            sender,
            ingest_config.cameras,
            host=args.viewer_host,
            port=args.viewer_port,
        )
    elif args.transport == "websocket":
        sender = ModalWebSocketFrameSender(
            websocket_url=args.modal_ws_url or args.modal_ingest_url,
            timeout_seconds=args.timeout_seconds,
            confidence_threshold=args.confidence,
            yolo_classes=args.yolo_classes,
            tenant_id=args.tenant_id,
        )
    else:
        sender = ModalFrameSender(
            ingest_url=args.modal_ingest_url,
            timeout_seconds=args.timeout_seconds,
            confidence_threshold=args.confidence,
            yolo_classes=args.yolo_classes,
            tenant_id=args.tenant_id,
        )
    stop_event = threading.Event()

    def stop_handler(signum, frame) -> None:
        logging.info("Stop signal received")
        stop_event.set()

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    threads: List[threading.Thread] = []
    workers: List[VideoIngestWorker] = []
    for camera in ingest_config.cameras:
        worker = VideoIngestWorker(camera, ingest_config, sender, stop_event)
        workers.append(worker)
        thread = threading.Thread(
            target=worker.run,
            kwargs={"max_frames": args.max_frames_per_camera},
            name="edge-camera-{}".format(camera.camera_id),
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
        sender.close()
        if viewer_thread is not None:
            viewer_thread.join(timeout=1.0)
        for worker in workers:
            logging.info("Edge gateway stopped camera=%s sent_frames=%s", worker.camera.camera_id, worker.enqueued_frames)


if __name__ == "__main__":
    main()
