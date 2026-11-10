"""Tests for post-BAN cleanup, without any network or Google account."""

from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace

from livechat_guard.cleanup import cleanup_observed_messages
from livechat_guard.storage import History, user_txt


class FakeAPI:
    def __init__(self, failures=None):
        self.calls = []
        self.failures = failures or {}

    def delete_message(self, message_id):
        self.calls.append(message_id)
        if message_id in self.failures:
            raise self.failures[message_id]


class FakeHttpError(Exception):
    def __init__(self, status, reason):
        self.resp = SimpleNamespace(status=status)
        self.error_details = [{"reason": reason}]
        super().__init__(f"HTTP {status}: {reason}")


def make_db(tmp_path):
    db = History(tmp_path / "history.db")
    time = datetime.now(timezone.utc) - timedelta(seconds=10)
    for index in range(1, 6):
        db.add_message(f"msg{index}", "broadcastA", "UC_A", "Alice", f"comment{index}",
                       (time + timedelta(seconds=index)).isoformat())
    db.add_message("other-user", "broadcastA", "UC_B", "Bob", "secret", time.isoformat())
    db.add_message("other-broadcast", "broadcastB", "UC_A", "Alice", "old", time.isoformat())
    return db


def test_successful_cleanup_only_same_user_and_live_broadcast(tmp_path):
    db = make_db(tmp_path)
    try:
        api = FakeAPI()
        result = cleanup_observed_messages(db, api, "broadcastA", "UC_A",
                                           remaining_limit=0, stop_signal=Event())
        assert api.calls == [f"msg{x}" for x in range(1, 6)]
        assert (result.successes, result.pending, result.attempted) == (5, 0, 5)
        assert db.cleanup_candidates("broadcastA", "UC_A") == []
        assert db.cleanup_candidates("broadcastB", "UC_A") == ["other-broadcast"]
        assert db.cleanup_candidates("broadcastA", "UC_B") == ["other-user"]
        # Local history is never removed when deleting YouTube messages.
        txt = user_txt("UC_A", db.history_for_user("UC_A"))
        assert "comment1" in txt and "YouTube上の削除：削除成功" in txt
        assert cleanup_observed_messages(db, api, "broadcastA", "UC_A",
                                         remaining_limit=0, stop_signal=Event()).attempted == 0
    finally:
        db.close()


def test_bounded_delete_and_404(tmp_path):
    db = make_db(tmp_path)
    try:
        api = FakeAPI({"msg1": FakeHttpError(404, "liveChatMessageNotFound")})
        result = cleanup_observed_messages(db, api, "broadcastA", "UC_A",
                                           remaining_limit=2, stop_signal=Event())
        assert result.attempted == 2 and result.not_found == 1 and result.successes == 1
        assert result.pending == 3
        assert db.cleanup_candidates("broadcastA", "UC_A") == ["msg3", "msg4", "msg5"]
        assert "既に存在しない" in user_txt("UC_A", db.history_for_user("UC_A"))
    finally:
        db.close()


def test_quota_error_stops_and_does_not_retry_failed_ids(tmp_path):
    db = make_db(tmp_path)
    try:
        api = FakeAPI({"msg2": FakeHttpError(403, "quotaExceeded")})
        result = cleanup_observed_messages(db, api, "broadcastA", "UC_A",
                                           remaining_limit=0, stop_signal=Event())
        assert api.calls == ["msg1", "msg2"]
        assert result.successes == 1 and result.failures == 1
        assert result.quota_exhausted and result.stopped
        assert db.cleanup_candidates("broadcastA", "UC_A") == ["msg3", "msg4", "msg5"]
    finally:
        db.close()


def test_stop_signal_causes_no_calls(tmp_path):
    db = make_db(tmp_path)
    try:
        stop = Event(); stop.set()
        api = FakeAPI()
        result = cleanup_observed_messages(db, api, "broadcastA", "UC_A",
                                           remaining_limit=0, stop_signal=stop)
        assert result.attempted == 0 and result.pending == 5 and result.stopped
        assert api.calls == []
    finally:
        db.close()
