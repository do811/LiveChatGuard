"""Deterministic, quota-conservative reconnect policy for server streaming.

The server may close a successful stream normally. Such an EOF is not a gRPC
error, and a stream that actually delivered data must not be called a failure.
Still, every *new connection* consumes quota, so repeated closures need
backoff even when they delivered a response.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPlan:
    delay_seconds: float
    reason: str
    quiet_period: bool = False


class StreamRecovery:
    """Per-monitoring-session policy, using injected monotonic timestamps.

    At most 10 connection starts per rolling 10 minutes, except for an already
    open connection. A circuit-breaker *pauses* connection attempts instead of
    permanently stopping monitoring after an arbitrary 5 EOFs.
    """

    def __init__(self, *, max_starts: int = 10, window_seconds: float = 600):
        self._starts: deque[float] = deque()
        self.max_starts = max_starts
        self.window_seconds = window_seconds
        self.empty_streak = 0
        self.error_streak = 0
        self.early_closes = 0

    def connection_started(self, now: float) -> None:
        self._trim(now)
        self._starts.append(now)

    def _trim(self, now: float) -> None:
        while self._starts and now - self._starts[0] >= self.window_seconds:
            self._starts.popleft()

    def _budget_delay(self, now: float) -> float:
        self._trim(now)
        if len(self._starts) < self.max_starts:
            return 0.0
        # Oldest request must exit the window before attempting another.
        return max(0.0, self.window_seconds - (now - self._starts[0]) + 1.0)

    def on_disconnect(self, *, now: float, lifetime: float,
                      responses: int, progress: bool, rpc_error: bool) -> RetryPlan:
        """Progress means receiving messages or an advancing nextPageToken."""
        if progress:
            self.empty_streak = 0
            self.error_streak = 0
        else:
            self.empty_streak += 1
            if rpc_error:
                self.error_streak += 1
        if lifetime < 30:
            self.early_closes += 1
        else:
            self.early_closes = 0

        # Successful data delivery may be followed by a legitimate EOF.
        # Nevertheless, prevent rapid reconnect loops that burn quota.
        if progress:
            base = 15.0 if lifetime < 30 else 5.0
            reason = "データ受信後に接続が終了しました"
        elif rpc_error:
            base = min(10.0 * (2 ** min(self.error_streak - 1, 5)), 300.0)
            reason = "通信エラー後の再接続"
        else:
            base = min(15.0 * (2 ** min(self.empty_streak - 1, 5)), 300.0)
            reason = "新着データを受信せず接続が終了しました"

        # A repeated healthy-looking stream that closes immediately is also
        # costly. There is no assumption that any single EOF is an error.
        if self.early_closes >= 5:
            base = max(base, 90.0)
            reason += "（短時間終了が続いたため間隔を延長）"
        if self.empty_streak >= 5:
            base = max(base, 300.0)
            reason += "（連続空終了・保護待機）"

        budget = self._budget_delay(now)
        if budget > base:
            return RetryPlan(budget, "接続回数の上限に達したためクォータ保護待機", True)
        return RetryPlan(base, reason, self.empty_streak >= 5)
