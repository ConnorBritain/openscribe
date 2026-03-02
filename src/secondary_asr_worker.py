"""Long-lived secondary ASR worker process.

The worker keeps a dedicated TranscriptionHandler alive in a separate process so
secondary retranscription does not evict or contend with the primary runtime.
"""

from __future__ import annotations

import multiprocessing as mp
import queue
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional


def _secondary_worker_entry(request_queue, response_queue) -> None:
    """Process entrypoint for secondary ASR work."""
    from src.transcription_handler import TranscriptionHandler

    handler: Optional[TranscriptionHandler] = None
    active_model_id: Optional[str] = None

    while True:
        try:
            request = request_queue.get()
        except (EOFError, OSError):
            break

        if not isinstance(request, dict):
            continue

        request_id = str(request.get("id") or uuid.uuid4().hex)
        request_type = str(request.get("type") or "")

        if request_type == "shutdown":
            try:
                response_queue.put(
                    {
                        "id": request_id,
                        "type": "shutdown",
                        "success": True,
                    }
                )
            except Exception:
                pass
            break

        if request_type not in {"retranscribe", "warmup"}:
            response_queue.put(
                {
                    "id": request_id,
                    "type": request_type,
                    "success": False,
                    "error": f"Unsupported secondary worker request type: {request_type}",
                }
            )
            continue

        model_id = str(request.get("model_id") or "")
        if not model_id:
            response_queue.put(
                {
                    "id": request_id,
                    "type": request_type,
                    "success": False,
                    "error": "Missing model_id for secondary ASR request.",
                }
            )
            continue

        audio_path = str(request.get("audio_path") or "")
        if request_type == "retranscribe" and not audio_path:
            response_queue.put(
                {
                    "id": request_id,
                    "type": request_type,
                    "success": False,
                    "error": "Missing audio_path for secondary retranscribe request.",
                }
            )
            continue

        start_time = time.time()
        try:
            if handler is None:
                handler = TranscriptionHandler(
                    on_transcription_complete_callback=None,
                    on_status_update_callback=None,
                    selected_asr_model=model_id,
                )
                active_model_id = model_id
            elif active_model_id != model_id:
                handler.update_selected_asr_model(model_id)
                active_model_id = model_id

            if request_type == "warmup":
                response_payload = {
                    "id": request_id,
                    "type": "warmup",
                    "success": True,
                    "modelId": model_id,
                    "duration": round(time.time() - start_time, 2),
                }
            else:
                transcript = handler.retranscribe_audio_file(audio_path, model_id)
                response_payload = {
                    "id": request_id,
                    "type": "retranscribe",
                    "success": True,
                    "modelId": model_id,
                    "transcript": transcript,
                    "duration": round(time.time() - start_time, 2),
                }
        except Exception as error:
            response_payload = {
                "id": request_id,
                "type": request_type,
                "success": False,
                "modelId": model_id,
                "error": str(error),
                "duration": round(time.time() - start_time, 2),
            }

        try:
            response_queue.put(response_payload)
        except Exception:
            break

    if handler is not None:
        try:
            handler.shutdown()
        except Exception:
            pass


