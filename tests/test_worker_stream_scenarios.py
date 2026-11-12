"""Offline end-to-end *worker loop* tests using fake Qt and gRPC streams.

The production GUI dependencies are deliberately not imported. Only the
worker orchestration is exercised; these tests never contact YouTube.
"""

import importlib.util
import logging
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import grpc


class _Signal:
    def __init__(self, *_args):
        self.values = []

    def emit(self, *args):
        self.values.append(args)


class _QThread:
    def __init__(self):
        pass


class _FakeStop:
    def __init__(self):
        self.stopped = False
        self.waited = []

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, delay):
        self.waited.append(delay)
        return self.stopped


class _FakeStream:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.requests = []

    def cancel(self):
        pass

    def responses(self, chat_id, page_token, stop):
        self.requests.append((chat_id, page_token))
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        yield from outcome


class _RpcError(grpc.RpcError):
    def __init__(self, code, detail="simulated error"):
        self._code = code
        self._detail = detail

    def code(self):
        return self._code

    def details(self):
        return self._detail

    def __str__(self):
        return self._detail


def _load_worker(monkeypatch):
    """Import the actual worker with minimal fake platform/network modules."""
    qt = types.ModuleType("PySide6.QtCore")
    qt.QThread = _QThread
    qt.Signal = _Signal
    pyqt = types.ModuleType("PySide6")
    pyqt.QtCore = qt
    monkeypatch.setitem(sys.modules, "PySide6", pyqt)
    monkeypatch.setitem(sys.modules, "PySide6.QtCore", qt)

    stubs = {
        "livechat_guard.auth": {"connect_google": lambda p: None},
        "livechat_guard.ban_control": {"release_permanent_ban": lambda *a: None},
        "livechat_guard.api_errors": {
            "is_quota_exhausted": lambda exc: False,
            "is_rate_limited": lambda exc: False,
            "readable_api_error": lambda exc: str(exc),
        },
        "livechat_guard.cleanup": {"cleanup_observed_messages": lambda *a, **k: None},
        "livechat_guard.youtube_api": {"YouTubeAPI": object},
    }
    for module_name, attributes in stubs.items():
        stub = types.ModuleType(module_name)
        for name, value in attributes.items():
            setattr(stub, name, value)
        monkeypatch.setitem(sys.modules, module_name, stub)

    file = Path(__file__).parents[1] / "src" / "livechat_guard" / "worker.py"
    spec = importlib.util.spec_from_file_location("livechat_guard._test_worker", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "get_logger", lambda: logging.getLogger("test-worker"))
    clock = iter(range(1_000_000))
    monkeypatch.setattr(module, "monotonic", lambda: next(clock))
    return module


def _monitor(module, outcomes):
    from livechat_guard.settings import Settings
    worker = module.MonitorThread(Settings(), Path("fake-sqlite-not-accessed"),
                                  {"chat_id": "CHAT", "id": "BROADCAST"})
    worker._stream = _FakeStream(outcomes)
    worker._stop_signal = _FakeStop()
    observed = []
    worker._handle_message = lambda *_args: observed.append("item")
    return worker, observed


def test_repeated_productive_short_eof_does_not_stop_monitoring(monkeypatch):
    worker_module = _load_worker(monkeypatch)
    outcomes = [iter([{"items": [{"id": str(i)}], "nextPageToken": str(i)}])
                for i in range(1, 8)]
    outcomes.append(iter([{"items": [], "offlineAt": "2026-11-11T00:00:00Z"}]))
    worker, observed = _monitor(worker_module, outcomes)
    worker._run_stream(None, None, None, datetime.now(timezone.utc))
    assert len(observed) == 7
    assert len(worker._stream.requests) == 8
    assert worker._stream.requests[1][1] == "1"
    assert worker._stream.requests[-1][1] == "7"
    assert worker.failed.values == []
    assert len(worker._stop_signal.waited) == 7
    assert max(worker._stop_signal.waited) >= 90  # churn protection


def test_repeated_empty_eof_enters_protective_wait_instead_of_fatal(monkeypatch):
    worker_module = _load_worker(monkeypatch)
    outcomes = [iter([]) for _ in range(9)]
    outcomes.append(iter([{"items": [], "offlineAt": "2026-11-11T00:00:00Z"}]))
    worker, _ = _monitor(worker_module, outcomes)
    worker._run_stream(None, None, None, datetime.now(timezone.utc))
    assert len(worker._stream.requests) == 10
    assert worker.failed.values == []
    assert max(worker._stop_signal.waited) >= 300
    assert any("接続" in args[0] for args in worker.notice.values)


def test_transient_rpc_error_is_logged_and_retried(monkeypatch):
    worker_module = _load_worker(monkeypatch)
    outcomes = [_RpcError(grpc.StatusCode.UNAVAILABLE),
                iter([{"offlineAt": "2026-11-11T00:00:00Z"}])]
    worker, _ = _monitor(worker_module, outcomes)
    worker._run_stream(None, None, None, datetime.now(timezone.utc))
    assert len(worker._stream.requests) == 2
    assert worker.failed.values == []
    assert any("UNAVAILABLE" in args[0] for args in worker.notice.values)


def test_resource_exhausted_stops_without_retry(monkeypatch):
    worker_module = _load_worker(monkeypatch)
    worker, _ = _monitor(worker_module,
                         [_RpcError(grpc.StatusCode.RESOURCE_EXHAUSTED,
                                    "quotaExceeded")])
    worker._run_stream(None, None, None, datetime.now(timezone.utc))
    assert len(worker._stream.requests) == 1
    assert worker._fatal_error
    assert "RESOURCE_EXHAUSTED" in worker.failed.values[0][0]


def test_auth_error_stops_without_retry(monkeypatch):
    worker_module = _load_worker(monkeypatch)
    worker, _ = _monitor(worker_module, [_RpcError(grpc.StatusCode.UNAUTHENTICATED)])
    worker._run_stream(None, None, None, datetime.now(timezone.utc))
    assert len(worker._stream.requests) == 1
    assert worker._fatal_error
    assert "UNAUTHENTICATED" in worker.failed.values[0][0]
