"""Validated user settings. OAuth tokens are NEVER stored here."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path


def data_dir() -> Path:
    """Per-user local data directory, not the Git working tree."""
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return root / "LiveChatGuard"
    if os.uname().sysname == "Darwin":
        return Path.home() / "Library" / "Application Support" / "LiveChatGuard"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "livechat-guard"


@dataclass
class Settings:
    client_secrets_path: str = ""
    window_seconds: int = 10
    minimum_poll_seconds: int = 120  # REST fallback interval, not detector window
    fetch_mode: str = "stream"  # stream (push / default) | poll (REST fallback)
    warning_count: int = 3
    limit_count: int = 5
    mode: str = "permanent"  # permanent | staged
    first_timeout_seconds: int = 300
    second_timeout_seconds: int = 1800
    permanent_after: int = 3  # 3rd effective violation in staged mode
    repeat_window_hours: int = 24
    chat_warning: bool = True
    exclude_moderators: bool = True
    exclude_members: bool = False
    excluded_channels: str = ""  # one channel ID per line
    dry_run: bool = True  # Safe on first launch: no API writes
    retention_days: int = 29  # YouTube API Data retention upper bound: 30 days

    def validate(self) -> None:
        if self.fetch_mode not in ("stream", "poll"):
            raise ValueError("不正なコメント取得方式です。")
        if not 5 <= self.minimum_poll_seconds <= 300:
            raise ValueError("API問い合わせ間隔は5～300秒で指定してください。")
        if not 1 <= self.window_seconds <= 3600:
            raise ValueError("判定秒数は1～3600で指定してください。")
        if not 2 <= self.warning_count < self.limit_count <= 100:
            raise ValueError("警告回数は2以上、制限回数より少なくしてください。")
        if self.mode not in ("permanent", "staged"):
            raise ValueError("不正な制限モードです。")
        if not 1 <= self.first_timeout_seconds <= 86400:
            raise ValueError("初回制限は1～86400秒で指定してください。")
        if not self.first_timeout_seconds <= self.second_timeout_seconds <= 86400:
            raise ValueError("2回目制限は初回以上かつ86400秒以下で指定してください。")
        if not 2 <= self.permanent_after <= 10:
            raise ValueError("永久BANまでの回数は2～10で指定してください。")
        if not 1 <= self.repeat_window_hours <= 720:
            raise ValueError("再犯判定期間は1～720時間で指定してください。")
        if not 1 <= self.retention_days <= 29:
            raise ValueError("ログ保存日数は1～29日にしてください。")

    def excluded_ids(self) -> set[str]:
        return {
            item.strip()
            for item in self.excluded_channels.splitlines()
            if item.strip() and not item.strip().startswith("#")
        }


def load_settings(path: Path | None = None) -> Settings:
    destination = path or data_dir() / "settings.json"
    if not destination.exists():
        return Settings()
    values = json.loads(destination.read_text(encoding="utf-8"))
    known = {field.name for field in fields(Settings)}
    config = Settings(**{key: value for key, value in values.items() if key in known})
    config.validate()
    return config


def save_settings(settings: Settings, path: Path | None = None) -> None:
    settings.validate()
    destination = path or data_dir() / "settings.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + ".tmp")
    temp.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, destination)
