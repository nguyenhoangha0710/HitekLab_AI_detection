import argparse
import logging
import os
import signal
import threading
from dataclasses import replace
from typing import List

from .config import load_video_ingest_config
from .evidence_recorder import VideoEvidenceRecorder
from .live_viewer import DetectionHub, LiveFrameHub, start_live_viewer_server
from .transport.modal_bbox_sender import AsyncModalBboxSender, FanOutFrameSink, WebSocketModalBboxSender
from .transport.modal_http_sender import ModalFrameSender
from .transport.modal_websocket_sender import ModalWebSocketFrameSender
from .video_ingest import VideoIngestWorker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Edge Gateway: read RTSP and send frames to Modal AI Server or local viewer.")
    parser.add_argument("--config", default="config.yaml", help="Path to edge/video ingest YAML config.")
    parser.add_argument("--modal-ingest-url", default=os.getenv("MODAL_INGEST_URL", ""), help="Modal /ingest endpoint URL.")
    parser.add_argument("--modal-ws-url", default=os.getenv("MODAL_WS_URL", ""), help="Modal /ws/ingest endpoint URL.")
    parser.add_argument("--modal-bbox-url", default=os.getenv("MODAL_BBOX_URL", ""), help="Modal /detect bbox endpoint URL.")
    parser.add_argument("--modal-bbox-ws-url", default=os.getenv("MODAL_BBOX_WS_URL", ""), help="Modal /ws/detect bbox endpoint URL.")
    parser.add_argument(
        "--modal-bbox-transport",
        choices=["websocket", "http"],
        default=os.getenv("MODAL_BBOX_TRANSPORT", "websocket"),
    )
    parser.add_argument(
        "--transport",
        choices=["websocket", "http", "viewer", "viewer-ai"],
        default=os.getenv("MODAL_TRANSPORT", "websocket"),
    )
    parser.add_argument("--timeout-seconds", type=float, default=float(os.getenv("MODAL_INGEST_TIMEOUT_SECONDS", "10")))
    parser.add_argument("--confidence", type=float, default=float(os.getenv("YOLO_CONFIDENCE", "0.35")))
    parser.add_argument("--yolo-classes", default=os.getenv("YOLO_CLASSES", "person,car"))
    parser.add_argument("--tenant-id", default=os.getenv("TENANT_ID"))
    parser.add_argument(
        "--viewer-fps",
        type=float,
        default=float(os.getenv("EDGE_VIEWER_FPS", os.getenv("VIEWER_FPS", "0"))),
        help="Optional FPS override for Gateway -> Viewer stream. 0 keeps config value.",
    )
    parser.add_argument("--viewer-host", default=os.getenv("EDGE_VIEWER_HOST", "0.0.0.0"))
    parser.add_argument("--viewer-port", type=int, default=int(os.getenv("EDGE_VIEWER_PORT", "8002")))
    parser.add_argument("--ai-queue-size", type=int, default=int(os.getenv("EDGE_AI_QUEUE_SIZE", "4")))
    parser.add_argument("--ai-fps", type=float, default=float(os.getenv("EDGE_AI_FPS", os.getenv("AI_FPS", "5"))))
    parser.add_argument("--max-frames-per-camera", type=int, default=None, help="Optional test limit.")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    args = parse_args()
    ingest_config = load_video_ingest_config(args.config)
    if args.viewer_fps > 0:
        ingest_config = replace(
            ingest_config,
            cameras=[replace(camera, target_fps=args.viewer_fps) for camera in ingest_config.cameras],
        )
    viewer_thread = None
    evidence_recorder = None
    if args.transport in ("viewer", "viewer-ai"):
        live_hub = LiveFrameHub(ingest_config.cameras)
        detection_hub = DetectionHub()
        evidence_recorder = VideoEvidenceRecorder(live_hub.frames_between)
        viewer_thread = start_live_viewer_server(
            live_hub,
            ingest_config.cameras,
            host=args.viewer_host,
            port=args.viewer_port,
            detection_hub=detection_hub,
            viewer_mode="sync" if args.transport == "viewer-ai" else "live",
            evidence_recorder=evidence_recorder,
        )
        if args.transport == "viewer-ai":
            if args.modal_bbox_transport == "websocket":
                ai_sender = WebSocketModalBboxSender(
                    websocket_url=args.modal_bbox_ws_url or args.modal_bbox_url,
                    detection_hub=detection_hub,
                    timeout_seconds=args.timeout_seconds,
                    confidence_threshold=args.confidence,
                    yolo_classes=args.yolo_classes,
                    tenant_id=args.tenant_id,
                    max_queue_size=args.ai_queue_size,
                    target_fps=args.ai_fps,
                )
            else:
                ai_sender = AsyncModalBboxSender(
                    detect_url=args.modal_bbox_url,
                    detection_hub=detection_hub,
                    timeout_seconds=args.timeout_seconds,
                    confidence_threshold=args.confidence,
                    yolo_classes=args.yolo_classes,
                    tenant_id=args.tenant_id,
                    max_queue_size=args.ai_queue_size,
                    target_fps=args.ai_fps,
                )
            sender = FanOutFrameSink(live_hub, ai_sender)
        else:
            sender = live_hub
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
        if evidence_recorder is not None:
            evidence_recorder.close()
        if viewer_thread is not None:
            viewer_thread.join(timeout=1.0)
        for worker in workers:
            logging.info("Edge gateway stopped camera=%s sent_frames=%s", worker.camera.camera_id, worker.enqueued_frames)


if __name__ == "__main__":
    main()
