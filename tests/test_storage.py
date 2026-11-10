from datetime import datetime, timedelta, timezone

from livechat_guard.storage import History, user_txt


def test_save_duplicate_prevention_export_and_delete(tmp_path):
    db = History(tmp_path / "messages.db")
    try:
        moment = datetime.now(timezone.utc).isoformat()
        assert db.add_message("msg1", "broadcast1", "UC1", "User 1", "こんにちは", moment)
        assert not db.add_message("msg1", "broadcast1", "UC1", "User 1", "こんにちは", moment)
        db.add_action("broadcast1", "UC1", "User 1", "warning", "3回連投", "dry_run")
        db.add_action("broadcast1", "UC1", "User 1", "permanent_ban", "5回連投", "success")
        rows = db.history_for_user("UC1")
        log = user_txt("UC1", rows)
        assert "アカウント：User 1" in log
        assert "こんにちは" in log
        assert "＝＝警告発動＝＝" in log
        assert "＝＝永久BAN発動＝＝" in log
        assert len(db.recent_users()) == 1
        db.delete_user("UC1")
        assert not db.recent_users()
    finally:
        db.close()


def test_only_successful_temporary_bans_count_as_reoffenses(tmp_path):
    db = History(tmp_path / "messages.db")
    try:
        for status in ("success", "failure", "dry_run"):
            db.add_action("b1", "UC1", "Alice", "temporary_ban", "5分間", status)
        db.add_action("b1", "UC2", "Bob", "temporary_ban", "5分間", "success")
        assert db.recent_temporary_bans("UC1", 24) == 1
        assert db.recent_temporary_bans("UC2", 24) == 1
    finally:
        db.close()


def test_retention_removes_old_data(tmp_path):
    db = History(tmp_path / "messages.db")
    try:
        old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        fresh = datetime.now(timezone.utc).isoformat()
        db.add_message("old1", "b", "UC1", "Alice", "old", old)
        db.add_message("new1", "b", "UC1", "Alice", "new", fresh)
        db.add_action("b", "UC1", "Alice", "warning", "old", "success", timestamp=old)
        assert db.purge_expired(29) == (1, 1)
        assert len(db.history_for_user("UC1")) == 1
    finally:
        db.close()


def test_action_appears_next_to_triggering_comment_even_when_api_is_delayed(tmp_path):
    db = History(tmp_path / "messages.db")
    try:
        start = datetime.now(timezone.utc) - timedelta(seconds=20)
        first = start.isoformat()
        second = (start + timedelta(seconds=2)).isoformat()
        db.add_message("m1", "b", "UC1", "A", "一件目", first)
        db.add_message("m2", "b", "UC1", "A", "二件目", second)
        db.add_action("b", "UC1", "A", "warning", "警告", "success",
                      timestamp=datetime.now(timezone.utc).isoformat(), trigger_at=first)
        entries = db.history_for_user("UC1")
        assert [e["kind"] for e in entries] == ["message", "warning", "message"]
    finally:
        db.close()


def test_legacy_database_migrates_cleanup_columns(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TABLE messages (
            message_id TEXT PRIMARY KEY,
            broadcast_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            display_name TEXT NOT NULL,
            body TEXT NOT NULL,
            published_at TEXT NOT NULL
        )""")
        connection.execute("""INSERT INTO messages VALUES
            ('old', 'b1', 'UC_A', 'Alice', '過去のコメント', '2026-01-01T00:00:00+00:00')""")
    db = History(path)
    try:
        assert db.cleanup_candidates("b1", "UC_A") == ["old"]
        db.mark_message_delete("old", "success")
        assert db.cleanup_candidates("b1", "UC_A") == []
        assert "過去のコメント" in user_txt("UC_A", db.history_for_user("UC_A"))
        assert "削除成功" in user_txt("UC_A", db.history_for_user("UC_A"))
    finally:
        db.close()
