import math
from typing import Sequence, Tuple

Point = Tuple[float, float]


def foot_point(bbox_xyxy: Sequence[float]) -> Point:
    """Diem day giua bbox: dai dien vi tri dung cua doi tuong tren mat dat."""
    x1, _, x2, y2 = (float(value) for value in bbox_xyxy)
    return (x1 + x2) / 2.0, y2


def scale_point(point: Point, from_size: Tuple[int, int], to_size: Tuple[int, int]) -> Point:
    """Doi toa do tu khung hinh detection sang khung hinh luc ve zone."""
    from_w, from_h = from_size
    to_w, to_h = to_size
    if not from_w or not from_h or (from_w == to_w and from_h == to_h):
        return point
    return point[0] * to_w / float(from_w), point[1] * to_h / float(from_h)


def point_in_polygon(point: Point, polygon: Sequence[Point]) -> bool:
    """Ray casting, cung thuat toan voi ham pointInPolygon cu o frontend."""
    x, y = point
    inside = False
    count = len(polygon)
    if count < 3:
        return False
    j = count - 1
    for i in range(count):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def bbox_area(bbox_xyxy: Sequence[float]) -> float:
    x1, y1, x2, y2 = (float(value) for value in bbox_xyxy)
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)
