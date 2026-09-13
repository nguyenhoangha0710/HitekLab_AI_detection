from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import load_settings, project_root
from .database import Database
from .repositories.camera_repository import CameraRepository
from .routers.cameras import create_camera_router, create_reference_frame_router
from .routers.zones import create_zone_router
from .services.camera_catalog_service import CameraCatalogService


def create_app() -> FastAPI:
    settings = load_settings()
    database = Database(settings.database_path)
    database.initialize()
    settings.reference_frame_dir.mkdir(parents=True, exist_ok=True)

    with database.session() as connection:
        cameras = CameraCatalogService(settings.camera_config_path).load_cameras()
        CameraRepository(connection).seed_from_config(settings.tenant_id, cameras)

    app = FastAPI(title="Hitek Zone Management Service")
    app.include_router(create_camera_router(database, settings))
    app.include_router(create_reference_frame_router(database, settings))
    app.include_router(create_zone_router(database))

    frontend_dir = project_root() / "code" / "zone_service" / "frontend"
    app.mount("/static", StaticFiles(directory=str(frontend_dir / "src")), name="static")

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "zone-management-service",
            "database": str(settings.database_path),
            "edge_gateway_base_url": settings.edge_gateway_base_url,
        }

    @app.get("/")
    def index():
        return FileResponse(str(frontend_dir / "index.html"))

    @app.get("/detect")
    def detect_view():
        return RedirectResponse(url="/")

    return app


app = create_app()
