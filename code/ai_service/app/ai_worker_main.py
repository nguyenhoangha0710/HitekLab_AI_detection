import argparse
import logging
import signal
import threading

from .ai_worker import AIWorker
from .config import load_queue_config
from .detector import build_person_detector
from .queue_factory import build_frame_queue
from .result_publisher import build_result_publisher
from .result_store_factory import build_result_store


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consume AI frame queue and write processed frames for viewer.")
    parser.add_argument("--shard-id", type=int, default=0, help="Shard this worker consumes.")
    parser.add_argument("--worker-id", default=None, help="Optional worker id shown in processed frame overlay.")
    parser.add_argument("--poll-timeout-seconds", type=float, default=1.0)
    parser.add_argument("--max-frames", type=int, default=None, help="Optional test limit.")
    parser.add_argument("--detector", default="debug", choices=["debug", "none", "noop", "yolo", "modal"], help="Object detector backend.")
    parser.add_argument("--yolo-model", default="yolo11n.pt", help="Ultralytics YOLO model path/name.")
    parser.add_argument("--yolo-classes", default="person,car", help="Comma-separated COCO class names/ids, for example person,car or 0,2.")
    parser.add_argument("--modal-endpoint-url", default=None, help="Modal YOLO HTTP endpoint URL. Defaults to MODAL_YOLO_ENDPOINT_URL.")
    parser.add_argument("--modal-timeout-seconds", type=float, default=30.0, help="Timeout for Modal YOLO HTTP inference.")
    parser.add_argument("--confidence", type=float, default=0.35, help="YOLO confidence threshold.")
    parser.add_argument("--device", default=None, help="YOLO device, for example cpu, 0, cuda:0.")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    args = parse_args()
    config = load_queue_config()
    frame_queue = build_frame_queue(config)
    result_store = build_result_store(config)
    result_publisher = build_result_publisher(config)
    detector = build_person_detector(
        mode=args.detector,
        model_path=args.yolo_model,
        confidence_threshold=args.confidence,
        device=args.device,
        yolo_classes=args.yolo_classes,
        modal_endpoint_url=args.modal_endpoint_url,
        modal_timeout_seconds=args.modal_timeout_seconds,
    )
    stop_event = threading.Event()

    def stop_handler(signum, frame) -> None:
        logging.info("Stop signal received")
        stop_event.set()

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    worker = AIWorker(
        frame_queue=frame_queue,
        result_store=result_store,
        result_publisher=result_publisher,
        detector=detector,
        shard_id=args.shard_id,
        worker_id=args.worker_id,
        poll_timeout_seconds=args.poll_timeout_seconds,
        stop_event=stop_event,
    )
    try:
        worker.run(max_frames=args.max_frames)
    finally:
        result_publisher.close()


if __name__ == "__main__":
    main()
