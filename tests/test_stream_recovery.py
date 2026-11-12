"""Connection policy tests with a fake monotonic clock: no network or time.sleep."""

from livechat_guard.stream_recovery import StreamRecovery


def test_short_success_is_not_counted_as_failure():
    p = StreamRecovery()
    for n in range(7):
        p.connection_started(n * 20)
        plan = p.on_disconnect(now=n * 20 + 2, lifetime=2,
                               responses=1, progress=True, rpc_error=False)
        assert p.empty_streak == 0
        assert p.error_streak == 0
        assert plan.delay_seconds >= 15
    assert p.early_closes == 7
    assert plan.delay_seconds >= 90  # Backoff even for productive repeated EOFs.


def test_empty_eof_exponential_backoff_and_pause():
    p = StreamRecovery()
    delays = []
    for n in range(6):
        t = n * 30
        p.connection_started(t)
        delays.append(p.on_disconnect(now=t + 1, lifetime=1, responses=0,
                                      progress=False, rpc_error=False).delay_seconds)
    assert delays[0] == 15
    assert delays[1] == 30
    assert delays[2] == 60
    assert delays[4] >= 300
    assert delays[5] >= 300


def test_transient_rpc_error_backoff():
    p = StreamRecovery()
    for i, delay in enumerate((10, 20, 40)):
        p.connection_started(i * 70)
        plan = p.on_disconnect(now=i * 70 + 31, lifetime=31,
                               responses=0, progress=False, rpc_error=True)
        assert plan.delay_seconds == delay
    assert p.error_streak == 3
    p.connection_started(250)
    p.on_disconnect(now=251, lifetime=1, responses=1, progress=True, rpc_error=True)
    assert p.error_streak == 0
    assert p.empty_streak == 0


def test_budget_is_enforced_per_rolling_10_min_window():
    p = StreamRecovery(max_starts=3, window_seconds=600)
    for t in (0, 20, 40):
        p.connection_started(t)
    plan = p.on_disconnect(now=41, lifetime=1, responses=0,
                           progress=False, rpc_error=False)
    assert plan.quiet_period is True
    assert plan.delay_seconds >= 560
    p.connection_started(601)
    plan = p.on_disconnect(now=602, lifetime=1, responses=1,
                           progress=True, rpc_error=False)
    assert plan.delay_seconds < 560


def test_policy_can_run_forever_without_5_eof_fatal_condition():
    p = StreamRecovery()
    for t in range(0, 3600, 150):
        p.connection_started(t)
        plan = p.on_disconnect(now=t + 1, lifetime=1, responses=0,
                               progress=False, rpc_error=False)
        assert plan.delay_seconds >= 0
    assert p.empty_streak == 24
    assert plan.delay_seconds >= 300


def test_long_lived_stream_resets_early_close_streak():
    p = StreamRecovery()
    p.connection_started(0)
    p.on_disconnect(now=10, lifetime=10, responses=1, progress=True, rpc_error=False)
    p.connection_started(20)
    p.on_disconnect(now=120, lifetime=100, responses=1, progress=True, rpc_error=False)
    assert p.early_closes == 0
