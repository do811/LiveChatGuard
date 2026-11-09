"""Classify API errors without discarding the original error details."""

from __future__ import annotations

import json


def error_reason(exc: Exception) -> str:
    """Return YouTube's most specific error reason when available."""
    details = getattr(exc, "error_details", None)
    if isinstance(details, list):
        for item in details:
            if isinstance(item, dict):
                reason = item.get("reason")
                if reason:
                    return str(reason)
    content = getattr(exc, "content", b"")
    if content:
        try:
            parsed = json.loads(content)
            error = parsed.get("error", {})
            for item in error.get("errors", []):
                reason = item.get("reason")
                if reason:
                    return str(reason)
            status = error.get("status")
            if status:
                return str(status)
        except (TypeError, UnicodeError, ValueError, AttributeError):
            pass
    return ""


def is_quota_exhausted(exc: Exception) -> bool:
    """Errors that should stop monitoring until quota is restored."""
    reason = error_reason(exc).lower()
    return reason in {"quotaexceeded", "dailylimitexceeded", "quota_exceeded",
                      "daily_limit_exceeded", "resource_exhausted"}


def is_rate_limited(exc: Exception) -> bool:
    reason = error_reason(exc).lower()
    return reason in {"ratelimitexceeded", "userratelimitexceeded",
                      "livechatratelimitexceeded", "rate_limit_exceeded"}


def readable_api_error(exc: Exception) -> str:
    reason = error_reason(exc)
    if is_quota_exhausted(exc):
        return f"API割り当て上限に達しました（{reason}）。Google Cloudの割り当てを確認してください。"
    if is_rate_limited(exc):
        return f"API呼び出し頻度の制限（{reason}）。待機間隔を延長します。"
    if reason:
        return f"YouTube APIエラー [{reason}]: {exc}"
    return str(exc)
