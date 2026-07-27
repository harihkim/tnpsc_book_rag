"""Integrity and functionality tests for S3 artifact storage."""

from hashlib import sha256
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from pydantic import AnyHttpUrl, SecretStr

from tnpsc_book_rag.artifact_storage import (
    ArtifactChecksumMismatchError,
    ArtifactConflictError,
    ArtifactKey,
    ArtifactStorageError,
    ArtifactTooLargeError,
    S3ArtifactStorage,
    create_artifact_storage,
)
from tnpsc_book_rag.config import Settings

_PAYLOAD = b"immutable textbook artifact for S3 testing\n" * 64
_SHA256 = sha256(_PAYLOAD).hexdigest()
_KEY = ArtifactKey("textbooks/science_std10.pdf")


@pytest.fixture
def mock_s3() -> Any:
    return MagicMock()


@pytest.fixture
def s3_storage(mock_s3: Any) -> Any:
    return S3ArtifactStorage(
        endpoint_url="https://s3.us-west-004.backblazeb2.com",
        bucket="tnpsc-test-bucket",
        access_key_id="test_key_id",
        secret_access_key="test_secret_key",
        s3_client=mock_s3,
    )


@pytest.mark.anyio
async def test_initialize_success(s3_storage: Any, mock_s3: Any) -> None:
    empty_dict: dict[str, Any] = {}
    mock_s3.head_bucket.return_value = empty_dict
    await s3_storage.initialize()
    mock_s3.head_bucket.assert_called_once_with(Bucket="tnpsc-test-bucket")


