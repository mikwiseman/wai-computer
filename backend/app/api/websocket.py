"""WebSocket endpoint for real-time audio streaming and transcription."""

import asyncio
import base64
import json
import logging
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deepgram import DeepgramStreamingClient
from app.core.embeddings import generate_embedding
from app.core.security import decode_access_token
from app.core.storage import get_storage_client
from app.db.session import async_session_maker
from app.models.recording import Recording, Segment
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


async def get_user_from_token(token: str, db: AsyncSession) -> User | None:
    """Validate token and get user."""
    user_id = decode_access_token(token)
    if user_id is None:
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


@router.websocket("/ws/audio")
async def audio_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for real-time audio streaming and transcription.

    Protocol:
    - Client sends: {"type": "audio", "data": "<base64 opus>", "timestamp": 123}
    - Server sends: {"type": "transcript", "text": "...",
      "speaker": "...", "is_final": true, "start_ms": 0, "end_ms": 1000}
    - Server sends: {"type": "status", "status": "ready|processing|error", "message": "..."}

    Query params:
    - token: JWT auth token
    - recording_id: UUID of the recording to add segments to
    """
    await websocket.accept()

    # Get auth token and recording_id from query params
    token = websocket.query_params.get("token")
    recording_id_str = websocket.query_params.get("recording_id")

    if not token:
        await websocket.send_json({"type": "status", "status": "error", "message": "Missing token"})
        await websocket.close(code=4001)
        return

    if not recording_id_str:
        await websocket.send_json(
            {"type": "status", "status": "error", "message": "Missing recording_id"}
        )
        await websocket.close(code=4002)
        return

    try:
        recording_id = UUID(recording_id_str)
    except ValueError:
        await websocket.send_json(
            {"type": "status", "status": "error", "message": "Invalid recording_id"}
        )
        await websocket.close(code=4003)
        return

    # Validate user and recording
    async with async_session_maker() as db:
        user = await get_user_from_token(token, db)
        if user is None:
            await websocket.send_json(
                {"type": "status", "status": "error", "message": "Invalid token"}
            )
            await websocket.close(code=4004)
            return

        result = await db.execute(
            select(Recording).where(Recording.id == recording_id, Recording.user_id == user.id)
        )
        recording = result.scalar_one_or_none()

        if recording is None:
            await websocket.send_json(
                {"type": "status", "status": "error", "message": "Recording not found"}
            )
            await websocket.close(code=4005)
            return

        user_id = user.id
        language = recording.language or "en"

    # Initialize Deepgram client
    deepgram = DeepgramStreamingClient(language=language)

    try:
        await deepgram.connect()
    except Exception as e:
        await websocket.send_json(
            {"type": "status", "status": "error", "message": f"Transcription service error: {e}"}
        )
        await websocket.close(code=5001)
        return

    await websocket.send_json(
        {"type": "status", "status": "ready", "message": "Ready to receive audio"}
    )

    # Track segments to save with thread-safe lock
    pending_segments: list[dict] = []
    segments_lock = asyncio.Lock()
    save_task: asyncio.Task | None = None

    # Accumulate raw audio chunks for S3 upload
    audio_chunks: list[bytes] = []

    async def save_segments():
        """Periodically save segments to database."""
        while True:
            await asyncio.sleep(5)  # Save every 5 seconds
            async with segments_lock:
                if not pending_segments:
                    continue
                segments_to_save = pending_segments.copy()
                pending_segments.clear()

            try:
                async with async_session_maker() as db:
                    for seg_data in segments_to_save:
                        # Generate embedding for final segments
                        embedding = None
                        if seg_data.get("is_final"):
                            try:
                                embedding = await generate_embedding(seg_data["text"])
                            except Exception as e:
                                logger.warning(f"Failed to generate embedding: {e}")

                        segment = Segment(
                            recording_id=recording_id,
                            speaker=seg_data.get("speaker"),
                            content=seg_data["text"],
                            start_ms=seg_data.get("start_ms"),
                            end_ms=seg_data.get("end_ms"),
                            confidence=seg_data.get("confidence"),
                            embedding=embedding,
                        )
                        db.add(segment)

                    await db.commit()
            except Exception as e:
                logger.error(f"Failed to save segments: {e}")

    async def receive_audio():
        """Receive audio from client and send to Deepgram."""
        try:
            while True:
                data = await websocket.receive_text()
                try:
                    message = json.loads(data)
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON received: {e}")
                    continue

                if message.get("type") == "audio":
                    audio_b64 = message.get("data")
                    if audio_b64:
                        try:
                            audio_bytes = base64.b64decode(audio_b64)
                            audio_chunks.append(audio_bytes)
                            await deepgram.send_audio(audio_bytes)
                        except Exception as e:
                            logger.warning(f"Failed to decode/send audio: {e}")

                elif message.get("type") == "end":
                    # Client signaling end of stream
                    break

        except WebSocketDisconnect:
            logger.info("WebSocket disconnected")
        except Exception as e:
            logger.error(f"Error in receive_audio: {e}")
            try:
                await websocket.send_json(
                    {"type": "status", "status": "error", "message": f"Error: {e}"}
                )
            except Exception:
                pass

    async def send_transcripts():
        """Receive transcripts from Deepgram and send to client."""
        try:
            async for result in deepgram.receive_transcripts():
                transcript_msg = {
                    "type": "transcript",
                    "text": result.text,
                    "speaker": result.speaker,
                    "is_final": result.is_final,
                    "start_ms": result.start_ms,
                    "end_ms": result.end_ms,
                }
                await websocket.send_json(transcript_msg)

                # Store final transcripts for saving (thread-safe)
                if result.is_final:
                    async with segments_lock:
                        pending_segments.append(
                            {
                                "text": result.text,
                                "speaker": result.speaker,
                                "start_ms": result.start_ms,
                                "end_ms": result.end_ms,
                                "confidence": result.confidence,
                                "is_final": True,
                            }
                        )

        except Exception as e:
            logger.error(f"Transcription error: {e}")
            try:
                await websocket.send_json(
                    {"type": "status", "status": "error", "message": f"Transcription error: {e}"}
                )
            except Exception:
                pass

    # Start background tasks
    save_task = asyncio.create_task(save_segments())

    try:
        # Run receive and send concurrently
        await asyncio.gather(
            receive_audio(),
            send_transcripts(),
        )
    finally:
        # Cleanup - cancel save task gracefully
        if save_task is not None:
            save_task.cancel()
            try:
                await save_task
            except asyncio.CancelledError:
                pass

        await deepgram.close()

        # Final save of any remaining segments
        async with segments_lock:
            segments_to_save = pending_segments.copy()
            pending_segments.clear()

        if segments_to_save:
            try:
                async with async_session_maker() as db:
                    for seg_data in segments_to_save:
                        embedding = None
                        if seg_data.get("is_final"):
                            try:
                                embedding = await generate_embedding(seg_data["text"])
                            except Exception as e:
                                logger.warning(f"Failed to generate final embedding: {e}")

                        segment = Segment(
                            recording_id=recording_id,
                            speaker=seg_data.get("speaker"),
                            content=seg_data["text"],
                            start_ms=seg_data.get("start_ms"),
                            end_ms=seg_data.get("end_ms"),
                            confidence=seg_data.get("confidence"),
                            embedding=embedding,
                        )
                        db.add(segment)

                    await db.commit()
            except Exception as e:
                logger.error(f"Failed to save final segments: {e}")

        # Upload accumulated audio to S3 and calculate duration
        try:
            async with async_session_maker() as db:
                rec_result = await db.execute(
                    select(Recording).where(Recording.id == recording_id)
                )
                rec = rec_result.scalar_one_or_none()

                if rec is not None:
                    # Upload audio to S3
                    if audio_chunks:
                        try:
                            storage = get_storage_client()
                            audio_data = b"".join(audio_chunks)
                            s3_key = await storage.upload_audio(audio_data, user_id, recording_id)
                            rec.audio_url = s3_key
                        except Exception as e:
                            logger.error(f"Failed to upload audio to S3: {e}")

                    # Calculate duration from max segment end_ms
                    duration_result = await db.execute(
                        select(func.max(Segment.end_ms)).where(
                            Segment.recording_id == recording_id
                        )
                    )
                    max_end_ms = duration_result.scalar()
                    if max_end_ms is not None:
                        rec.duration_seconds = max_end_ms // 1000

                    await db.commit()
        except Exception as e:
            logger.error(f"Failed to finalize recording: {e}")

        try:
            await websocket.send_json(
                {"type": "status", "status": "complete", "message": "Transcription complete"}
            )
        except Exception:
            pass  # WebSocket may already be closed
