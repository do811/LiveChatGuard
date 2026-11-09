import json

from livechat_guard.api_errors import error_reason, is_quota_exhausted, is_rate_limited, readable_api_error


class FakeHttpError(Exception):
    def __init__(self, reason: str):
        self.content = json.dumps({"error": {"errors": [{"reason": reason}]}}).encode("utf-8")
        super().__init__("403 API error")


def test_quota_exceeded_stops_polling():
    for name in ("quotaExceeded", "dailyLimitExceeded"):
        exc = FakeHttpError(name)
        assert is_quota_exhausted(exc)
        assert not is_rate_limited(exc)
        assert name in readable_api_error(exc)


def test_rate_limit_is_retryable():
    exc = FakeHttpError("rateLimitExceeded")
    assert is_rate_limited(exc)
    assert not is_quota_exhausted(exc)


def test_unknown_error_retains_reason():
    exc = FakeHttpError("insufficientPermissions")
    assert error_reason(exc) == "insufficientPermissions"
    assert not is_quota_exhausted(exc)
