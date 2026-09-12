import queue
from typing import List

from .runtime import result_queue, state_store


def latest_results_snapshot() -> List[dict]:
    values = []
    for key, value in state_store.items():
        if str(key).startswith("latest:"):
            values.append(value)
    values.sort(key=lambda item: str(item.get("camera_id", "")))
    return values


def publish_result(result: dict) -> None:
    camera_id = result["camera_id"]
    if camera_id:
        state_store["latest:{}".format(camera_id)] = result
        state_store["stats:{}".format(camera_id)] = {
            "camera_id": camera_id,
            "last_frame_id": result.get("frame_id"),
            "last_sequence_number": result.get("sequence_number"),
            "last_processed_at": result.get("modal_processed_at"),
            "last_detection_count": result.get("detection_count"),
        }
    try:
        result_queue.put(result, block=False)
    except queue.Full:
        pass
