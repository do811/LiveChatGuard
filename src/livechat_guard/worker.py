"""Background QThreads. All API calls happen off the UI thread."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, Signal

from .auth import connect_google
from .moderation import StreakDetector, choose_restriction
from .settings import Settings
from .storage import History
from .youtube_api import YouTubeAPI


def parse_timestamp(iso: str) -> datetime:
    result = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Published timestamp must include a timezone")
    return result.astimezone(timezone.utc)


class AuthThread(QThread):
    completed = Signal()
    failed = Signal(str)

    def __init__(self, client_path: str):
        super().__init__()
        self.client_path = client_path

    def run(self) -> None:
        try:
            connect_google(self.client_path)
            self.completed.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class BroadcastThread(QThread):
    completed = Signal(list)
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.completed.emit(YouTubeAPI().active_broadcasts())
        except Exception as exc:
            self.failed.emit(str(exc))


class MonitorThread(QThread):
    notification = Signal(dict)
    status = Signal(str)
    failed = Signal(str)

    def __init__(self, config: Settings, db_path: Path, broadcast: dict):
        super().__init__()
        self.config = config
        self.db_path = db_path
        self.broadcast = broadcast
        self._stop_signal = Event()

    def stop(self) -> None:
        self._stop_signal.set()

    def _notify(self, label: str, channel_id: str, name: str, detail: str) -> None:
        self.notification.emit({"label": label, "channel_id": channel_id,
                                "name": name, "detail": detail})

    def _action(self, db: History, api: YouTubeAPI, channel_id: str, name: str,
                kind: str, detail: str, duration: int | None = None,
                trigger_at: str | None = None) -> None:
        bid = self.broadcast["id"]
        chat_id = self.broadcast["chat_id"]
        outcome = ("dry_run" if self.config.dry_run else
                   "local_only" if kind == "warning" and not self.config.chat_warning else "success")
        ban_id = None
        try:
            if not self.config.dry_run:
                if kind == "warning" and self.config.chat_warning:
                    api.warn(chat_id, name)
                elif kind in ("temporary_ban", "permanent_ban"):
                    ban_id = api.ban(chat_id, channel_id, seconds=duration)
        except Exception as exc:
            outcome = "failure"
            detail += f" / APIエラー: {exc}"
        db.add_action(bid, channel_id, name, kind, detail, outcome, ban_id,
                      trigger_at=trigger_at)
        self._notify(kind, channel_id, name, f"{detail} [{outcome}]")

    def _handle_message(self, db: History, api: YouTubeAPI, detector: StreakDetector,
                        raw: dict, started: datetime) -> None:
        snippet = raw.get("snippet", {})
        if snippet.get("type") != "textMessageEvent":
            return
        channel = raw.get("authorDetails", {})
        channel_id = channel.get("channelId") or snippet.get("authorChannelId", "")
        message_id = raw.get("id", "")
        published = snippet.get("publishedAt", "")
        if not channel_id or not message_id or not published:
            return
        stamp = parse_timestamp(published)
        if stamp < started:  # Never ban based on pre-monitor history.
            return
        name = channel.get("displayName", "不明")
        body = snippet.get("textMessageDetails", {}).get("messageText")
        if body is None:
            body = snippet.get("displayMessage", "")
        normalized = stamp.isoformat(timespec="microseconds")
        if not db.add_message(message_id, self.broadcast["id"], channel_id, name, body, normalized):
            return  # Prevent duplicate messages on reconnect / repeated pages.
        self._notify("message", channel_id, name, body)
        if (channel.get("isChatOwner") or
            (self.config.exclude_moderators and channel.get("isChatModerator")) or
            (self.config.exclude_members and channel.get("isChatSponsor")) or
            channel_id in self.config.excluded_ids()):
            return
        streak, event = detector.on_comment(channel_id, stamp)
        if event == "warning":
            self._action(db, api, channel_id, name, "warning",
                         f"{self.config.window_seconds}秒以内の連続投稿 {streak}回",
                         trigger_at=normalized)
        elif event == "limit":
            past = (db.recent_temporary_bans(channel_id, self.config.repeat_window_hours)
                    if self.config.mode == "staged" else 0)
            kind, duration = choose_restriction(
                self.config.mode, past, self.config.permanent_after,
                self.config.first_timeout_seconds, self.config.second_timeout_seconds
            )
            self._action(db, api, channel_id, name, kind,
                         f"{self.config.window_seconds}秒以内の連続投稿 {streak}回", duration,
                         trigger_at=normalized)

    def run(self) -> None:
        db = None
        try:
            api = YouTubeAPI()
            db = History(self.db_path)
            db.purge_expired(self.config.retention_days)
            detector = StreakDetector(
                self.config.window_seconds, self.config.warning_count, self.config.limit_count
            )
            chat_id = self.broadcast["chat_id"]
            started = datetime.now(timezone.utc)
            page_token = None
            first_page = True
            errors = 0
            while not self._stop_signal.is_set():
                try:
                    response = api.list_messages(chat_id, page_token)
                    errors = 0
                    page_token = response.get("nextPageToken", page_token)
                    if first_page:
                        first_page = False
                        self.status.emit("接続済み：過去のコメントをスキップして監視開始")
                    else:
                        for raw in response.get("items", []):
                            if self._stop_signal.is_set():
                                break
                            try:
                                self._handle_message(db, api, detector, raw, started)
                            except Exception as exc:
                                self.failed.emit(f"メッセージ処理エラー: {exc}")
                    if response.get("offlineAt"):
                        self.status.emit("配信が終了しました。")
                        break
                    # Never poll more often than YouTube's requested interval.
                    interval = max(int(response.get("pollingIntervalMillis", 5000)) / 1000, 1)
                    self._stop_signal.wait(interval)
                except Exception as exc:
                    errors += 1
                    if errors >= 5:
                        self.failed.emit(f"API接続に連続失敗したため停止: {exc}")
                        break
                    self.failed.emit(f"API通信エラー（再試行 {errors}/5）: {exc}")
                    self._stop_signal.wait(min(2 ** errors * 5, 60))
            self.status.emit("監視停止")
        except Exception as exc:
            self.failed.emit(f"監視を開始できませんでした: {exc}")
            self.status.emit("監視停止")
        finally:
            if db is not None:
                db.close()
