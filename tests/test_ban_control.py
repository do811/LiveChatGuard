"""BAN removal never trusts user IDs or dry-run records alone."""

import pytest

from livechat_guard.ban_control import release_permanent_ban
from livechat_guard.storage import History, user_txt


class FakeBanApi:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def unban(self, ban_id):
        self.calls.append(ban_id)
        if self.error:
            raise self.error


def history(tmp_path):
    return History(tmp_path / "history.sqlite3")


def test_only_successful_permanent_ban_with_id_is_releasable(tmp_path):
    db = history(tmp_path)
    try:
        db.add_action("video1", "viewer", "User", "permanent_ban", "fail", "failure", ban_id="bad")
        db.add_action("video1", "viewer", "User", "permanent_ban", "dry", "dry_run", ban_id="dry")
        db.add_action("video1", "viewer", "User", "temporary_ban", "temp", "success", ban_id="temp")
        assert db.active_permanent_bans("viewer") == []
        api = FakeBanApi()
        with pytest.raises(ValueError):
            release_permanent_ban(db, api, {"channel_id": "viewer", "ban_id": "bad", "broadcast_id": "video1", "display_name": "User"})
        assert api.calls == []

        db.add_action("video1", "viewer", "User", "permanent_ban", "real", "success", ban_id="ban123")
        record = db.active_permanent_bans("viewer")[0]
        detail = release_permanent_ban(db, api, record)
        assert "BAN解除成功" in detail
        assert api.calls == ["ban123"]
        assert db.active_permanent_bans("viewer") == []
        assert "永久BAN解除" in user_txt("viewer", db.history_for_user("viewer"))
        with pytest.raises(ValueError):
            release_permanent_ban(db, api, record)
        assert api.calls == ["ban123"]
    finally:
        db.close()


def test_failed_unban_records_error_and_leaves_ban_active(tmp_path):
    db = history(tmp_path)
    try:
        db.add_action("video1", "viewer", "User", "permanent_ban", "real", "success", ban_id="banX")
        record = db.active_permanent_bans("viewer")[0]
        api = FakeBanApi(RuntimeError("denied"))
        with pytest.raises(RuntimeError, match="denied"):
            release_permanent_ban(db, api, record)
        assert db.active_permanent_bans("viewer")[0]["ban_id"] == "banX"
        events = db.history_for_user("viewer")
        assert events[-1]["kind"] == "ban_lift"
        assert events[-1]["outcome"] == "failure"
    finally:
        db.close()


def test_multiple_chat_bans_are_independent(tmp_path):
    db = history(tmp_path)
    try:
        db.add_action("video1", "viewer", "User", "permanent_ban", "one", "success", ban_id="id1")
        db.add_action("video2", "viewer", "User", "permanent_ban", "two", "success", ban_id="id2")
        records = db.active_permanent_bans("viewer")
        assert {r["ban_id"] for r in records} == {"id1", "id2"}
        api = FakeBanApi()
        release_permanent_ban(db, api, next(r for r in records if r["ban_id"] == "id1"))
        assert [r["ban_id"] for r in db.active_permanent_bans("viewer")] == ["id2"]
    finally:
        db.close()


def test_unban_404_marks_as_no_longer_active_without_claiming_success(tmp_path):
    class GoneError(Exception):
        resp = type("Response", (), {"status": 404})()

    db = history(tmp_path)
    try:
        db.add_action("video1", "viewer", "User", "permanent_ban", "real", "success", ban_id="gone")
        record = db.active_permanent_bans("viewer")[0]
        result = release_permanent_ban(db, FakeBanApi(GoneError("not found")), record)
        assert "見つかりません" in result
        assert not db.active_permanent_bans("viewer")
        assert db.history_for_user("viewer")[-1]["outcome"] == "not_found"
    finally:
        db.close()
