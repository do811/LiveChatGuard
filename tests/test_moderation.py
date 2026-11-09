from datetime import datetime, timedelta, timezone

from livechat_guard.moderation import StreakDetector, choose_restriction

BASE = datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)


def at(seconds):
    return BASE + timedelta(seconds=seconds)


def test_consecutive_intervals_not_moving_window():
    detector = StreakDetector(seconds=10, warning_count=3, limit_count=5)
    times = [0, 5, 13, 17, 22]
    results = [detector.on_comment("UC1", at(s)) for s in times]
    assert results == [(1, None), (2, None), (3, "warning"), (4, None), (5, "limit")]
    # 0 -> 13 spans more than 10 seconds; the streak must still continue.


def test_boundary_exactly_n_seconds_counts():
    detector = StreakDetector(10, 2, 3)
    assert detector.on_comment("UC1", at(0)) == (1, None)
    assert detector.on_comment("UC1", at(10)) == (2, "warning")
    assert detector.on_comment("UC1", at(20)) == (3, "limit")


def test_gap_greater_than_n_resets_and_allows_new_warning():
    detector = StreakDetector(10, 2, 3)
    assert detector.on_comment("UC1", at(0)) == (1, None)
    assert detector.on_comment("UC1", at(5)) == (2, "warning")
    assert detector.on_comment("UC1", at(15.001)) == (1, None)
    assert detector.on_comment("UC1", at(20)) == (2, "warning")


def test_per_user_isolation_and_no_repeated_actions_for_same_streak():
    detector = StreakDetector(10, 2, 3)
    detector.on_comment("UC1", at(0))
    assert detector.on_comment("UC2", at(1)) == (1, None)
    assert detector.on_comment("UC1", at(2)) == (2, "warning")
    assert detector.on_comment("UC2", at(3)) == (2, "warning")
    assert detector.on_comment("UC1", at(4)) == (3, "limit")
    assert detector.on_comment("UC1", at(5)) == (4, None)
    assert detector.on_comment("UC1", at(6)) == (5, None)


def test_out_of_order_message_resets():
    detector = StreakDetector(10, 2, 3)
    detector.on_comment("UC1", at(10))
    assert detector.on_comment("UC1", at(9)) == (1, None)


def test_default_and_staged_escalation():
    args = (3, 300, 1800)
    assert choose_restriction("permanent", 0, *args) == ("permanent_ban", None)
    assert choose_restriction("staged", 0, *args) == ("temporary_ban", 300)
    assert choose_restriction("staged", 1, *args) == ("temporary_ban", 1800)
    assert choose_restriction("staged", 2, *args) == ("permanent_ban", None)
