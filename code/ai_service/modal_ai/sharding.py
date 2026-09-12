import hashlib
import uuid


def shard_id_for_camera(camera_id: str, num_shards: int) -> int:
    if num_shards <= 0:
        raise ValueError("num_shards must be greater than 0")

    try:
        return int(uuid.UUID(camera_id)) % num_shards
    except ValueError:
        pass

    digest = hashlib.sha256(camera_id.encode("utf-8")).hexdigest()
    return int(digest, 16) % num_shards


def frame_queue_name(prefix: str, shard_id: int) -> str:
    return "{}-{}".format(prefix, shard_id)
