"""Media storage. S3-compatible (MinIO locally, real S3 on AWS)."""
from pathlib import Path
from typing import Protocol

import boto3
from botocore.client import Config

from recall.config import get_settings


class MediaStorage(Protocol):
    def put_file(self, local_path: Path, key: str) -> int: ...
    def put_bytes(self, data: bytes, key: str, content_type: str = "application/octet-stream") -> int: ...
    def get_to_file(self, key: str, local_path: Path) -> None: ...
    def presigned_url(self, key: str, expires_seconds: int = 3600) -> str: ...
    def exists(self, key: str) -> bool: ...


def _client(endpoint_url: str):
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4"),
    )


class S3Storage:
    def __init__(self):
        settings = get_settings()
        self._bucket = settings.s3_bucket
        self._s3 = _client(settings.s3_endpoint_url)
        # Presigned URLs must be signed against the endpoint the browser will hit.
        public_endpoint = settings.s3_public_endpoint_url or settings.s3_endpoint_url
        self._public_s3 = (
            self._s3 if public_endpoint == settings.s3_endpoint_url else _client(public_endpoint)
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        existing = [b["Name"] for b in self._s3.list_buckets().get("Buckets", [])]
        if self._bucket not in existing:
            self._s3.create_bucket(Bucket=self._bucket)

    def put_file(self, local_path: Path, key: str) -> int:
        self._s3.upload_file(str(local_path), self._bucket, key)
        return local_path.stat().st_size

    def put_bytes(self, data: bytes, key: str, content_type: str = "application/octet-stream") -> int:
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
        return len(data)

    def get_to_file(self, key: str, local_path: Path) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self._s3.download_file(self._bucket, key, str(local_path))

    def presigned_url(self, key: str, expires_seconds: int = 3600) -> str:
        return self._public_s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )

    def exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self._bucket, Key=key)
            return True
        except self._s3.exceptions.ClientError:
            return False


class LocalDirStorage:
    """Test double backed by a temp directory."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def put_file(self, local_path: Path, key: str) -> int:
        data = Path(local_path).read_bytes()
        self._path(key).write_bytes(data)
        return len(data)

    def put_bytes(self, data: bytes, key: str, content_type: str = "application/octet-stream") -> int:
        self._path(key).write_bytes(data)
        return len(data)

    def get_to_file(self, key: str, local_path: Path) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes((self.root / key).read_bytes())

    def presigned_url(self, key: str, expires_seconds: int = 3600) -> str:
        return f"file://{self.root / key}"

    def exists(self, key: str) -> bool:
        return (self.root / key).exists()
