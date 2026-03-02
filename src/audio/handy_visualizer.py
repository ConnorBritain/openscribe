"""Handy-style audio visualization utilities."""

from __future__ import annotations

from typing import List, Optional, Tuple

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except Exception:  # pragma: no cover - fallback path for CI/no-numpy
    np = None
    NUMPY_AVAILABLE = False


class HandyAudioVisualizer:
    """Compute Handy-style multi-bin vocal spectrum levels."""

    def __init__(
        self,
        sample_rate: int,
        window_size: int = 512,
        bucket_count: int = 16,
        freq_min_hz: float = 400.0,
        freq_max_hz: float = 4000.0,
        db_min: float = -55.0,
        db_max: float = -8.0,
        gain: float = 1.3,
        curve_power: float = 0.7,
        noise_alpha: float = 0.001,
    ):
        self.sample_rate = float(sample_rate or 16000)
        self.window_size = int(window_size)
        self.bucket_count = int(bucket_count)
        self.freq_min_hz = float(freq_min_hz)
        self.freq_max_hz = float(freq_max_hz)
        self.db_min = float(db_min)
        self.db_max = float(db_max)
        self.gain = float(gain)
        self.curve_power = float(curve_power)
        self.noise_alpha = float(noise_alpha)

        self._noise_floor = [-40.0] * self.bucket_count
        self._last_levels = [0.0] * self.bucket_count
        self._hann_window = None
        self._bucket_ranges: List[Tuple[int, int]] = []
        self._sample_buffer = None
        self._sample_count = 0

        self._initialize()

    @property
    def last_levels(self) -> List[float]:
        return list(self._last_levels)

    def _initialize(self):
        self._noise_floor = [-40.0] * self.bucket_count
        self._last_levels = [0.0] * self.bucket_count
        self._bucket_ranges = []
        self._sample_count = 0

        if not NUMPY_AVAILABLE:
            self._sample_buffer = None
            self._hann_window = None
            return

        self._sample_buffer = np.zeros(self.window_size, dtype=np.float32)

        # Match Handy's Hann window definition: denominator uses N.
        indices = np.arange(self.window_size, dtype=np.float32)
        self._hann_window = (
            0.5
            * (1.0 - np.cos((2.0 * np.pi * indices) / float(self.window_size)))
        ).astype(np.float32)

        nyquist = self.sample_rate / 2.0
        freq_min = min(self.freq_min_hz, nyquist)
        freq_max = min(self.freq_max_hz, nyquist)
        max_bin = self.window_size // 2

        for bucket_index in range(self.bucket_count):
            log_start = (bucket_index / self.bucket_count) ** 2
            log_end = ((bucket_index + 1) / self.bucket_count) ** 2

            start_hz = freq_min + ((freq_max - freq_min) * log_start)
            end_hz = freq_min + ((freq_max - freq_min) * log_end)

            start_bin = int((start_hz * self.window_size) / self.sample_rate)
            end_bin = int((end_hz * self.window_size) / self.sample_rate)

            if end_bin <= start_bin:
                end_bin = start_bin + 1

            start_bin = min(max(start_bin, 0), max_bin)
            end_bin = min(max(end_bin, start_bin + 1), max_bin)
            self._bucket_ranges.append((start_bin, end_bin))

    def reset(self):
        self._noise_floor = [-40.0] * self.bucket_count
        self._last_levels = [0.0] * self.bucket_count
        self._sample_count = 0
        if NUMPY_AVAILABLE and self._sample_buffer is not None:
            self._sample_buffer.fill(0.0)

    def _append_samples(self, samples):
        if self._sample_buffer is None:
            return
        if self._sample_count >= self.window_size:
            return

        available = self.window_size - self._sample_count
        take = min(int(samples.size), available)
        if take <= 0:
            return

        start = self._sample_count
        end = start + take
        self._sample_buffer[start:end] = samples[:take]
        self._sample_count = end

    def feed(self, frame_data) -> Optional[List[float]]:
        """Feed int16 frame data and return levels when enough samples are buffered.

        Returns:
            - `None` when not enough samples are buffered yet.
            - List of bucket levels when a full window is processed.
            - List of zeros when frame_data is None/empty.
        """
        if not NUMPY_AVAILABLE:
            self._last_levels = [0.0] * self.bucket_count
            return self.last_levels

        if frame_data is None or getattr(frame_data, "size", 0) == 0:
            self.reset()
            return self.last_levels

        if self._hann_window is None or self._sample_buffer is None or not self._bucket_ranges:
            self._last_levels = [0.0] * self.bucket_count
            return self.last_levels

        samples = frame_data.astype(np.float32) / 32768.0
        self._append_samples(samples)
        if self._sample_count < self.window_size:
            return None

        window_samples = self._sample_buffer[:self.window_size]
        self._sample_count = 0

        mean_value = float(np.mean(window_samples))
        fft_input = (window_samples - mean_value) * self._hann_window
        spectrum = np.fft.fft(fft_input)

        levels = [0.0] * self.bucket_count
        max_bin = self.window_size // 2

        for bucket_index, (start_bin, end_bin) in enumerate(self._bucket_ranges):
            if start_bin >= end_bin or end_bin > max_bin:
                continue

            power_sum = 0.0
            for bin_index in range(start_bin, end_bin):
                magnitude = float(np.abs(spectrum[bin_index]))
                power_sum += magnitude * magnitude

            avg_power = power_sum / float(end_bin - start_bin)
            if avg_power > 1e-12:
                db_level = 20.0 * float(np.log10((np.sqrt(avg_power) / self.window_size)))
            else:
                db_level = -80.0

            current_floor = self._noise_floor[bucket_index]
            if db_level < current_floor + 10.0:
                updated_floor = (
                    (self.noise_alpha * db_level)
                    + ((1.0 - self.noise_alpha) * current_floor)
                )
                self._noise_floor[bucket_index] = float(updated_floor)

            normalized = (db_level - self.db_min) / (self.db_max - self.db_min)
            normalized = float(np.clip(normalized, 0.0, 1.0))
            level = float(np.clip((normalized * self.gain) ** self.curve_power, 0.0, 1.0))
            levels[bucket_index] = level

        if len(levels) >= 3:
            smoothed = levels[:]
            for idx in range(1, len(levels) - 1):
                smoothed[idx] = (
                    (levels[idx] * 0.7)
                    + (levels[idx - 1] * 0.15)
                    + (levels[idx + 1] * 0.15)
                )
            levels = smoothed

        self._last_levels = levels
        return levels
