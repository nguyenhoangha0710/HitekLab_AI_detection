import uuid
import time
import urllib.request
from typing import Iterable, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from ..access_control import AccessControl, Principal
from ..auth import principal_dependency
from ..config import ZoneServiceSettings
from ..database import Database
from ..models import CameraOut, ReferenceFrameOut
from ..repositories.camera_repository import CameraRepository
from ..repositories.reference_frame_repository import ReferenceFrameRepository
from ..serializers import camera_out, reference_frame_out, reference_frame_path
from ..services.frame_capture_service import FrameCaptureService


def create_camera_router(
    database: Database, settings: ZoneServiceSettings, access: Optional[AccessControl] = None
) -> APIRouter:
    router = APIRouter(prefix="/api/cameras", tags=["cameras"])
    access = access or AccessControl(database, settings)
    current_principal = principal_dependency(access)

    @router.get("", response_model=List[CameraOut])
    def list_cameras(principal: Principal = Depends(current_principal)):
        with database.session() as connection:
            rows = CameraRepository(connection, database).list_cameras()
            allowed = access.allowed_camera_ids(principal, connection)
            if allowed is not None:
                allowed_set = set(allowed)
                rows = [row for row in rows if str(row["id"]) in allowed_set]
            return [camera_out(row, settings.edge_gateway_base_url) for row in rows]

    @router.get("/{camera_id}", response_model=CameraOut)
    def get_camera(camera_id: str, principal: Principal = Depends(current_principal)):
        with database.session() as connection:
            row = access.require_camera(principal, connection, camera_id)
            return camera_out(row, settings.edge_gateway_base_url)

    @router.get("/{camera_id}/latest.jpg")
    def proxy_latest_frame(camera_id: str, principal: Principal = Depends(current_principal)):
        with database.session() as connection:
            access.require_camera(principal, connection, camera_id)

        url = "{}/api/cameras/{}/latest.jpg".format(settings.edge_gateway_base_url, camera_id)
        try:
            request = urllib.request.Request(url, headers={"Accept": "image/jpeg"})
            with urllib.request.urlopen(request, timeout=5) as response:
                image_bytes = response.read()
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Cannot read latest frame from Edge Gateway: {}".format(exc))
        return StreamingResponse(iter([image_bytes]), media_type="image/jpeg")

    @router.get("/{camera_id}/frames/{frame_id}.jpg")
    def proxy_frame_by_id(camera_id: str, frame_id: str, principal: Principal = Depends(current_principal)):
        with database.session() as connection:
            access.require_camera(principal, connection, camera_id)

        url = "{}/api/cameras/{}/frames/{}.jpg".format(settings.edge_gateway_base_url, camera_id, frame_id)
        try:
            request = urllib.request.Request(url, headers={"Accept": "image/jpeg"})
            with urllib.request.urlopen(request, timeout=5) as response:
                image_bytes = response.read()
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Cannot read matched frame from Edge Gateway: {}".format(exc))
        return StreamingResponse(iter([image_bytes]), media_type="image/jpeg")

    @router.get("/{camera_id}/mjpeg")
    def proxy_mjpeg(camera_id: str, principal: Principal = Depends(current_principal)):
        with database.session() as connection:
            access.require_camera(principal, connection, camera_id)

        def stream() -> Iterable[bytes]:
            url = "{}/api/cameras/{}/mjpeg".format(settings.edge_gateway_base_url, camera_id)
            while True:
                try:
                    request = urllib.request.Request(url, headers={"Accept": "multipart/x-mixed-replace"})
                    with urllib.request.urlopen(request, timeout=30) as response:
                        while True:
                            chunk = response.read(8192)
                            if not chunk:
                                break
                            yield chunk
                except Exception:
                    time.sleep(1)

        return StreamingResponse(stream(), media_type="multipart/x-mixed-replace; boundary=frame")

    @router.post("/{camera_id}/reference-frame", response_model=ReferenceFrameOut, status_code=201)
    def capture_reference_frame(camera_id: str, principal: Principal = Depends(current_principal)):
        reference_id = str(uuid.uuid4())
        with database.session() as connection:
            camera = access.require_camera(principal, connection, camera_id, "admin")

            try:
                storage_key, width, height, captured_at = FrameCaptureService(
                    settings.edge_gateway_base_url,
                    settings.reference_frame_dir,
                ).capture_latest(camera_id, reference_id)
            except Exception as exc:
                raise HTTPException(status_code=502, detail="Cannot capture frame from Edge Gateway: {}".format(exc))

            row = ReferenceFrameRepository(connection, database).create(
                camera_id=camera_id,
                storage_key=storage_key,
                mime_type="image/jpeg",
                frame_width=width,
                frame_height=height,
                captured_at=captured_at,
            )
            return reference_frame_out(row, "/api/reference-frames/{}".format(row["id"]))

    @router.get("/{camera_id}/reference-frame", response_model=ReferenceFrameOut)
    def get_reference_frame(camera_id: str, principal: Principal = Depends(current_principal)):
        with database.session() as connection:
            access.require_camera(principal, connection, camera_id)
            row = ReferenceFrameRepository(connection, database).get_latest(camera_id)
            if row is None:
                raise HTTPException(status_code=404, detail="No reference frame captured yet")
            return reference_frame_out(row, "/api/reference-frames/{}".format(row["id"]))

    @router.get("/{camera_id}/detections/stream")
    def proxy_detection_stream(camera_id: str, principal: Principal = Depends(current_principal)):
        with database.session() as connection:
            access.require_camera(principal, connection, camera_id)

        def stream() -> Iterable[bytes]:
            url = "{}/api/cameras/{}/detections/stream".format(settings.edge_gateway_base_url, camera_id)
            while True:
                try:
                    request = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
                    with urllib.request.urlopen(request, timeout=30) as response:
                        while True:
                            chunk = response.readline()
                            if not chunk:
                                break
                            yield chunk
                except Exception:
                    yield b": waiting-for-edge-detections\n\n"
                    time.sleep(1)

        return StreamingResponse(stream(), media_type="text/event-stream")

    return router


def create_reference_frame_router(
    database: Database, settings: ZoneServiceSettings, access: Optional[AccessControl] = None
) -> APIRouter:
    router = APIRouter(prefix="/api/reference-frames", tags=["reference-frames"])
    access = access or AccessControl(database, settings)
    current_principal = principal_dependency(access)

    @router.get("/{reference_id}")
    def get_reference_image(reference_id: str, principal: Principal = Depends(current_principal)):
        with database.session() as connection:
            row = access.require_via(principal, connection, "camera_reference_frame", reference_id)
            path = reference_frame_path(settings.reference_frame_dir, row["storage_key"])
            if path is None or not path.exists():
                raise HTTPException(status_code=404, detail="Reference image file not found")
            return FileResponse(str(path), media_type=row["mime_type"])

    return router
