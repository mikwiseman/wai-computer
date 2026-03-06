"""Tests for the WebSocket audio streaming endpoint."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app

# ---------------------------------------------------------------------------
# Helper: build a mock async-context-manager that yields a mock session
# ---------------------------------------------------------------------------

def _make_mock_session(user=None, recording=None):
    """Return (session_factory, session_mock).

    ``session_factory`` is a callable returning an async-context-manager whose
    ``__aenter__`` yields ``session_mock``.

    ``session_mock.execute`` is set up so that:
      - The first call returns ``user`` via ``.scalar_one_or_none()``
      - The second call returns ``recording`` via ``.scalar_one_or_none()``
    """
    session = MagicMock()

    call_count = 0

    def _execute_side_effect(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = user
        elif call_count == 2:
            result.scalar_one_or_none.return_value = recording
        else:
            result.scalar_one_or_none.return_value = None
        return result

    # The Starlette TestClient runs async code in a thread, so we need
    # ``execute`` to be a *coroutine function* that the event-loop can await.
    async def _async_execute(*args, **kwargs):
        return _execute_side_effect(*args, **kwargs)

    session.execute = _async_execute

    @asynccontextmanager
    async def _session_ctx():
        yield session

    def session_factory():
        return _session_ctx()

    return session_factory, session


def _fake_user(user_id=None):
    """Return a lightweight mock User."""
    u = MagicMock()
    u.id = user_id or uuid.uuid4()
    return u


def _fake_recording(recording_id=None, user_id=None, language="en"):
    """Return a lightweight mock Recording."""
    r = MagicMock()
    r.id = recording_id or uuid.uuid4()
    r.user_id = user_id or uuid.uuid4()
    r.language = language
    return r


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWebSocketMissingParams:
    """Tests for parameter validation before any DB or service interaction."""

    def test_missing_token_closes_4001(self):
        """Connecting without a token yields an error and close code 4001."""
        client = TestClient(app)
        with client.websocket_connect("/api/ws/audio") as ws:
            data = ws.receive_json()
            assert data["type"] == "status"
            assert data["status"] == "error"
            assert "Missing token" in data["message"]
            # The server closes after sending the error; the next receive
            # should raise WebSocketDisconnect with code 4001.
            try:
                ws.receive_json()
            except WebSocketDisconnect as exc:
                assert exc.code == 4001

    def test_missing_recording_id_closes_4002(self):
        """Connecting with a token but no recording_id yields close 4002."""
        client = TestClient(app)
        with client.websocket_connect("/api/ws/audio?token=some-token") as ws:
            data = ws.receive_json()
            assert data["type"] == "status"
            assert data["status"] == "error"
            assert "Missing recording_id" in data["message"]
            try:
                ws.receive_json()
            except WebSocketDisconnect as exc:
                assert exc.code == 4002

    def test_invalid_recording_id_closes_4003(self):
        """Non-UUID recording_id yields close 4003."""
        client = TestClient(app)
        with client.websocket_connect(
            "/api/ws/audio?token=some-token&recording_id=not-a-uuid"
        ) as ws:
            data = ws.receive_json()
            assert data["type"] == "status"
            assert data["status"] == "error"
            assert "Invalid recording_id" in data["message"]
            try:
                ws.receive_json()
            except WebSocketDisconnect as exc:
                assert exc.code == 4003


class TestWebSocketAuth:
    """Tests requiring mocked DB/session layer."""

    @patch("app.api.websocket.async_session_maker")
    @patch("app.api.websocket.decode_access_token", return_value=None)
    def test_invalid_token_closes_4004(self, _mock_decode, mock_session_maker):
        """An invalid JWT (decode returns None) yields close 4004."""
        _fake_user()
        session_factory, _ = _make_mock_session(user=None)
        mock_session_maker.side_effect = lambda: session_factory()

        recording_id = str(uuid.uuid4())
        client = TestClient(app)
        with client.websocket_connect(
            f"/api/ws/audio?token=bad-token&recording_id={recording_id}"
        ) as ws:
            data = ws.receive_json()
            assert data["type"] == "status"
            assert data["status"] == "error"
            assert "Invalid token" in data["message"]
            try:
                ws.receive_json()
            except WebSocketDisconnect as exc:
                assert exc.code == 4004

    @patch("app.api.websocket.async_session_maker")
    @patch("app.api.websocket.decode_access_token")
    def test_recording_not_found_closes_4005(self, mock_decode, mock_session_maker):
        """Valid token but non-existent recording yields close 4005."""
        user_id = uuid.uuid4()
        mock_decode.return_value = str(user_id)

        user = _fake_user(user_id=user_id)
        session_factory, _ = _make_mock_session(user=user, recording=None)
        mock_session_maker.side_effect = lambda: session_factory()

        recording_id = str(uuid.uuid4())
        client = TestClient(app)
        with client.websocket_connect(
            f"/api/ws/audio?token=good-token&recording_id={recording_id}"
        ) as ws:
            data = ws.receive_json()
            assert data["type"] == "status"
            assert data["status"] == "error"
            assert "Recording not found" in data["message"]
            try:
                ws.receive_json()
            except WebSocketDisconnect as exc:
                assert exc.code == 4005


class TestWebSocketDeepgram:
    """Tests for Deepgram service interaction."""

    @patch("app.api.websocket.DeepgramStreamingClient")
    @patch("app.api.websocket.async_session_maker")
    @patch("app.api.websocket.decode_access_token")
    def test_deepgram_connect_failure_closes_4006(
        self, mock_decode, mock_session_maker, mock_deepgram_cls
    ):
        """If Deepgram connect() raises, the server sends error and closes 4006."""
        user_id = uuid.uuid4()
        recording_id = uuid.uuid4()
        mock_decode.return_value = str(user_id)

        user = _fake_user(user_id=user_id)
        recording = _fake_recording(recording_id=recording_id, user_id=user_id)
        session_factory, _ = _make_mock_session(user=user, recording=recording)
        mock_session_maker.side_effect = lambda: session_factory()

        # Deepgram instance whose connect() raises
        deepgram_instance = MagicMock()

        async def _failing_connect():
            raise RuntimeError("Deepgram unavailable")

        deepgram_instance.connect = _failing_connect
        mock_deepgram_cls.return_value = deepgram_instance

        client = TestClient(app)
        with client.websocket_connect(
            f"/api/ws/audio?token=tok&recording_id={recording_id}"
        ) as ws:
            data = ws.receive_json()
            assert data["type"] == "status"
            assert data["status"] == "error"
            assert "Transcription service error" in data["message"]
            try:
                ws.receive_json()
            except WebSocketDisconnect as exc:
                assert exc.code == 4006

    @patch("app.api.websocket.get_storage_client")
    @patch("app.api.websocket.generate_embedding")
    @patch("app.api.websocket.DeepgramStreamingClient")
    @patch("app.api.websocket.async_session_maker")
    @patch("app.api.websocket.decode_access_token")
    def test_successful_connection_receives_ready(
        self,
        mock_decode,
        mock_session_maker,
        mock_deepgram_cls,
        mock_gen_embedding,
        mock_storage,
    ):
        """Full happy-path: auth passes, Deepgram connects, client gets 'ready'."""
        user_id = uuid.uuid4()
        recording_id = uuid.uuid4()
        mock_decode.return_value = str(user_id)

        user = _fake_user(user_id=user_id)
        recording = _fake_recording(recording_id=recording_id, user_id=user_id)

        # We need a session factory that can be called multiple times (the
        # endpoint opens sessions in the finally-block too).  Each call should
        # return a fresh async-context-manager yielding a usable mock session.
        def _session_factory():
            call_count_inner = 0

            async def _exec(*_a, **_kw):
                nonlocal call_count_inner
                call_count_inner += 1
                res = MagicMock()
                if call_count_inner == 1:
                    res.scalar_one_or_none.return_value = user
                elif call_count_inner == 2:
                    res.scalar_one_or_none.return_value = recording
                else:
                    res.scalar_one_or_none.return_value = None
                    res.scalar.return_value = None
                return res

            sess = MagicMock()
            sess.execute = _exec
            sess.commit = AsyncMock()
            sess.add = MagicMock()

            @asynccontextmanager
            async def _ctx():
                yield sess

            return _ctx()

        mock_session_maker.side_effect = _session_factory

        # Deepgram that connects fine, and yields no transcripts
        deepgram_instance = MagicMock()

        async def _noop_connect():
            pass

        async def _noop_close():
            pass

        async def _noop_finish_stream():
            pass

        async def _empty_transcripts():
            return
            yield  # make it an async generator that yields nothing

        deepgram_instance.connect = _noop_connect
        deepgram_instance.finish_stream = _noop_finish_stream
        deepgram_instance.close = _noop_close
        deepgram_instance.receive_transcripts = _empty_transcripts
        mock_deepgram_cls.return_value = deepgram_instance

        client = TestClient(app)
        with client.websocket_connect(
            f"/api/ws/audio?token=tok&recording_id={recording_id}"
        ) as ws:
            data = ws.receive_json()
            assert data["type"] == "status"
            assert data["status"] == "ready"
            assert "Ready to receive audio" in data["message"]

            # Send end-of-stream so the server finishes cleanly
            ws.send_json({"type": "end"})

    @patch("app.api.websocket.get_storage_client")
    @patch("app.api.websocket.generate_embedding")
    @patch("app.api.websocket.DeepgramStreamingClient")
    @patch("app.api.websocket.async_session_maker")
    @patch("app.api.websocket.decode_access_token")
    def test_transcription_error_is_terminal(
        self,
        mock_decode,
        mock_session_maker,
        mock_deepgram_cls,
        _mock_gen_embedding,
        _mock_storage,
    ):
        """A transcription failure yields a terminal error status and never 'complete'."""
        user_id = uuid.uuid4()
        recording_id = uuid.uuid4()
        mock_decode.return_value = str(user_id)

        user = _fake_user(user_id=user_id)
        recording = _fake_recording(recording_id=recording_id, user_id=user_id)

        def _session_factory():
            call_count_inner = 0

            async def _exec(*_a, **_kw):
                nonlocal call_count_inner
                call_count_inner += 1
                res = MagicMock()
                if call_count_inner == 1:
                    res.scalar_one_or_none.return_value = user
                elif call_count_inner == 2:
                    res.scalar_one_or_none.return_value = recording
                else:
                    res.scalar_one_or_none.return_value = recording
                    res.scalar.return_value = None
                return res

            sess = MagicMock()
            sess.execute = _exec
            sess.commit = AsyncMock()
            sess.add = MagicMock()

            @asynccontextmanager
            async def _ctx():
                yield sess

            return _ctx()

        mock_session_maker.side_effect = _session_factory

        deepgram_instance = MagicMock()

        async def _noop_connect():
            pass

        async def _noop_close():
            pass

        async def _noop_finish_stream():
            pass

        async def _failing_transcripts():
            raise RuntimeError("Deepgram stream failed")
            yield

        deepgram_instance.connect = _noop_connect
        deepgram_instance.close = _noop_close
        deepgram_instance.finish_stream = _noop_finish_stream
        deepgram_instance.receive_transcripts = _failing_transcripts
        mock_deepgram_cls.return_value = deepgram_instance

        client = TestClient(app)
        with client.websocket_connect(
            f"/api/ws/audio?token=tok&recording_id={recording_id}"
        ) as ws:
            ready = ws.receive_json()
            assert ready["status"] == "ready"

            error = ws.receive_json()
            assert error["type"] == "status"
            assert error["status"] == "error"
            assert "Deepgram stream failed" in error["message"]

            try:
                ws.receive_json()
            except WebSocketDisconnect:
                pass

    @patch("app.api.websocket.get_storage_client")
    @patch("app.api.websocket.generate_embedding")
    @patch("app.api.websocket.DeepgramStreamingClient")
    @patch("app.api.websocket.async_session_maker")
    @patch("app.api.websocket.decode_access_token")
    def test_finalization_failure_is_terminal(
        self,
        mock_decode,
        mock_session_maker,
        mock_deepgram_cls,
        _mock_gen_embedding,
        _mock_storage,
    ):
        """Finalization errors must surface as terminal error instead of 'complete'."""
        user_id = uuid.uuid4()
        recording_id = uuid.uuid4()
        mock_decode.return_value = str(user_id)

        user = _fake_user(user_id=user_id)
        recording = _fake_recording(recording_id=recording_id, user_id=user_id)

        validation_session = MagicMock()
        validation_execute_count = 0

        async def _validation_execute(*_args, **_kwargs):
            nonlocal validation_execute_count
            validation_execute_count += 1
            result = MagicMock()
            if validation_execute_count == 1:
                result.scalar_one_or_none.return_value = user
            else:
                result.scalar_one_or_none.return_value = recording
            return result

        validation_session.execute = _validation_execute

        finalize_session = MagicMock()
        finalize_execute_count = 0

        async def _finalize_execute(*_args, **_kwargs):
            nonlocal finalize_execute_count
            finalize_execute_count += 1
            result = MagicMock()
            if finalize_execute_count == 1:
                result.scalar_one_or_none.return_value = recording
            else:
                result.scalar.return_value = None
            return result

        finalize_session.execute = _finalize_execute
        finalize_session.commit = AsyncMock(side_effect=RuntimeError("Final DB commit failed"))
        finalize_session.add = MagicMock()

        @asynccontextmanager
        async def _validation_ctx():
            yield validation_session

        @asynccontextmanager
        async def _finalize_ctx():
            yield finalize_session

        session_contexts = iter([_validation_ctx(), _finalize_ctx()])
        mock_session_maker.side_effect = lambda: next(session_contexts)

        deepgram_instance = MagicMock()

        async def _noop_connect():
            pass

        async def _noop_close():
            pass

        stream_finished = asyncio.Event()

        async def _noop_finish_stream():
            stream_finished.set()

        async def _wait_for_finish_then_exit():
            await stream_finished.wait()
            return
            yield

        deepgram_instance.connect = _noop_connect
        deepgram_instance.close = _noop_close
        deepgram_instance.finish_stream = _noop_finish_stream
        deepgram_instance.receive_transcripts = _wait_for_finish_then_exit
        deepgram_instance.send_audio = AsyncMock()
        mock_deepgram_cls.return_value = deepgram_instance

        client = TestClient(app)
        with client.websocket_connect(
            f"/api/ws/audio?token=tok&recording_id={recording_id}"
        ) as ws:
            ready = ws.receive_json()
            assert ready["status"] == "ready"

            ws.send_json({"type": "end"})

            terminal = ws.receive_json()
            assert terminal["type"] == "status"
            assert terminal["status"] == "error"
            assert terminal["message"] == "Final DB commit failed"


class TestWebSocketQueryParamEdgeCases:
    """Additional edge-case tests for query-param handling."""

    def test_empty_token_closes_4001(self):
        """An explicitly empty token string is still treated as missing."""
        client = TestClient(app)
        with client.websocket_connect(
            "/api/ws/audio?token=&recording_id=" + str(uuid.uuid4())
        ) as ws:
            data = ws.receive_json()
            assert data["status"] == "error"
            assert "Missing token" in data["message"]
            try:
                ws.receive_json()
            except WebSocketDisconnect as exc:
                assert exc.code == 4001

    def test_empty_recording_id_closes_4002(self):
        """An explicitly empty recording_id string is treated as missing."""
        client = TestClient(app)
        with client.websocket_connect(
            "/api/ws/audio?token=abc&recording_id="
        ) as ws:
            data = ws.receive_json()
            assert data["status"] == "error"
            assert "Missing recording_id" in data["message"]
            try:
                ws.receive_json()
            except WebSocketDisconnect as exc:
                assert exc.code == 4002

    def test_uuid_like_but_invalid_closes_4003(self):
        """A string that looks like a UUID but has wrong characters closes 4003."""
        client = TestClient(app)
        with client.websocket_connect(
            "/api/ws/audio?token=abc&recording_id=00000000-0000-0000-0000-00000000gggg"
        ) as ws:
            data = ws.receive_json()
            assert data["status"] == "error"
            assert "Invalid recording_id" in data["message"]
            try:
                ws.receive_json()
            except WebSocketDisconnect as exc:
                assert exc.code == 4003
