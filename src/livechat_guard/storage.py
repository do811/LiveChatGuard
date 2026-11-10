"""SQLite history and human-readable user history export."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def local_display(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%Y/%m/%d %H:%M:%S")
    except (ValueError, AttributeError):
        return str(iso)


class History:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(db_path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout = 10000")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA secure_delete=ON")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                broadcast_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                body TEXT NOT NULL,
                published_at TEXT NOT NULL,
                delete_outcome TEXT,
                delete_note TEXT,
                deleted_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_messages_user_time
                ON messages(channel_id, published_at);
            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                broadcast_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                kind TEXT NOT NULL,
                detail TEXT NOT NULL,
                outcome TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                ban_id TEXT,
                trigger_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_actions_user_time
                ON actions(channel_id, timestamp);
        """)
        # Older databases can be opened after upgrading the app.
        existing = {r["name"] for r in self.connection.execute("PRAGMA table_info(actions)")}
        if "trigger_at" not in existing:
            self.connection.execute("ALTER TABLE actions ADD COLUMN trigger_at TEXT")
        message_columns = {r["name"] for r in self.connection.execute("PRAGMA table_info(messages)")}
        for column in ("delete_outcome", "delete_note", "deleted_at"):
            if column not in message_columns:
                self.connection.execute(f"ALTER TABLE messages ADD COLUMN {column} TEXT")
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def add_message(
        self, message_id: str, broadcast_id: str, channel_id: str,
        display_name: str, body: str, published_at: str,
    ) -> bool:
        cursor = self.connection.execute("""
            INSERT OR IGNORE INTO messages
            (message_id, broadcast_id, channel_id, display_name, body, published_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (message_id, broadcast_id, channel_id, display_name, body, published_at))
        self.connection.commit()
        return cursor.rowcount == 1

    def cleanup_candidates(self, broadcast_id: str, channel_id: str,
                           limit: int = 0) -> list[str]:
        """Known message IDs of this user on the current stream, oldest first.

        0 limit means all. Never fetch more messages from YouTube just to delete them.
        """
        sql = """SELECT message_id FROM messages
                 WHERE broadcast_id=? AND channel_id=?
                   AND delete_outcome IS NULL
                 ORDER BY published_at ASC, message_id ASC"""
        if limit:
            sql += " LIMIT ?"
            params = (broadcast_id, channel_id, limit)
        else:
            params = (broadcast_id, channel_id)
        return [row["message_id"] for row in self.connection.execute(sql, params)]

    def mark_message_delete(self, message_id: str, outcome: str, note: str = "") -> None:
        if outcome not in ("success", "not_found", "failure"):
            raise ValueError("Unknown delete outcome")
        self.connection.execute("""
            UPDATE messages SET delete_outcome=?, delete_note=?, deleted_at=?
            WHERE message_id=?
        """, (outcome, note, utc_now(), message_id))
        self.connection.commit()

    def add_action(
        self, broadcast_id: str, channel_id: str, display_name: str,
        kind: str, detail: str, outcome: str, ban_id: str | None = None,
        timestamp: str | None = None, trigger_at: str | None = None,
    ) -> None:
        self.connection.execute("""
            INSERT INTO actions
            (broadcast_id, channel_id, display_name, kind, detail, outcome, timestamp, ban_id, trigger_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (broadcast_id, channel_id, display_name, kind, detail, outcome,
              timestamp or utc_now(), ban_id, trigger_at))
        self.connection.commit()

    def active_permanent_bans(self, channel_id: str) -> list[dict]:
        """Confirmed permanent bans with IDs, excluding successfully lifted ones.

        Ban IDs are unique to a live chat, not the author's channel ID.
        Failed / dry-run attempts to lift a ban do not change its active state.
        """
        rows = self.connection.execute("""
            SELECT b.broadcast_id, b.channel_id, b.display_name, b.ban_id,
                   b.timestamp, b.id
              FROM actions AS b
             WHERE b.channel_id=? AND b.kind='permanent_ban'
                   AND b.outcome='success' AND b.ban_id IS NOT NULL
                   AND b.ban_id <> ''
                   AND NOT EXISTS (
                       SELECT 1 FROM actions AS u
                        WHERE u.kind='ban_lift' AND u.outcome IN ('success', 'not_found')
                              AND u.ban_id=b.ban_id
                   )
             ORDER BY b.timestamp DESC, b.id DESC
        """, (channel_id,)).fetchall()
        seen: set[str] = set()
        result = []
        for row in rows:
            if row['ban_id'] not in seen:
                seen.add(row['ban_id'])
                result.append(dict(row))
        return result

    def recent_temporary_bans(self, channel_id: str, hours: int) -> int:
        """Only confirmed API bans count as prior offenses, not dry runs/errors."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        row = self.connection.execute("""
            SELECT COUNT(*) AS count FROM actions
            WHERE channel_id = ? AND kind = 'temporary_ban'
              AND outcome = 'success' AND timestamp >= ?
        """, (channel_id, cutoff)).fetchone()
        return int(row["count"])

    def recent_users(self, query: str = "", only_actions: bool = False, limit: int = 500):
        """Group by stable channel ID; derive latest name across comments/actions."""
        rows = self.connection.execute("""
            WITH all_events AS (
                SELECT channel_id, display_name, published_at AS moment,
                       1 AS message_count, 0 AS action_count FROM messages
                UNION ALL
                SELECT channel_id, display_name, timestamp AS moment,
                       0 AS message_count, 1 AS action_count FROM actions
            ), totals AS (
                SELECT channel_id, MAX(moment) AS last_seen,
                       SUM(message_count) AS messages, SUM(action_count) AS actions
                FROM all_events GROUP BY channel_id
            )
            SELECT totals.*, (
                SELECT display_name FROM all_events e
                WHERE e.channel_id=totals.channel_id
                ORDER BY moment DESC LIMIT 1
            ) AS display_name
            FROM totals ORDER BY last_seen DESC
        """).fetchall()
        filtered = [row for row in rows
                    if (not query or query.casefold() in row["display_name"].casefold()
                        or query.casefold() in row["channel_id"].casefold())
                    and (not only_actions or row["actions"] > 0)]
        return filtered[:limit]

    def history_for_user(self, channel_id: str, limit: int = 10000):
        messages = self.connection.execute("""
            SELECT published_at AS moment, published_at AS action_at,
                   0 AS row_order, 'message' AS kind,
                   body AS detail, '' AS outcome, display_name, broadcast_id,
                   delete_outcome, delete_note
            FROM messages WHERE channel_id = ?
        """, (channel_id,)).fetchall()
        actions = self.connection.execute("""
            SELECT COALESCE(trigger_at, timestamp) AS moment, timestamp AS action_at,
                   1 AS row_order, kind, detail, outcome,
                   display_name, broadcast_id,
                   NULL AS delete_outcome, NULL AS delete_note
            FROM actions WHERE channel_id = ?
        """, (channel_id,)).fetchall()
        return sorted([dict(r) for r in messages] + [dict(r) for r in actions],
                      key=lambda r: (r["moment"], r["row_order"]))[-limit:]

    def delete_user(self, channel_id: str) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM messages WHERE channel_id = ?", (channel_id,))
            self.connection.execute("DELETE FROM actions WHERE channel_id = ?", (channel_id,))

    def purge_expired(self, retention_days: int) -> tuple[int, int]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        with self.connection:
            messages = self.connection.execute("DELETE FROM messages WHERE published_at < ?", (cutoff,)).rowcount
            actions = self.connection.execute("DELETE FROM actions WHERE timestamp < ?", (cutoff,)).rowcount
        return messages, actions


def user_txt(channel_id: str, entries: list[dict]) -> str:
    name = entries[-1]["display_name"] if entries else "不明なユーザー"
    lines = [f"アカウント：{name}", f"チャンネルID：{channel_id}", ""]
    labels = {"warning": "警告発動", "temporary_ban": "一時制限発動",
              "permanent_ban": "永久BAN発動", "message_cleanup": "過去コメント削除", "ban_lift": "永久BAN解除"}
    for event in entries:
        if event["kind"] == "message":
            # Indent embedded newlines so multiline comments remain readable.
            body = str(event["detail"]).replace("\r\n", "\n").replace("\r", "\n")
            body = body.replace("\n", "\n    ")
            lines.append(f"[{local_display(event['moment'])}] {body}")
            if event.get("delete_outcome"):
                outcome_labels = {"success": "削除成功", "not_found": "既に存在しない（404）", "failure": "削除失敗"}
                status = outcome_labels.get(event["delete_outcome"], event["delete_outcome"])
                note = event.get("delete_note") or ""
                lines.append(f"    YouTube上の削除：{status}" + (f" / {note}" if note else ""))
        else:
            title = labels.get(event["kind"], event["kind"])
            lines.append(f"＝＝{title}＝＝")
            lines.append(f"[{local_display(event['action_at'])}] {event['detail']}")
            lines.append(f"処理結果：{event['outcome']}")
    return "\n".join(lines) + "\n"
