# audio_source.py
# Per-source audio capture + VAD abstraction for multi-source dictation.

try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False
    sd = None

try:
    import webrtcvad
    WEBRTCVAD_AVAILABLE = True
except ImportError:
    WEBRTCVAD_AVAILABLE = False
    webrtcvad = None

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    np = None

import collections
import sys
import threading
import time

from src.config import config
from src.utils.utils import log_text


class AudioSource:
    """Captures audio from a single device with its own VAD + ring buffer.

    Each AudioSource owns:
    - A sounddevice InputStream (one per device)
    - A WebRTC VAD instance
    - A ring buffer + voiced frames accumulator
    - An on_speech_end callback that includes the speaker name
    """

    def __init__(
        self,
        device_id,
        device_name,
        speaker_name="",
        sample_rate=None,
        on_speech_end=None,
        on_status_update=None,
        source_type="input",
    ):
        self.device_id = device_id
        self.device_name = device_name
        self.speaker_name = speaker_name
        self.source_type = source_type  # "input" or "loopback"
        self.sample_rate = sample_rate or config.SAMPLE_RATE

        self.on_speech_end = on_speech_end
        self.on_status_update = on_status_update

        self._stream = None
        self._active = False
        self._stop_event = threading.Event()

        # VAD
        self._vad = webrtcvad.Vad(config.VAD_AGGRESSIVENESS) if WEBRTCVAD_AVAILABLE else None
        self._frame_duration_ms = config.FRAME_DURATION_MS
        self._frame_size = int(self.sample_rate * self._frame_duration_ms / 1000)

        # Buffering
        ring_buffer_size = int(config.RING_BUFFER_DURATION_MS / self._frame_duration_ms)
        self._ring_buffer = collections.deque(maxlen=ring_buffer_size)
        self._voiced_frames = []
        self._triggered = False
        self._silence_start_time = None

        # Auto-stop on silence
        self._auto_stop_on_silence = True

        # Accumulation buffer for callback-based input
        self._accumulator = bytearray()
        self._accumulator_lock = threading.Lock()

        # RMS level for visualization
        self._last_rms = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        """Open the sounddevice InputStream and begin capture."""
        if not SOUNDDEVICE_AVAILABLE:
            log_text("AUDIO_SOURCE", f"sounddevice not available, cannot start source '{self.device_name}'")
            return

        self._stop_event.clear()
        self._active = True
        self._reset_buffering()

        device_index = self._resolve_device_index()

        extra_settings = None
        if self.source_type == "loopback" and sys.platform == "win32":
            try:
                extra_settings = sd.WasapiSettings(exclusive=False)
            except Exception as e:
                log_text("AUDIO_SOURCE", f"WASAPI loopback settings failed: {e}")

        try:
            self._stream = sd.InputStream(
                device=device_index,
                samplerate=self.sample_rate,
                channels=config.CHANNELS,
                dtype=config.AUDIO_DTYPE,
                blocksize=self._frame_size,
                callback=self._audio_callback,
                extra_settings=extra_settings,
            )
            self._stream.start()
            log_text("AUDIO_SOURCE", f"Started source '{self.device_name}' (speaker: {self.speaker_name or 'unnamed'})")
        except Exception as e:
            self._active = False
            log_text("AUDIO_SOURCE", f"Failed to start source '{self.device_name}': {e}")
            if self.on_status_update:
                self.on_status_update(f"Audio source '{self.device_name}' failed: {e}", "red")

    def stop(self):
        """Stop the stream and clean up."""
        self._stop_event.set()
        self._active = False

        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                log_text("AUDIO_SOURCE", f"Error stopping source '{self.device_name}': {e}")
            self._stream = None

        self._reset_buffering()
        log_text("AUDIO_SOURCE", f"Stopped source '{self.device_name}'")

    @property
    def is_active(self):
        return self._active and self._stream is not None

    @property
    def last_rms(self):
        return self._last_rms

    def set_auto_stop_on_silence(self, enabled):
        self._auto_stop_on_silence = bool(enabled)

    # ------------------------------------------------------------------
    # Dictation state control
    # ------------------------------------------------------------------

    def begin_dictation(self):
        """Reset buffering state to prepare for a new dictation capture."""
        self._reset_buffering()

    def end_dictation(self):
        """Process any remaining voiced frames and reset."""
        self._request_audio_processing()
        self._reset_buffering()

    # ------------------------------------------------------------------
    # Internal: sounddevice callback
    # ------------------------------------------------------------------

    def _audio_callback(self, indata, frames, time_info, status):
        """Called by sounddevice on the audio thread."""
        if status:
            log_text("AUDIO_SOURCE", f"Stream status for '{self.device_name}': {status}")

        if not self._active or self._stop_event.is_set():
            return

        # indata is a numpy array of shape (frames, channels)
        # Convert to int16 bytes for VAD processing
        frame_bytes = indata.tobytes()

        with self._accumulator_lock:
            self._accumulator.extend(frame_bytes)

        # Process complete frames
        expected_frame_bytes = self._frame_size * config.AUDIO_SAMPLE_WIDTH * config.CHANNELS
        while True:
            with self._accumulator_lock:
                if len(self._accumulator) < expected_frame_bytes:
                    break
                frame = bytes(self._accumulator[:expected_frame_bytes])
                del self._accumulator[:expected_frame_bytes]

            self._process_frame(frame)

    # ------------------------------------------------------------------
    # Internal: VAD + accumulation (mirrors AudioHandler logic)
    # ------------------------------------------------------------------

    def _process_frame(self, frame_bytes):
        """Process a single audio frame with VAD during dictation."""
        if not NUMPY_AVAILABLE or not WEBRTCVAD_AVAILABLE:
            return

        if not frame_bytes or len(frame_bytes) == 0:
            return

        expected_size = self._frame_size * config.AUDIO_SAMPLE_WIDTH
        if len(frame_bytes) != expected_size:
            return

        frame_data = np.frombuffer(frame_bytes, dtype=np.int16)

        # Compute RMS for level metering
        if frame_data.size > 0:
            self._last_rms = float(np.sqrt(np.mean(frame_data.astype(np.float32) ** 2)))

        # Skip all-zero frames
        if np.all(frame_data == 0):
            return

        # VAD
        try:
            is_speech = self._vad.is_speech(frame_bytes, self.sample_rate)
        except Exception:
            is_speech = False

        if not self._triggered:
            self._ring_buffer.append((frame_data, is_speech))
            num_voiced = sum(1 for _, speech in self._ring_buffer if speech)
            if num_voiced > 0.5 * self._ring_buffer.maxlen:
                self._triggered = True
                self._silence_start_time = None
                for f, s in self._ring_buffer:
                    self._voiced_frames.append(f)
                self._ring_buffer.clear()
        else:
            self._voiced_frames.append(frame_data)

            if not is_speech:
                if not self._auto_stop_on_silence:
                    self._silence_start_time = None
                else:
                    if self._silence_start_time is None:
                        self._silence_start_time = time.time()
                    else:
                        silence_duration = time.time() - self._silence_start_time
                        if silence_duration >= config.SILENCE_THRESHOLD_SECONDS:
                            self._triggered = False
                            self._silence_start_time = None
                            self._request_audio_processing()
            else:
                self._silence_start_time = None

    def _request_audio_processing(self):
        """Concatenate voiced frames and fire the on_speech_end callback."""
        if not self._voiced_frames or not NUMPY_AVAILABLE:
            return

        frames_to_process = list(self._voiced_frames)
        audio_data = np.concatenate(frames_to_process) if frames_to_process else np.array([], dtype=np.int16)
        self._reset_buffering()

        if self.on_speech_end and audio_data.size > 0:
            self.on_speech_end(audio_data, self.speaker_name)

    def _reset_buffering(self):
        """Reset ring buffer and voiced frames."""
        self._ring_buffer.clear()
        self._voiced_frames = []
        self._triggered = False
        self._silence_start_time = None

    # ------------------------------------------------------------------
    # Internal: device resolution
    # ------------------------------------------------------------------

    def _resolve_device_index(self):
        """Resolve device_id to a sounddevice device index."""
        if not SOUNDDEVICE_AVAILABLE:
            return None

        device_id = self.device_id
        if device_id in (None, "", "default", "system"):
            return None  # sounddevice default

        # Handle loopback device IDs like "loopback:3"
        if isinstance(device_id, str) and device_id.startswith("loopback:"):
            try:
                return int(device_id.split(":", 1)[1])
            except (ValueError, IndexError):
                return None

        try:
            return int(device_id)
        except (ValueError, TypeError):
            return None
