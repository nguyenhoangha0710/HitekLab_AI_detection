from dataclasses import dataclass
from datetime import datetime

import numpy as np

from .models import FrameMetadata


@dataclass(frozen=True)
class FrameJob:
    metadata: FrameMetadata
    frame: np.ndarray
    image_bytes: bytes
    received_at: datetime
