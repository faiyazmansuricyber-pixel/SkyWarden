from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class HealthSnapshot:
    paused: bool
    p95_latency_ms: float
    server_error_rate: float
    sample_count: int
    reason: str | None


class HealthMonitor:
    def __init__(
        self,
        baseline_latency_ms: float = 100.0,
        window_size: int = 20,
        max_server_error_rate: float = 0.20,
    ) -> None:
        if baseline_latency_ms <= 0 or window_size < 1:
            raise ValueError("Health monitor baseline and window must be positive.")
        self.baseline_latency_ms = baseline_latency_ms
        self.window_size = window_size
        self.max_server_error_rate = max_server_error_rate
        self._samples: deque[tuple[float, int]] = deque(maxlen=window_size)
        self._paused_reason: str | None = None

    @property
    def paused(self) -> bool:
        return self._paused_reason is not None

    def record(self, latency_ms: float, status_code: int) -> HealthSnapshot:
        self._samples.append((max(0.0, latency_ms), status_code))
        latencies = sorted(sample[0] for sample in self._samples)
        rank = max(1, math.ceil(0.95 * len(latencies)))
        p95 = latencies[rank - 1]
        errors = sum(status >= 500 for _, status in self._samples)
        error_rate = errors / len(self._samples)

        if len(self._samples) == self.window_size and self._paused_reason is None:
            if p95 > 3 * self.baseline_latency_ms:
                self._paused_reason = "p95 latency exceeded three times baseline."
            elif error_rate > self.max_server_error_rate:
                self._paused_reason = "5xx rate exceeded the configured threshold."
        return self.snapshot()

    def snapshot(self) -> HealthSnapshot:
        latencies = sorted(sample[0] for sample in self._samples)
        rank = max(1, math.ceil(0.95 * len(latencies))) if latencies else 0
        p95 = latencies[rank - 1] if rank else 0.0
        errors = sum(status >= 500 for _, status in self._samples)
        error_rate = errors / len(self._samples) if self._samples else 0.0
        return HealthSnapshot(
            paused=self.paused,
            p95_latency_ms=p95,
            server_error_rate=error_rate,
            sample_count=len(self._samples),
            reason=self._paused_reason,
        )

    def resume(self) -> None:
        self._paused_reason = None
        self._samples.clear()
