"""S3 storage for audio files (Hetzner Object Storage)."""

import uuid
from datetime import datetime, timezone

import boto3
from botocore.config import Config

from app.config import get_settings

settings = get_settings()


class StorageClient:
    """Client for S3 audio file storage."""

    def __init__(self):
        self._client = None

    def _get_client(self):
        """Get or create the S3 client."""
        if self._client is None:
            if not settings.s3_endpoint:
                raise ValueError("S3_ENDPOINT not configured")

            self._client = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint,
                aws_access_key_id=settings.s3_access_key,
                aws_secret_access_key=settings.s3_secret_key,
                region_name=settings.s3_region,
                config=Config(signature_version="s3v4"),
            )
        return self._client

    def _generate_key(self, user_id: uuid.UUID, recording_id: uuid.UUID, ext: str = "opus") -> str:
        """Generate a unique S3 key for an audio file."""
        date_prefix = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        return f"{user_id}/{date_prefix}/{recording_id}.{ext}"

    async def upload_audio(
        self,
        audio_data: bytes,
        user_id: uuid.UUID,
        recording_id: uuid.UUID,
        content_type: str = "audio/pcm",
    ) -> str:
        """
        Upload audio data to S3.

        Args:
            audio_data: Raw audio bytes
            user_id: User ID
            recording_id: Recording ID
            content_type: MIME type of the audio

        Returns:
            S3 key of the uploaded file
        """
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._upload_sync,
            audio_data,
            user_id,
            recording_id,
            content_type,
        )

    def _upload_sync(
        self,
        audio_data: bytes,
        user_id: uuid.UUID,
        recording_id: uuid.UUID,
        content_type: str,
    ) -> str:
        """Synchronous upload."""
        client = self._get_client()
        ext_map = {
            "audio/opus": "opus", "audio/wav": "wav", "audio/mpeg": "mp3",
            "audio/mp4": "m4a", "audio/ogg": "ogg", "audio/webm": "webm",
            "audio/flac": "flac", "audio/pcm": "pcm", "audio/x-wav": "wav",
            "audio/x-m4a": "m4a",
        }
        ext = ext_map.get(content_type, "bin")
        key = self._generate_key(user_id, recording_id, ext)

        client.put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=audio_data,
            ContentType=content_type,
        )

        # Return the S3 key — clients should use presigned URLs for access
        return key

    async def get_presigned_url(
        self,
        s3_key: str,
        expires_in: int = 3600,
    ) -> str:
        """
        Get a presigned URL for downloading an audio file.

        Args:
            s3_key: The S3 key (as returned by upload_audio)
            expires_in: URL expiration time in seconds

        Returns:
            Presigned URL
        """
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._get_presigned_url_sync,
            s3_key,
            expires_in,
        )

    def _get_presigned_url_sync(
        self,
        s3_key: str,
        expires_in: int,
    ) -> str:
        """Synchronous presigned URL generation."""
        client = self._get_client()

        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket, "Key": s3_key},
            ExpiresIn=expires_in,
        )

    async def delete_audio(
        self,
        s3_key: str,
    ) -> None:
        """Delete an audio file from storage."""
        import asyncio

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            self._delete_sync,
            s3_key,
        )

    def _delete_sync(
        self,
        s3_key: str,
    ) -> None:
        """Synchronous delete."""
        client = self._get_client()
        client.delete_object(Bucket=settings.s3_bucket, Key=s3_key)


# Global instance
_storage_client: StorageClient | None = None


def get_storage_client() -> StorageClient:
    """Get or create the global storage client instance."""
    global _storage_client
    if _storage_client is None:
        _storage_client = StorageClient()
    return _storage_client