@pytest.mark.anyio
async def test_initialize_failure(s3_storage: Any, mock_s3: Any) -> None:
    mock_s3.head_bucket.side_effect = ClientError(
        {"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadBucket"
    )
    with pytest.raises(ArtifactStorageError, match="Failed to access S3 bucket"):
        await s3_storage.initialize()


@pytest.mark.anyio
async def test_is_ready(s3_storage: Any, mock_s3: Any) -> None:
    empty_dict: dict[str, Any] = {}
    mock_s3.head_bucket.return_value = empty_dict
    assert await s3_storage.is_ready() is True

    mock_s3.head_bucket.side_effect = Exception("Network error")
    assert await s3_storage.is_ready() is False


@pytest.mark.anyio
async def test_put_new_artifact(s3_storage: Any, mock_s3: Any) -> None:
    mock_s3.head_object.side_effect = [
        ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"),
        {
            "ContentLength": len(_PAYLOAD),
            "Metadata": {"sha256": _SHA256},
        },
    ]

    result = await s3_storage.put(_KEY, BytesIO(_PAYLOAD), expected_sha256=_SHA256)
    assert result.created is True
    assert result.artifact.sha256 == _SHA256
    assert result.artifact.size_bytes == len(_PAYLOAD)
    mock_s3.put_object.assert_called_once()


@pytest.mark.anyio
async def test_put_new_backblaze_artifact_when_missing_head_is_forbidden(
    s3_storage: Any, mock_s3: Any
) -> None:
    mock_s3.head_object.side_effect = ClientError(
        {"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadObject"
    )

    result = await s3_storage.put(_KEY, BytesIO(_PAYLOAD), expected_sha256=_SHA256)

    assert result.created is True
    assert result.artifact.sha256 == _SHA256
    assert result.artifact.size_bytes == len(_PAYLOAD)
    mock_s3.head_object.assert_called_once()
    mock_s3.put_object.assert_called_once()


@pytest.mark.anyio
async def test_put_forbidden_head_requires_expected_checksum(s3_storage: Any, mock_s3: Any) -> None:
    mock_s3.head_object.side_effect = ClientError(
        {"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadObject"
    )

    with pytest.raises(ArtifactStorageError):
        await s3_storage.put(_KEY, BytesIO(_PAYLOAD))

    mock_s3.put_object.assert_not_called()


@pytest.mark.anyio
async def test_put_forbidden_head_fails_closed_for_non_backblaze(
    mock_s3: Any,
) -> None:
    storage = S3ArtifactStorage(
        endpoint_url="https://s3.us-west-2.amazonaws.com",
        bucket="tnpsc-test-bucket",
        access_key_id="test_key_id",
        secret_access_key="test_secret_key",
        s3_client=mock_s3,
    )
    mock_s3.head_object.side_effect = ClientError(
        {"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadObject"
    )

    with pytest.raises(ArtifactStorageError):
        await storage.put(_KEY, BytesIO(_PAYLOAD), expected_sha256=_SHA256)

    mock_s3.put_object.assert_not_called()


@pytest.mark.anyio
async def test_put_existing_identical_artifact(s3_storage: Any, mock_s3: Any) -> None:
    mock_s3.head_object.return_value = {
        "ContentLength": len(_PAYLOAD),
        "Metadata": {"sha256": _SHA256},
    }

    result = await s3_storage.put(_KEY, BytesIO(_PAYLOAD), expected_sha256=_SHA256)
    assert result.created is False
    assert result.artifact.sha256 == _SHA256
    mock_s3.put_object.assert_not_called()


@pytest.mark.anyio
async def test_put_existing_conflict(s3_storage: Any, mock_s3: Any) -> None:
    mock_s3.head_object.return_value = {
        "ContentLength": 10,
        "Metadata": {"sha256": "different_hash"},
    }

    with pytest.raises(ArtifactConflictError):
        await s3_storage.put(_KEY, BytesIO(_PAYLOAD), expected_sha256=_SHA256)


@pytest.mark.anyio
async def test_put_checksum_mismatch(s3_storage: Any, mock_s3: Any) -> None:
    mock_s3.head_object.side_effect = ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
    )

    with pytest.raises(ArtifactChecksumMismatchError):
        await s3_storage.put(_KEY, BytesIO(_PAYLOAD), expected_sha256="0" * 64)


@pytest.mark.anyio
async def test_put_too_large(s3_storage: Any, mock_s3: Any) -> None:
    mock_s3.head_object.side_effect = ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
    )

    with pytest.raises(ArtifactTooLargeError):
        await s3_storage.put(_KEY, BytesIO(_PAYLOAD), max_bytes=10)


@pytest.mark.anyio
async def test_copy_to(s3_storage: Any, mock_s3: Any) -> None:
    mock_body = MagicMock()
    mock_body.read.side_effect = [_PAYLOAD, b""]
    mock_s3.get_object.return_value = {
        "Body": mock_body,
        "Metadata": {"sha256": _SHA256},
    }

    dest = BytesIO()
    meta = await s3_storage.copy_to(_KEY, dest)
    assert meta.sha256 == _SHA256
    assert dest.getvalue() == _PAYLOAD


@pytest.mark.anyio
async def test_delete(s3_storage: Any, mock_s3: Any) -> None:
    empty_dict: dict[str, Any] = {}
    mock_s3.head_object.return_value = empty_dict
    mock_s3.delete_object.return_value = empty_dict

    assert await s3_storage.delete(_KEY) is True
    mock_s3.delete_object.assert_called_once()


@pytest.mark.anyio
async def test_create_artifact_storage_factory_s3() -> None:
    settings = Settings(
        storage_backend="s3",
        s3_endpoint_url=AnyHttpUrl("https://s3.us-west-004.backblazeb2.com"),
        s3_bucket="my-b2-bucket",
        s3_access_key_id=SecretStr("key_id"),
        s3_secret_access_key=SecretStr("secret_key"),
    )

    storage = create_artifact_storage(settings)
    assert isinstance(storage, S3ArtifactStorage)


def test_s3_client_uses_adaptive_retries_and_a_bounded_connection_pool() -> None:
    with patch("tnpsc_book_rag.artifact_storage.s3.boto3.client") as client:
        S3ArtifactStorage(
            endpoint_url="https://s3.us-west-004.backblazeb2.com",
            bucket="tnpsc-test-bucket",
            access_key_id="test_key_id",
            secret_access_key="test_secret_key",
        )

    config = client.call_args.kwargs["config"]
    assert config.retries == {"mode": "adaptive", "total_max_attempts": 10}
    assert config.max_pool_connections == 32
