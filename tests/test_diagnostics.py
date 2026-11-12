import logging

from livechat_guard.diagnostics import _SensitiveDataFilter, log_path, safe_error_detail


def test_sensitive_strings_are_redacted_in_log():
    record = logging.makeLogRecord({
        "msg": "Request Authorization: Bearer abc123 access_token=sekret refresh_token=refreshvalue",
        "levelno": logging.WARNING,
        "levelname": "WARNING",
    })
    assert _SensitiveDataFilter().filter(record)
    message = record.getMessage()
    assert "abc123" not in message
    assert "sekret" not in message
    assert "refreshvalue" not in message
    assert "REDACTED" in message


def test_error_detail_redaction_and_length():
    error = RuntimeError("Bearer secret-token x" * 100)
    detail = safe_error_detail(error, max_chars=70)
    assert "secret-token" not in detail
    assert len(detail) < 100


def test_diagnostic_path_belongs_to_local_data(tmp_path):
    assert log_path(tmp_path) == tmp_path / "logs" / "livechat_guard.log"
