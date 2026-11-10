"""Best-effort YouTube message deletion after a CONFIRMED permanent ban.

This module is intentionally independent from Qt and googleapiclient so it can
be tested without authenticating or contacting YouTube.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event

from .api_errors import is_quota_exhausted, readable_api_error
from .storage import History


@dataclass(frozen=True)
class CleanupResult:
    successes: int
    not_found: int
    failures: int
    attempted: int
    pending: int
    stopped: bool
    quota_exhausted: bool


def cleanup_observed_messages(
    db: History,
    api: object,
    broadcast_id: str,
    channel_id: str,
    *,
    remaining_limit: int,
    stop_signal: Event,
) -> CleanupResult:
    """Remove known chat messages. remaining_limit=0 means unlimited.

    - Only local IDs for the same broadcast + author are used.
    - Already processed IDs (even failed requests) are not automatically retried.
    - 404 is recorded as 'not_found' (not a claim that our delete succeeded).
    - Quota, permissions or rate-limit failure halts the batch.
    """
    successes = not_found = failures = attempted = 0
    stopped = quota_exhausted = False
    candidates = db.cleanup_candidates(broadcast_id, channel_id, remaining_limit)
    for message_id in candidates:
        if stop_signal.is_set():
            stopped = True
            break
        attempted += 1
        try:
            api.delete_message(message_id)
            db.mark_message_delete(message_id, "success")
            successes += 1
        except Exception as exc:
            response = getattr(exc, "resp", None)
            status = int(getattr(response, "status", 0))
            if status == 404:
                db.mark_message_delete(message_id, "not_found", "API 404: メッセージなし")
                not_found += 1
                continue
            db.mark_message_delete(message_id, "failure", readable_api_error(exc)[:300])
            failures += 1
            quota_exhausted = is_quota_exhausted(exc)
            # Any non-404 failure may be systematic; do not burn quota retrying.
            stopped = True
            break
    pending = len(db.cleanup_candidates(broadcast_id, channel_id))
    return CleanupResult(successes, not_found, failures, attempted, pending,
                         stopped, quota_exhausted)
