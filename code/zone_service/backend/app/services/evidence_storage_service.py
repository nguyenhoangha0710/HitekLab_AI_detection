from __future__ import annotations

from datetime import timedelta
from io import BytesIO
import mimetypes
from pathlib import Path
from typing import Optional, Tuple

from ..config import ZoneServiceSettings


class EvidenceStorageService:
    def __init__(self, settings: ZoneServiceSettings) -> None:
        self.settings = settings

    @property
    def backend(self) -> str:
        return self.settings.evidence_storage_backend

    def is_minio_enabled(self) -> bool:
        return (
            self.backend == "minio"
            and bool(self.settings.minio_endpoint)
            and bool(self.settings.minio_access_key)
            and bool(self.settings.minio_secret_key)
        )

    def save_bytes(self, storage_key: str, content: bytes, content_type: str) -> int:
        if self.is_minio_enabled():
            self._save_to_minio(storage_key, content, content_type)
        else:
            self._save_to_local(storage_key, content)
        return len(content)

    def local_path(self, storage_key: str) -> Optional[Path]:
        path = (self.settings.evidence_dir / storage_key).resolve()
        root = self.settings.evidence_dir.resolve()
        if not str(path).startswith(str(root)):
            return None
        return path

    def presigned_url(self, storage_key: str) -> str:
        client = self._minio_client()
        return client.presigned_get_object(
            self.settings.minio_bucket,
            storage_key,
            expires=timedelta(minutes=10),
        )

    def read_bytes(self, storage_key: str) -> Tuple[bytes, str]:
        if self.is_minio_enabled():
            return self._read_from_minio(storage_key)
        path = self.local_path(storage_key)
        if path is None or not path.exists():
            raise FileNotFoundError(storage_key)
        media_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        return path.read_bytes(), media_type

    def _save_to_local(self, storage_key: str, content: bytes) -> None:
        path = self.local_path(storage_key)
        if path is None:
            raise ValueError("Invalid evidence storage key")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def _save_to_minio(self, storage_key: str, content: bytes, content_type: str) -> None:
        client = self._minio_client()
        bucket = self.settings.minio_bucket
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
        client.put_object(
            bucket,
            storage_key,
            BytesIO(content),
            length=len(content),
            content_type=content_type,
        )

    def _read_from_minio(self, storage_key: str) -> Tuple[bytes, str]:
        client = self._minio_client()
        response = client.get_object(self.settings.minio_bucket, storage_key)
        try:
            content = response.read()
            content_type = response.headers.get("content-type") or "application/octet-stream"
            return content, content_type
        finally:
            response.close()
            response.release_conn()

    def _minio_client(self):
        try:
            from minio import Minio
        except ImportError as exc:
            raise RuntimeError("MinIO storage requires the 'minio' Python package") from exc

        return Minio(
            self.settings.minio_endpoint,
            access_key=self.settings.minio_access_key,
            secret_key=self.settings.minio_secret_key,
            secure=self.settings.minio_secure,
        )
