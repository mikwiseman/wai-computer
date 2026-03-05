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
    logger.info(f"Connecting to Deepgram for recording {recording_id}")

    try:
        await deepgram.connect()
        logger.info("Deepgram connected successfully")
    except Exception as e:
        logger.error(f"Deepgram connection failed: {e}")
        await websocket.send_json(
            {"type": "status", "status": "error", "message": f"Transcription service error: {e}"}
        )
        await websocket.close(code=4006)
        return

    await websocket.send_json(
        {"type": "status", "status": "ready", "message": "Ready to receive audio"}
    )
    logger.info("Sent 'ready' status to client, starting audio pipeline")

    segment_queue: asyncio.Queue[dict | None] = asyncio.Queue()
    audio_chunks: list[bytes] = []
    audio_msg_count = 0
    client_socket_open = True
    stream_finished = False
    save_task: asyncio.Task | None = None
    receive_task: asyncio.Task | None = None
    send_task: asyncio.Task | None = None
    saver_stopped = False
    terminal_error: Exception | None = None
    terminal_status_sent = False

    async def finish_deepgram_stream() -> None:
        nonlocal stream_finished
        if stream_finished:
            return

        stream_finished = True
        try:
            await deepgram.finish_stream()
        except Exception as exc:
            logger.warning(f"Failed to finish Deepgram stream cleanly: {exc}")

    async def persist_segment_batch(segments_to_save: list[dict]) -> None:
        for attempt in range(1, 4):
            try:
                async with async_session_maker() as db:
                    for seg_data in segments_to_save:
                        embedding = None
                        if seg_data.get("is_final"):
                            try:
                                embedding = await generate_embedding(seg_data["text"])
                            except Exception as exc:
                                logger.warning(f"Failed to generate embedding: {exc}")

                        db.add(
                            Segment(
                                recording_id=recording_id,
                                speaker=seg_data.get("speaker"),
                                content=seg_data["text"],
                                start_ms=seg_data.get("start_ms"),
                                end_ms=seg_data.get("end_ms"),
                                confidence=seg_data.get("confidence"),
                                embedding=embedding,
                            )
                        )

                    await db.commit()
                return
            except Exception as exc:
                logger.error(
                    "Failed to save transcript batch for recording %s on attempt %s: %s",
                    recording_id,
                    attempt,
                    exc,
                )
                if attempt == 3:
                    raise
                await asyncio.sleep(attempt)

    async def save_segments() -> None:
        """Persist final transcript segments without dropping them on cancellation."""
        while True:
            item = await segment_queue.get()
            if item is None:
                return

            segments_to_save = [item]
            reached_sentinel = False
            while len(segments_to_save) < 20:
                try:
                    queued_item = segment_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                if queued_item is None:
                    reached_sentinel = True
                    break

                segments_to_save.append(queued_item)

            await persist_segment_batch(segments_to_save)
            if reached_sentinel:
                return

    async def stop_segment_saver() -> None:
        nonlocal saver_stopped
        if saver_stopped:
            return

        saver_stopped = True
        await segment_queue.put(None)

    async def cancel_task(task: asyncio.Task | None, timeout: float = 1.0) -> None:
        if task is None or task.done():
            return

        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    async def receive_audio() -> None:
        """Receive audio from client and send it to Deepgram."""
        nonlocal audio_msg_count, client_socket_open
        logger.info("receive_audio: started, waiting for messages")
        try:
            while True:
                data = await websocket.receive_text()
                try:
                    message = json.loads(data)
                except json.JSONDecodeError as exc:
                    logger.warning(f"Invalid JSON received: {exc}")
                    continue

                msg_type = message.get("type")
                if msg_type == "audio":
                    audio_b64 = message.get("data")
                    if not audio_b64:
                        logger.warning("receive_audio: audio message with empty data field")
                        continue

                    audio_bytes = base64.b64decode(audio_b64)
                    audio_chunks.append(audio_bytes)
                    audio_msg_count += 1
                    if audio_msg_count <= 3 or audio_msg_count % 50 == 0:
                        logger.info(
                            "receive_audio: msg #%s, %s bytes",
                            audio_msg_count,
                            len(audio_bytes),
                        )
                    await deepgram.send_audio(audio_bytes)
                    continue

                if msg_type == "end":
                    logger.info(
                        "receive_audio: end signal received after %s audio messages",
                        audio_msg_count,
                    )
                    await finish_deepgram_stream()
                    return

                logger.warning(f"receive_audio: unknown message type: {msg_type}")

        except WebSocketDisconnect:
            client_socket_open = False
            logger.info("WebSocket disconnected after %s audio messages", audio_msg_count)
            await finish_deepgram_stream()
        except Exception:
            await finish_deepgram_stream()
            raise

    async def send_transcripts() -> None:
        """Receive Deepgram transcripts and persist them even if the client disconnects."""
        nonlocal client_socket_open
        logger.info("send_transcripts: started, waiting for Deepgram results")
        async for result in deepgram.receive_transcripts():
            if result.is_final:
                await segment_queue.put(
                    {
                        "text": result.text,
                        "speaker": result.speaker,
                        "start_ms": result.start_ms,
                        "end_ms": result.end_ms,
                        "confidence": result.confidence,
                        "is_final": True,
                    }
                )

            if not client_socket_open:
                continue

            transcript_msg = {
                "type": "transcript",
                "text": result.text,
                "speaker": result.speaker,
                "is_final": result.is_final,
                "start_ms": result.start_ms,
                "end_ms": result.end_ms,
            }

            try:
                await websocket.send_json(transcript_msg)
            except Exception as exc:
                client_socket_open = False
                logger.warning(f"Failed to send transcript to client: {exc}")

    save_task = asyncio.create_task(save_segments())
    receive_task = asyncio.create_task(receive_audio())
    send_task = asyncio.create_task(send_transcripts())

    try:
        done, pending = await asyncio.wait(
            {receive_task, send_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if receive_task in done:
            try:
                await receive_task
            except Exception as exc:
                terminal_error = exc

            if send_task in pending:
                try:
                    await asyncio.wait_for(send_task, timeout=15.0)
                except asyncio.TimeoutError as exc:
                    logger.error("Timed out waiting for Deepgram final transcripts")
                    terminal_error = terminal_error or RuntimeError(
                        "Timed out waiting for final transcripts"
                    )
                    send_task.cancel()
                    await asyncio.gather(send_task, return_exceptions=True)
                except Exception as exc:
                    terminal_error = terminal_error or exc
            elif send_task in done:
                try:
                    await send_task
                except Exception as exc:
                    terminal_error = terminal_error or exc
        else:
            try:
                await send_task
                terminal_error = RuntimeError(
                    "Transcription stream closed before audio input finished"
                )
            except Exception as exc:
                terminal_error = exc

            await finish_deepgram_stream()
            if terminal_error is not None:
                try:
                    await websocket.send_json(
                        {"type": "status", "status": "error", "message": str(terminal_error)}
                    )
                    terminal_status_sent = True
                except Exception:
                    pass
            try:
                await websocket.close(code=1011)
            except Exception:
                pass
            await cancel_task(receive_task)
    except Exception as exc:
        terminal_error = terminal_error or exc
    finally:
        await stop_segment_saver()
        if save_task is not None:
            try:
                await save_task
            except Exception as exc:
                terminal_error = terminal_error or exc

        await cancel_task(receive_task)
        await cancel_task(send_task)

        await deepgram.close()

        # Upload accumulated audio and finalize metadata before reporting completion.
        try:
            async with async_session_maker() as db:
                rec_result = await db.execute(select(Recording).where(Recording.id == recording_id))
                rec = rec_result.scalar_one_or_none()

                if rec is not None:
                    if audio_chunks:
                        try:
                            storage = get_storage_client()
                            audio_data = b"".join(audio_chunks)
                            s3_key = await storage.upload_audio(audio_data, user_id, recording_id)
                            rec.audio_url = s3_key
                        except Exception as exc:
                            logger.error(f"Failed to upload audio to S3: {exc}")

                    duration_result = await db.execute(
                        select(func.max(Segment.end_ms)).where(Segment.recording_id == recording_id)
                    )
                    max_end_ms = duration_result.scalar()
                    if max_end_ms is not None:
                        rec.duration_seconds = max_end_ms // 1000

                    await db.commit()
        except Exception as exc:
            logger.error(f"Failed to finalize recording: {exc}")
            terminal_error = terminal_error or exc

        terminal_status = "complete"
        terminal_message = "Transcription complete"
        if terminal_error is not None:
            terminal_status = "error"
            terminal_message = str(terminal_error)

        if not terminal_status_sent:
            try:
                await websocket.send_json(
                    {"type": "status", "status": terminal_status, "message": terminal_message}
                )
                logger.info("Sent terminal status '%s' to client", terminal_status)
            except Exception:
                pass
