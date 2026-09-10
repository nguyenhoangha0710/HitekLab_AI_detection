import base64
from typing import Dict, List

import modal


APP_NAME = "hitek-yolo11-person-car"
DEFAULT_MODEL = "yolo11n.pt"
DEFAULT_CONFIDENCE = 0.35
DEFAULT_IMAGE_SIZE = 640
COCO_CLASS_IDS: Dict[str, int] = {
    "person": 0,
    "car": 2,
}


image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install("fastapi[standard]", "opencv-python-headless", "numpy", "ultralytics")
)

app = modal.App(APP_NAME)


def _parse_class_ids(value) -> List[int]:
    if value is None:
        return [COCO_CLASS_IDS["person"], COCO_CLASS_IDS["car"]]

    raw_items = value
    if isinstance(value, str):
        raw_items = value.split(",")

    class_ids: List[int] = []
    for raw_item in raw_items:
        item = str(raw_item).strip().lower()
        if not item:
            continue
        if item.isdigit():
            class_id = int(item)
        elif item in COCO_CLASS_IDS:
            class_id = COCO_CLASS_IDS[item]
        else:
            raise ValueError("Unsupported class '{}'. Use person, car, 0, or 2.".format(item))
        if class_id not in class_ids:
            class_ids.append(class_id)
    return class_ids or [COCO_CLASS_IDS["person"], COCO_CLASS_IDS["car"]]


@app.cls(image=image, gpu="T4", timeout=120, scaledown_window=300)
class Yolo11PersonCarService:
    model_name: str = modal.parameter(default=DEFAULT_MODEL)

    @modal.enter()
    def load_model(self):
        from ultralytics import YOLO

        self.model = YOLO(self.model_name)

    def _run_detection(self, payload: dict) -> dict:
        import cv2
        import numpy as np

        image_b64 = payload["image_b64"]
        confidence = float(payload.get("confidence", DEFAULT_CONFIDENCE))
        image_size = int(payload.get("imgsz", DEFAULT_IMAGE_SIZE))
        class_ids = _parse_class_ids(payload.get("classes", ["person", "car"]))
        return_image = bool(payload.get("return_image", False))

        image_bytes = base64.b64decode(image_b64)
        np_buffer = np.frombuffer(image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(np_buffer, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Cannot decode image_b64 as an image.")

        results = self.model.predict(
            frame,
            conf=confidence,
            classes=class_ids,
            imgsz=image_size,
            verbose=False,
        )

        detections = []
        result = results[0] if results else None
        names = result.names if result is not None else {}
        boxes = result.boxes if result is not None else None

        if boxes is not None:
            for box in boxes:
                class_id = int(box.cls[0].item())
                score = float(box.conf[0].item())
                x1, y1, x2, y2 = [int(value) for value in box.xyxy[0].tolist()]
                detections.append(
                    {
                        "class_id": class_id,
                        "class_name": str(names.get(class_id, class_id)),
                        "confidence": score,
                        "bbox_xyxy": [x1, y1, x2, y2],
                    }
                )

                if return_image:
                    color = (32, 220, 80) if class_id == COCO_CLASS_IDS["person"] else (40, 170, 255)
                    label = "{} {:.2f}".format(names.get(class_id, class_id), score)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(frame, label, (x1, max(18, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        response = {
            "camera_id": payload.get("camera_id"),
            "frame_id": payload.get("frame_id"),
            "sequence_number": payload.get("sequence_number"),
            "model": self.model_name,
            "classes": class_ids,
            "detections": detections,
            "detection_count": len(detections),
        }

        if return_image:
            ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if ok:
                response["image_b64"] = base64.b64encode(encoded.tobytes()).decode("ascii")

        return response

    @modal.method()
    def detect_jpeg(self, payload: dict) -> dict:
        return self._run_detection(payload)

    @modal.fastapi_endpoint(method="POST", docs=True)
    def detect(self, payload: dict) -> dict:
        return self._run_detection(payload)


@app.local_entrypoint()
def main(image_path: str = "", confidence: float = DEFAULT_CONFIDENCE):
    if not image_path:
        print("Deploy endpoint: modal deploy code/ai_service/modal_yolo11_service.py")
        print("Dev endpoint:    modal serve code/ai_service/modal_yolo11_service.py")
        return

    with open(image_path, "rb") as image_file:
        image_b64 = base64.b64encode(image_file.read()).decode("ascii")

    payload = {
        "camera_id": "local-test-camera",
        "frame_id": "local-test-frame",
        "sequence_number": 1,
        "image_b64": image_b64,
        "classes": ["person", "car"],
        "confidence": confidence,
        "return_image": False,
    }
    result = Yolo11PersonCarService(model_name=DEFAULT_MODEL).detect_jpeg.remote(payload)
    print(result)
