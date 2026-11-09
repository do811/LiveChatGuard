"""Pure, testable consecutive-comment detector.

Each new text comment starts/resets an N-second timer. We do NOT count messages
inside a moving N-second window. We count consecutive *adjacent intervals* <= N.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Streak:
    last_published_at: datetime
    count: int = 1
    warned: bool = False
    limited: bool = False


class StreakDetector:
    def __init__(self, seconds: int, warning_count: int, limit_count: int):
        if not (seconds > 0 and 2 <= warning_count < limit_count):
            raise ValueError("Invalid detector thresholds")
        self.seconds = seconds
        self.warning_count = warning_count
        self.limit_count = limit_count
        self._users: dict[str, Streak] = {}

    def on_comment(self, channel_id: str, timestamp: datetime) -> tuple[int, str | None]:
        """Return (streak_length, 'warning' | 'limit' | None)."""
        if not channel_id:
            return 0, None
        state = self._users.get(channel_id)
        if state is None:
            self._users[channel_id] = Streak(timestamp)
            return 1, None

        delta = (timestamp - state.last_published_at).total_seconds()
        if delta < 0 or delta > self.seconds:
            state.count = 1
            state.warned = False
            state.limited = False
        else:
            state.count += 1
        state.last_published_at = timestamp

        if state.count >= self.limit_count and not state.limited:
            state.limited = True
            return state.count, "limit"
        if state.count >= self.warning_count and not state.warned:
            state.warned = True
            return state.count, "warning"
        return state.count, None

    def reset(self) -> None:
        self._users.clear()


def choose_restriction(
    mode: str, past_successful_temporary_bans: int, permanent_after: int,
    first_seconds: int, second_seconds: int,
) -> tuple[str, int | None]:
    """Return ('permanent_ban'|'temporary_ban', duration or None)."""
    if mode == "permanent":
        return "permanent_ban", None
    if mode != "staged":
        raise ValueError("Unknown restriction mode")
    offense_number = past_successful_temporary_bans + 1
    if offense_number >= permanent_after:
        return "permanent_ban", None
    duration = first_seconds if offense_number == 1 else second_seconds
    return "temporary_ban", duration