class SecondaryAsrWorkerClient:
    """Client for requesting secondary ASR work from a long-lived process."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 240.0,
        queue_size: int = 8,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ):
        self._timeout_seconds = max(1.0, float(timeout_seconds))
        self._queue_size = max(1, int(queue_size))
        self._log_callback = log_callback
        self._lock = threading.RLock()
        self._request_queue = None
        self._response_queue = None
        self._process: Optional[mp.Process] = None
        self._response_thread: Optional[threading.Thread] = None
        self._response_thread_stop = threading.Event()
        self._pending: Dict[str, "queue.Queue[Dict[str, Any]]"] = {}

    def _log(self, message: str) -> None:
        if self._log_callback:
            try:
                self._log_callback("SECONDARY_ASR", message)
            except Exception:
                pass

    def _start_locked(self) -> None:
        if self._process and self._process.is_alive():
            return

        ctx = mp.get_context("spawn")
        self._request_queue = ctx.Queue(maxsize=self._queue_size)
        self._response_queue = ctx.Queue(maxsize=self._queue_size)
        self._response_thread_stop.clear()

        self._process = ctx.Process(
            target=_secondary_worker_entry,
            args=(self._request_queue, self._response_queue),
            name="secondary-asr-worker",
            daemon=True,
        )
        self._process.start()
        self._response_thread = threading.Thread(
            target=self._response_dispatch_loop,
            name="secondary-asr-response-dispatch",
            daemon=True,
        )
        self._response_thread.start()
        self._log("Secondary ASR worker process started.")

    def _ensure_started(self) -> None:
        with self._lock:
            if self._process and self._process.is_alive():
                return
            self._start_locked()

    def _response_dispatch_loop(self) -> None:
        while not self._response_thread_stop.is_set():
            response_queue = self._response_queue
            if response_queue is None:
                break

            try:
                response = response_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            except (EOFError, OSError):
                break

            if not isinstance(response, dict):
                continue

            request_id = str(response.get("id") or "")
            if not request_id:
                continue

            with self._lock:
                waiter = self._pending.pop(request_id, None)
            if waiter is None:
                continue

            try:
                waiter.put_nowait(response)
            except queue.Full:
                pass

    def start(self) -> None:
        """Explicitly start worker process."""
        self._ensure_started()

    def _request(
        self,
        payload: Dict[str, Any],
        *,
        timeout_seconds: Optional[float],
        model_id_for_error: str,
    ) -> Dict[str, Any]:
        self._ensure_started()
        request_id = uuid.uuid4().hex
        waiter: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=1)
        with self._lock:
            self._pending[request_id] = waiter
            request_queue = self._request_queue

        if request_queue is None:
            with self._lock:
                self._pending.pop(request_id, None)
            raise RuntimeError("Secondary ASR worker request queue is unavailable.")

        payload["id"] = request_id

        try:
            request_queue.put(payload, timeout=1.0)
        except Exception as error:
            with self._lock:
                self._pending.pop(request_id, None)
            raise RuntimeError(f"Failed to submit secondary ASR request: {error}") from error

        timeout = self._timeout_seconds if timeout_seconds is None else max(1.0, float(timeout_seconds))
        try:
            response = waiter.get(timeout=timeout)
        except queue.Empty as error:
            with self._lock:
                self._pending.pop(request_id, None)
            raise TimeoutError(
                f"Secondary ASR worker timed out after {timeout:.1f}s (model={model_id_for_error})."
            ) from error

        if not response.get("success"):
            raise RuntimeError(str(response.get("error") or "Secondary ASR worker failed."))
        return response

    def warm_model(
        self,
        model_id: str,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Load/activate a secondary model in the worker without transcription."""
        return self._request(
            {
                "type": "warmup",
                "model_id": model_id,
            },
            timeout_seconds=timeout_seconds,
            model_id_for_error=model_id,
        )

    def transcribe_audio_file(
        self,
        audio_path: str,
        model_id: str,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Run retranscription in the secondary worker and return the response payload."""
        return self._request(
            {
                "type": "retranscribe",
                "audio_path": audio_path,
                "model_id": model_id,
            },
            timeout_seconds=timeout_seconds,
            model_id_for_error=model_id,
        )

    def shutdown(self) -> None:
        """Stop worker process and background dispatcher thread."""
        with self._lock:
            process = self._process
            request_queue = self._request_queue
            response_thread = self._response_thread

        if request_queue is not None:
            try:
                request_queue.put(
                    {"id": uuid.uuid4().hex, "type": "shutdown"},
                    timeout=0.25,
                )
            except Exception:
                pass

        if process is not None and process.is_alive():
            process.join(timeout=2.0)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1.0)

        self._response_thread_stop.set()
        if response_thread is not None and response_thread.is_alive():
            response_thread.join(timeout=1.0)

        with self._lock:
            self._process = None
            self._request_queue = None
            self._response_queue = None
            self._response_thread = None
            for waiter in self._pending.values():
                try:
                    waiter.put_nowait(
                        {
                            "success": False,
                            "error": "Secondary ASR worker is shutting down.",
                        }
                    )
                except queue.Full:
                    pass
            self._pending.clear()
        self._log("Secondary ASR worker process stopped.")

    def __del__(self):
        try:
            self.shutdown()
        except Exception:
            pass
