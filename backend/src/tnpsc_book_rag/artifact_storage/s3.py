"""S3 / Backblaze B2 compatible implementation of the artifact storage boundary."""

from hashlib import sha256
from io import BytesIO
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from tnpsc_book_rag.telemetry_logging import run_in_thread_with_context
from tnpsc_book_rag.artifact_storage.errors import (
    ArtifactChecksumMismatchError,
    ArtifactConflictError,
    ArtifactNotFoundError,
    ArtifactStorageError,
    ArtifactTooLargeError,
)
from tnpsc_book_rag.artifact_storage.keys import validate_sha256
from tnpsc_book_rag.artifact_storage.models import ArtifactKey, ArtifactMetadata, ArtifactWriteResult
from tnpsc_book_rag.artifact_storage.ports import ReadableBinary, WritableBinary

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

_DEFAULT_CHUNK_SIZE = 1024 * 1024


class S3ArtifactStorage:
    """S3-compatible immutable object storage adapter (Backblaze B2, AWS S3, MinIO)."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        region_name: str = "us-west-004",
        prefix: str = "",
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        s3_client: Any = None,
    ) -> None:
        if chunk_size <= 0:
            msg = "artifact I/O chunk size must be positive"
            raise ValueError(msg)

        self._endpoint_url = endpoint_url
        self._bucket = bucket
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._region_name = region_name
        self._prefix = prefix.strip("/")
        self._chunk_size = chunk_size

        if s3_client is not None:
            self._s3_client = s3_client
        else:
            self._s3_client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                region_name=region_name,
                config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
            )

    def _get_s3_key(self, key: ArtifactKey) -> str:
        if self._prefix:
            return f"{self._prefix}/{key.value}"
        return key.value

    async def initialize(self) -> None:
        """Verify bucket access during startup."""
        await run_in_thread_with_context(self._initialize)

    def _initialize(self) -> None:
        try:
            self._s3_client.head_bucket(Bucket=self._bucket)
        except ClientError as exc:
            msg = f"Failed to access S3 bucket '{self._bucket}': {exc}"
            raise ArtifactStorageError(msg) from exc

    async def is_ready(self) -> bool:
        """Check if S3 bucket is reachable."""
        try:
            await run_in_thread_with_context(self._initialize)
            return True
        except Exception:
            return False

    async def stat(self, key: ArtifactKey) -> ArtifactMetadata:
        """Get object metadata including sha256 checksum stored in x-amz-meta-sha256."""
        return await run_in_thread_with_context(self._stat, key)

    def _stat(self, key: ArtifactKey) -> ArtifactMetadata:
        s3_key = self._get_s3_key(key)
        try:
            head = self._s3_client.head_object(Bucket=self._bucket, Key=s3_key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                raise ArtifactNotFoundError(f"Artifact not found at key '{key.value}'") from exc
            raise ArtifactStorageError(f"S3 head_object error for '{key.value}': {exc}") from exc

        metadata = head.get("Metadata", {})
        sha256_val = metadata.get("sha256")
        size_bytes = head.get("ContentLength", 0)

        if not sha256_val:
            body = self._s3_client.get_object(Bucket=self._bucket, Key=s3_key)["Body"]
            hasher = sha256()
            while chunk := body.read(self._chunk_size):
                hasher.update(chunk)
            sha256_val = hasher.hexdigest()

        return ArtifactMetadata(key=key, size_bytes=size_bytes, sha256=sha256_val)

    async def put(
        self,
        key: ArtifactKey,
        source: ReadableBinary,
        *,
        expected_sha256: str | None = None,
        max_bytes: int | None = None,
    ) -> ArtifactWriteResult:
        """Atomically upload object to S3 if not existing; check immutability if exists."""
        if expected_sha256 is not None:
            expected_sha256 = validate_sha256(expected_sha256)
        if max_bytes is not None and max_bytes <= 0:
            msg = "max_bytes limit must be positive"
            raise ValueError(msg)

        return await run_in_thread_with_context(
            self._put, key, source, expected_sha256, max_bytes
        )

    def _put(
        self,
        key: ArtifactKey,
        source: ReadableBinary,
        expected_sha256: str | None,
        max_bytes: int | None,
    ) -> ArtifactWriteResult:
        s3_key = self._get_s3_key(key)

        try:
            existing = self._stat(key)
            if expected_sha256 is not None and existing.sha256 != expected_sha256:
                raise ArtifactConflictError(
                    f"Artifact at '{key.value}' already exists with different sha256"
                )
            hasher = sha256()
            bytes_read = 0
            while chunk := source.read(self._chunk_size):
                bytes_read += len(chunk)
                if max_bytes is not None and bytes_read > max_bytes:
                    raise ArtifactTooLargeError(f"Artifact exceeds limit of {max_bytes} bytes")
                hasher.update(chunk)
            digest = hasher.hexdigest()
            if expected_sha256 is not None and digest != expected_sha256:
                raise ArtifactChecksumMismatchError(
                    f"Uploaded content sha256 '{digest}' does not match expected '{expected_sha256}'"
                )
            if digest != existing.sha256:
                raise ArtifactConflictError(
                    f"Artifact at '{key.value}' already exists with different sha256 '{existing.sha256}' vs uploaded '{digest}'"
                )
            return ArtifactWriteResult(artifact=existing, created=False)
        except ArtifactNotFoundError:
            pass

        hasher = sha256()
        buffer = BytesIO()
        bytes_read = 0
        while chunk := source.read(self._chunk_size):
            bytes_read += len(chunk)
            if max_bytes is not None and bytes_read > max_bytes:
                raise ArtifactTooLargeError(f"Artifact exceeds limit of {max_bytes} bytes")
            hasher.update(chunk)
            buffer.write(chunk)

        digest = hasher.hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise ArtifactChecksumMismatchError(
                f"Uploaded content sha256 '{digest}' does not match expected '{expected_sha256}'"
            )

        buffer.seek(0)
        self._s3_client.put_object(
            Bucket=self._bucket,
            Key=s3_key,
            Body=buffer.getvalue(),
            Metadata={"sha256": digest},
        )
        metadata = ArtifactMetadata(key=key, size_bytes=bytes_read, sha256=digest)
        return ArtifactWriteResult(artifact=metadata, created=True)

    async def copy_to(
        self,
        key: ArtifactKey,
        destination: WritableBinary,
    ) -> ArtifactMetadata:
        """Stream object from S3 to destination."""
        return await run_in_thread_with_context(self._copy_to, key, destination)

    def _copy_to(
        self,
        key: ArtifactKey,
        destination: WritableBinary,
    ) -> ArtifactMetadata:
        s3_key = self._get_s3_key(key)
        try:
            obj = self._s3_client.get_object(Bucket=self._bucket, Key=s3_key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                raise ArtifactNotFoundError(f"Artifact not found at key '{key.value}'") from exc
            raise ArtifactStorageError(f"S3 get_object error for '{key.value}': {exc}") from exc

        body = obj["Body"]
        hasher = sha256()
        bytes_read = 0
        while chunk := body.read(self._chunk_size):
            bytes_read += len(chunk)
            hasher.update(chunk)
            destination.write(chunk)

        digest = hasher.hexdigest()
        stored_sha = obj.get("Metadata", {}).get("sha256")
        if stored_sha and stored_sha != digest:
            raise ArtifactChecksumMismatchError(
                f"Stored sha256 '{stored_sha}' does not match downloaded content digest '{digest}'"
            )

        return ArtifactMetadata(key=key, size_bytes=bytes_read, sha256=digest)

    async def delete(self, key: ArtifactKey) -> bool:
        """Delete an artifact from S3, returning whether it existed."""
        return await run_in_thread_with_context(self._delete, key)

    def _delete(self, key: ArtifactKey) -> bool:
        s3_key = self._get_s3_key(key)
        try:
            self._s3_client.head_object(Bucket=self._bucket, Key=s3_key)
            existed = True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise ArtifactStorageError(f"S3 head_object error: {exc}") from exc

        try:
            self._s3_client.delete_object(Bucket=self._bucket, Key=s3_key)
            return existed
        except ClientError as exc:
            raise ArtifactStorageError(f"S3 delete_object error: {exc}") from exc
