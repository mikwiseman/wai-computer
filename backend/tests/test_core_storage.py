"""Tests for app/core/storage.py - S3 storage client."""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

import app.core.storage as storage_module
from app.core.storage import StorageClient, get_storage_client


@pytest.fixture(autouse=True)
def reset_storage_singleton():
    """Reset the global _storage_client between tests."""
    storage_module._storage_client = None
    yield
    storage_module._storage_client = None


@pytest.fixture
def mock_boto3_client():
    """Create a mock boto3 S3 client."""
    mock_client = MagicMock()
    mock_client.put_object = MagicMock()
    mock_client.delete_object = MagicMock()
    mock_client.generate_presigned_url = MagicMock(return_value="https://presigned.example.com/file")
    return mock_client


@pytest.fixture
def storage_with_mock_client(mock_boto3_client):
    """Create a StorageClient with a pre-injected mock S3 client."""
    client = StorageClient()
    client._client = mock_boto3_client
    return client


@pytest.fixture
def user_id():
    return uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


@pytest.fixture
def recording_id():
    return uuid.UUID("11111111-2222-3333-4444-555555555555")


class TestGenerateKey:
    def test_generates_correct_path_format(self, user_id, recording_id):
        """_generate_key() produces {user_id}/{YYYY/MM/DD}/{recording_id}.opus format."""
        client = StorageClient()
        key = client._generate_key(user_id, recording_id, ext="opus")

        today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        expected = f"{user_id}/{today}/{recording_id}.opus"
        assert key == expected

    def test_generates_key_with_custom_extension(self, user_id, recording_id):
        """_generate_key() uses the specified extension."""
        client = StorageClient()
        key = client._generate_key(user_id, recording_id, ext="wav")

        today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        expected = f"{user_id}/{today}/{recording_id}.wav"
        assert key == expected


class TestGetClient:
    def test_raises_when_s3_endpoint_empty(self):
        """_get_client() raises ValueError when S3_ENDPOINT is not configured."""
        with patch.object(storage_module.settings, "s3_endpoint", ""):
            client = StorageClient()
            with pytest.raises(ValueError, match="S3_ENDPOINT not configured"):
                client._get_client()

    def test_caches_client_instance(self):
        """_get_client() returns the same client on subsequent calls."""
        with patch.object(storage_module.settings, "s3_endpoint", "https://s3.example.com"), \
             patch.object(storage_module.settings, "s3_access_key", "access"), \
             patch.object(storage_module.settings, "s3_secret_key", "secret"), \
             patch.object(storage_module.settings, "s3_region", "us-east-1"), \
             patch("app.core.storage.boto3") as mock_boto3:
            mock_boto3.client.return_value = MagicMock()
            client = StorageClient()

            first = client._get_client()
            second = client._get_client()

            assert first is second
            assert mock_boto3.client.call_count == 1


class TestUploadSync:
    def test_calls_put_object_with_correct_params(
        self, storage_with_mock_client, mock_boto3_client, user_id, recording_id
    ):
        """_upload_sync() calls put_object with correct Bucket, Key, Body, ContentType."""
        audio_data = b"fake-audio-data"
        content_type = "audio/opus"

        with patch.object(storage_module.settings, "s3_bucket", "test-bucket"):
            key = storage_with_mock_client._upload_sync(
                audio_data, user_id, recording_id, content_type
            )

        mock_boto3_client.put_object.assert_called_once()
        call_kwargs = mock_boto3_client.put_object.call_args
        assert call_kwargs.kwargs["Bucket"] == "test-bucket"
        assert call_kwargs.kwargs["Body"] == audio_data
        assert call_kwargs.kwargs["ContentType"] == content_type
        assert key.endswith(".opus")

    def test_uses_wav_extension_for_non_opus_content(
        self, storage_with_mock_client, mock_boto3_client, user_id, recording_id
    ):
        """_upload_sync() uses 'wav' extension for non-opus content types."""
        with patch.object(storage_module.settings, "s3_bucket", "test-bucket"):
            key = storage_with_mock_client._upload_sync(
                b"data", user_id, recording_id, "audio/wav"
            )

        assert key.endswith(".wav")


class TestPresignedUrlSync:
    def test_calls_generate_presigned_url_correctly(
        self, storage_with_mock_client, mock_boto3_client
    ):
        """_get_presigned_url_sync() calls generate_presigned_url with correct params."""
        s3_key = "some-user/2026/03/02/some-recording.opus"
        with patch.object(storage_module.settings, "s3_bucket", "test-bucket"):
            url = storage_with_mock_client._get_presigned_url_sync(s3_key, 7200)

        mock_boto3_client.generate_presigned_url.assert_called_once()
        call_args = mock_boto3_client.generate_presigned_url.call_args
        assert call_args.args[0] == "get_object"
        assert call_args.kwargs["Params"]["Bucket"] == "test-bucket"
        assert call_args.kwargs["Params"]["Key"] == s3_key
        assert call_args.kwargs["ExpiresIn"] == 7200
        assert url == "https://presigned.example.com/file"


class TestDeleteSync:
    def test_calls_delete_object_correctly(
        self, storage_with_mock_client, mock_boto3_client
    ):
        """_delete_sync() calls delete_object with correct Bucket and Key."""
        s3_key = "some-user/2026/03/02/some-recording.opus"
        with patch.object(storage_module.settings, "s3_bucket", "test-bucket"):
            storage_with_mock_client._delete_sync(s3_key)

        mock_boto3_client.delete_object.assert_called_once()
        call_kwargs = mock_boto3_client.delete_object.call_args
        assert call_kwargs.kwargs["Bucket"] == "test-bucket"
        assert call_kwargs.kwargs["Key"] == s3_key


class TestAsyncWrappers:
    async def test_upload_audio_delegates_to_upload_sync(
        self, storage_with_mock_client, user_id, recording_id
    ):
        """upload_audio() async wrapper delegates to _upload_sync."""
        with patch.object(storage_module.settings, "s3_bucket", "test-bucket"):
            key = await storage_with_mock_client.upload_audio(
                b"audio-data", user_id, recording_id, "audio/opus"
            )

        assert key.endswith(".opus")
        assert str(user_id) in key

    async def test_get_presigned_url_delegates(
        self, storage_with_mock_client
    ):
        """get_presigned_url() async wrapper delegates to _get_presigned_url_sync."""
        s3_key = "some-user/2026/03/02/some-recording.opus"
        with patch.object(storage_module.settings, "s3_bucket", "test-bucket"):
            url = await storage_with_mock_client.get_presigned_url(s3_key, 3600)

        assert url == "https://presigned.example.com/file"

    async def test_delete_audio_delegates(
        self, storage_with_mock_client, mock_boto3_client
    ):
        """delete_audio() async wrapper delegates to _delete_sync."""
        s3_key = "some-user/2026/03/02/some-recording.opus"
        with patch.object(storage_module.settings, "s3_bucket", "test-bucket"):
            await storage_with_mock_client.delete_audio(s3_key)

        mock_boto3_client.delete_object.assert_called_once()


class TestGetStorageClient:
    def test_returns_singleton_instance(self):
        """get_storage_client() returns the same instance on repeated calls."""
        first = get_storage_client()
        second = get_storage_client()
        assert first is second
        assert isinstance(first, StorageClient)
