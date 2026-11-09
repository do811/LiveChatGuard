import json

import pytest

from livechat_guard.settings import Settings, load_settings, save_settings


def test_defaults():
    config = Settings()
    assert config.mode == "permanent"
    assert config.warning_count == 3
    assert config.limit_count == 5
    assert config.dry_run is True
    assert config.window_seconds == 10


def test_settings_roundtrip_and_no_token(tmp_path):
    target = tmp_path / "settings.json"
    original = Settings(excluded_channels="UC1\nUC2", mode="staged")
    save_settings(original, target)
    loaded = load_settings(target)
    assert loaded == original
    data = json.loads(target.read_text(encoding="utf-8"))
    assert "token" not in data
    assert loaded.excluded_ids() == {"UC1", "UC2"}


def test_invalid_threshold_rejected():
    with pytest.raises(ValueError):
        Settings(warning_count=5, limit_count=5).validate()
