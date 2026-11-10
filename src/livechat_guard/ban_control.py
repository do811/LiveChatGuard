"""Verified permanent-ban lifting and audit logging (no Qt dependencies)."""

from __future__ import annotations

from .api_errors import readable_api_error
from .storage import History


def release_permanent_ban(db: History, api: object, record: dict) -> str:
    """Revoke one locally confirmed ban ID; keep failed/successful attempts in history.

    A channel ID alone is *not* sufficient to revoke a ban. Only a matching
    YouTube ban resource ID saved from a successful permanent-ban insert is used.
    """
    channel_id = record["channel_id"]
    ban_id = record.get("ban_id")
    active = db.active_permanent_bans(channel_id)
    if not ban_id or not any(item["ban_id"] == ban_id for item in active):
        raise ValueError("BANは既に解除済み、または解除可能なBAN IDが見つかりません。")

    try:
        api.unban(ban_id)
    except Exception as exc:
        response = getattr(exc, "resp", None)
        if int(getattr(response, "status", 0)) == 404:
            detail = f"BAN ID {ban_id} はYouTube上で見つかりませんでした。既に解除済み、または無効なIDです。"
            db.add_action(record["broadcast_id"], channel_id,
                          record["display_name"], "ban_lift", detail,
                          "not_found", ban_id=ban_id)
            return detail
        detail = readable_api_error(exc)
        db.add_action(record["broadcast_id"], channel_id,
                      record["display_name"], "ban_lift", detail,
                      "failure", ban_id=ban_id)
        raise RuntimeError(f"BAN解除失敗：{detail}") from exc

    detail = f"BAN解除成功（配信ID: {record['broadcast_id']}、BAN ID: {ban_id}）"
    db.add_action(record["broadcast_id"], channel_id,
                  record["display_name"], "ban_lift", detail,
                  "success", ban_id=ban_id)
    return detail
