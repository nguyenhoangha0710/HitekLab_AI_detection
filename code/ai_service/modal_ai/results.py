import queue
from typing import List

from .runtime import result_queues, state_store
from .settings import RESULT_QUEUE_LIMIT


def latest_results_snapshot() -> List[dict]:
    values = []
    for key, value in state_store.items():
        if str(key).startswith("latest:"):
            values.append(value)
    values.sort(key=lambda item: str(item.get("camera_id", "")))
    return values


def publish_result(result: dict, shard_id: int) -> None:
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
    result_queue = result_queues[shard_id]
    try:
        # Result queue chi phuc vu viewer live. Neu viewer doc cham hon worker,
        # bo ket qua cu nhat trong shard de tranh viewer bi xem backlog cu.
        current_size = result_queue.len()
        drop_count = max(0, current_size - RESULT_QUEUE_LIMIT + 1)
        if drop_count:
            result_queue.get_many(drop_count, block=False)
        result_queue.put(result, block=False)
    except queue.Full:
        pass
