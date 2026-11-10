"""Local quota ledger: estimation only, not actual Cloud project usage."""

from datetime import datetime, timezone
import json

import pytest

from livechat_guard.quota import COSTS, QuotaLedger, oauth_project_key, quota_day


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_official_costs():
    assert COSTS["liveChatBans.insert"] == 200
    assert COSTS["liveChatBans.delete"] == 200
    assert COSTS["liveChatMessages.delete"] == 20
    assert COSTS["liveChatMessages.streamList"] == 5
    assert COSTS["liveChatMessages.list"] == 5
    assert COSTS["liveBroadcasts.list"] == 1


def test_quota_day_rollover_pst_and_pdt():
    assert quota_day(instant("2026-11-10T07:59:59Z")) == "2026-11-09"
    assert quota_day(instant("2026-11-10T08:00:00Z")) == "2026-11-10"
    assert quota_day(instant("2026-07-01T06:59:59Z")) == "2026-06-30"
    assert quota_day(instant("2026-07-01T07:00:00Z")) == "2026-07-01"
    with pytest.raises(ValueError):
        quota_day(datetime(2026, 11, 10))


def test_record_attempt_snapshot_separates_project_and_pt_day(tmp_path):
    db = tmp_path / "quota.sqlite3"
    a = QuotaLedger(db, project="proj-A")
    b = QuotaLedger(db, project="proj-B")
    before = instant("2026-11-10T07:50:00Z")
    after = instant("2026-11-10T08:20:00Z")
    a.record_attempt("liveChatMessages.streamList", before)
    a.record_attempt("liveChatBans.insert", before)
    a.record_attempt("liveChatBans.delete", after)
    b.record_attempt("liveChatMessages.delete", before)

    prev = a.snapshot(500, before)
    assert (prev.used, prev.calls, prev.estimated_remaining, prev.date_pt) == (205, 2, 295, "2026-11-09")
    assert a.snapshot(500, after).used == 200
    assert b.snapshot(500, before).used == 20
    assert a.snapshot(100, before).estimated_remaining == 0
    assert a.breakdown(before) == [("liveChatBans.insert", 1, 200),
                                   ("liveChatMessages.streamList", 1, 5)]
    with pytest.raises(ValueError):
        a.record_attempt("unknown.method")


def test_exceeded_flag_is_recorded_per_day_project(tmp_path):
    db = tmp_path / "quota.sqlite3"
    a = QuotaLedger(db, project="A")
    b = QuotaLedger(db, project="B")
    a.mark_exceeded(instant("2026-11-10T07:59:59Z"))
    assert a.snapshot(10000, instant("2026-11-10T07:59:59Z")).quota_exceeded
    assert not a.snapshot(10000, instant("2026-11-10T08:01:00Z")).quota_exceeded
    assert not b.snapshot(10000, instant("2026-11-10T07:59:59Z")).quota_exceeded


def test_project_id_from_oauth_json_without_storing_secret(tmp_path):
    path = tmp_path / "client_secrets.json"
    path.write_text(json.dumps({"installed": {"project_id": "test-project", "client_secret": "private"}}))
    assert oauth_project_key(str(path)) == "test-project"
    assert oauth_project_key(str(tmp_path / "missing.json")) == "unknown-project"
    path.write_text(json.dumps({"installed": {"client_id": "myid", "client_secret": "private"}}))
    assert oauth_project_key(str(path)).startswith("client-")
    assert "myid" not in oauth_project_key(str(path))
