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
    assert config.fetch_mode == "stream"
    assert config.minimum_poll_seconds == 120


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


def test_minimum_poll_setting_validation():
    from livechat_guard.settings import Settings
    config = Settings(minimum_poll_seconds=20)
    config.validate()
    import pytest
    with pytest.raises(ValueError):
        Settings(minimum_poll_seconds=1).validate()


def test_old_settings_migrate_to_stream(tmp_path):
    destination = tmp_path / "settings.json"
    destination.write_text('{"minimum_poll_seconds": 20, "mode": "permanent"}', encoding="utf-8")
    config = load_settings(destination)
    assert config.fetch_mode == "stream"
    assert config.minimum_poll_seconds == 20  # preserved for REST fallback


def test_invalid_fetch_mode_rejected():
    with pytest.raises(ValueError):
        Settings(fetch_mode="invalid").validate()
