"""Background QThreads. All API calls happen off the UI thread."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from threading import Event

import grpc

from PySide6.QtCore import QThread, Signal

from .auth import connect_google
from .ban_control import release_permanent_ban
from .api_errors import is_quota_exhausted, is_rate_limited, readable_api_error
from .moderation import StreakDetector, choose_restriction
from .cleanup import cleanup_observed_messages
from .settings import Settings
from .storage import History
from .youtube_api import YouTubeAPI
from .stream_grpc import LiveChatStream
from .diagnostics import get_logger, safe_error_detail
from .stream_recovery import StreamRecovery


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
            get_logger().exception("auth_failed")
            self.failed.emit(safe_error_detail(exc))


class BroadcastThread(QThread):
    completed = Signal(list)
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.completed.emit(YouTubeAPI().active_broadcasts())
        except Exception as exc:
            get_logger().exception("broadcast_fetch_failed")
            self.failed.emit(safe_error_detail(exc))


class BanLiftThread(QThread):
    """BAN removal happens outside the GUI thread, and only when monitoring is stopped."""

    completed = Signal(str, str)  # channel ID, detail
    failed = Signal(str)

    def __init__(self, db_path: Path, ban_record: dict):
        super().__init__()
        self.db_path = db_path
        self.ban_record = ban_record

    def run(self) -> None:
        db = History(self.db_path)
        record = self.ban_record
        try:
            api = YouTubeAPI()
            detail = release_permanent_ban(db, api, record)
            self.completed.emit(record["channel_id"], detail)
        except Exception as exc:
            get_logger().exception("ban_release_failed")
            self.failed.emit(safe_error_detail(exc))
        finally:
            db.close()


class MonitorThread(QThread):
    notification = Signal(dict)
    status = Signal(str)
    failed = Signal(str)
    notice = Signal(str)  # Non-fatal connection diagnostics shown in the dashboard.

    def __init__(self, config: Settings, db_path: Path, broadcast: dict):
        super().__init__()
        self.config = config
        self.db_path = db_path
        self.broadcast = broadcast
        self._stop_signal = Event()
        self._fatal_error = False
        self._logger = get_logger()
        self._stream = LiveChatStream()
        self._banned_channels: set[str] = set()  # only confirmed bans during this run
        self._cleanup_count: dict[str, int] = {}  # quota limit across backlogged messages too
        self._cleanup_disabled_channels: set[str] = set()  # stop repeated failing API calls
        self._cleanup_cap_notified: set[str] = set()

    def stop(self) -> None:
        self._logger.info("monitor_stop_requested")
        self._stop_signal.set()
        self._stream.cancel()  # Interrupt blocking gRPC receive promptly.

    def _fatal(self, message: str) -> None:
        self._fatal_error = True
        self._logger.error("monitor_fatal %s", message)
        self.failed.emit(message)

    def _notify(self, label: str, channel_id: str, name: str, detail: str) -> None:
        self.notification.emit({"label": label, "channel_id": channel_id,
                                "name": name, "detail": detail})

    def _action(self, db: History, api: YouTubeAPI, channel_id: str, name: str,
                kind: str, detail: str, duration: int | None = None,
                trigger_at: str | None = None) -> str:
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
            self._logger.warning("moderation_action_failed kind=%s %s", kind, safe_error_detail(exc))
            detail += f" / {readable_api_error(exc)}"
            if is_quota_exhausted(exc):
                # Avoid spending the remaining quota on further writes or reads.
                self._stop_signal.set()
                self._fatal("API割り当て超過により監視を停止します。BANは実行できませんでした。")
        db.add_action(bid, channel_id, name, kind, detail, outcome, ban_id,
                      trigger_at=trigger_at)
        labels = {"dry_run": "テストのみ・実行なし", "local_only": "ローカル記録のみ",
                  "success": "API成功", "failure": "API失敗"}
        self._notify(kind, channel_id, name, f"{detail} 【{labels.get(outcome, outcome)}】")
        if kind == "permanent_ban" and outcome == "success":
            self._banned_channels.add(channel_id)
            if self.config.delete_messages_after_permanent_ban:
                self._cleanup_messages(db, api, channel_id, name, trigger_at=trigger_at)
        return outcome

    def _cleanup_messages(self, db: History, api: YouTubeAPI, channel_id: str,
                          name: str, *, trigger_at: str | None = None) -> None:
        """Delete every *observed* message in this broadcast after confirmed BAN.

        Does not alter local comment text, which is kept for the audit/history UI.
        API quota: 20 units per attempted deletion. 0 limit means uncapped.
        """
        if (self.config.dry_run or self._stop_signal.is_set() or
                channel_id in self._cleanup_disabled_channels):
            return
        cap = self.config.max_cleanup_messages
        used = self._cleanup_count.get(channel_id, 0)
        remaining = max(0, cap - used) if cap else 0
        if cap and remaining == 0:
            if channel_id not in self._cleanup_cap_notified:
                self._cleanup_cap_notified.add(channel_id)
                self._notify("message_cleanup", channel_id, name,
                             f"削除件数の上限{cap}件に到達。残りは未削除です。")
            return
        result = cleanup_observed_messages(
            db, api, self.broadcast["id"], channel_id,
            remaining_limit=remaining, stop_signal=self._stop_signal,
        )
        self._cleanup_count[channel_id] = used + result.attempted
        if result.failures:
            # A systemic API failure must not cause one more DELETE per new chat message.
            self._cleanup_disabled_channels.add(channel_id)
        if result.quota_exhausted:
            self._stop_signal.set()
            self._fatal("コメント削除中にAPI割り当て超過。監視と追加削除を停止します。")
        used = self._cleanup_count[channel_id]
        success, missing, failures = result.successes, result.not_found, result.failures
        stopped, pending = result.stopped, result.pending
        # Include an explicit summary in GUI history/TXT even if some attempts failed.
        pending = len(db.cleanup_candidates(self.broadcast["id"], channel_id))
        summary = (f"削除成功 {success}件 / 既に存在しない {missing}件 / 失敗 {failures}件"
                   f" / 未処理 {pending}件（今回の削除API {result.attempted}回、推定 {result.attempted * 20}ユニット）")
        if stopped:
            summary += " / 中断（停止要求・APIエラー・上限等）"
        elif cap and used >= cap and pending:
            summary += f" / 設定上限 {cap}件に到達"
        outcome = ("success" if not failures and pending == 0 else
                   "partial" if success or missing else "failure")
        db.add_action(self.broadcast["id"], channel_id, name, "message_cleanup",
                      summary, outcome, trigger_at=trigger_at)
        self._notify("message_cleanup", channel_id, name, summary)

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
        # Stream pages can contain comments published just before BAN succeeded.
        # Remove those newly observed messages without issuing another BAN.
        if channel_id in self._banned_channels:
            if self.config.delete_messages_after_permanent_ban and not self.config.dry_run:
                self._cleanup_messages(db, api, channel_id, name, trigger_at=normalized)
            return
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

    def _run_stream(self, db: History, api: YouTubeAPI,
                    detector: StreakDetector, started: datetime) -> None:
        """Consume gRPC stream with bounded, explainable, quota-safe reconnects.

        Normal EOF and transient gRPC errors are handled separately. A short
        successful stream is NOT a failed connection, but both paths back off
        when repeated connects could waste quota. Only fatal API errors stop
        monitoring; repeated transient errors enter a longer cool-down.
        """
        chat_id = self.broadcast["chat_id"]
        page_token = None
        recovery = StreamRecovery()
        connection_no = 0
        mode = "テストモード・BANなし" if self.config.dry_run else "実制限有効"
        self._logger.info("monitor_stream_start mode=%s", "dry_run" if self.config.dry_run else "live")
        self.status.emit(f"リアルタイム受信に接続中（{mode}）")
        while not self._stop_signal.is_set():
            connection_no += 1
            connected_at = monotonic()
            recovery.connection_started(connected_at)
            response_count = 0
            item_count = 0
            progressed = False
            rpc_error = False
            grpc_code = "EOF"
            grpc_detail = ""
            self._logger.info("stream_connect attempt=%d resume=%s", connection_no,
                              "yes" if page_token else "no")
            try:
                for response in self._stream.responses(chat_id, page_token, self._stop_signal):
                    if self._stop_signal.is_set():
                        break
                    response_count += 1
                    if response_count == 1:
                        self.status.emit(f"リアルタイム受信中（{mode}）")
                    items = response.get("items", [])
                    item_count += len(items)
                    if items:
                        progressed = True
                    for raw in items:
                        if self._stop_signal.is_set():
                            break
                        try:
                            self._handle_message(db, api, detector, raw, started)
                        except Exception as exc:
                            self._logger.exception("message_processing_failed error_type=%s",
                                                   type(exc).__name__)
                            self.failed.emit(f"メッセージ処理エラー: {safe_error_detail(exc)}")
                    if self._stop_signal.is_set():
                        break
                    next_token = response.get("nextPageToken")
                    if next_token:
                        if next_token != page_token:
                            progressed = True
                        # Save only after processing this batch; reconnect from
                        # the last processed page instead of skipping messages.
                        page_token = next_token
                    if response.get("offlineAt"):
                        self._logger.info("stream_offline_at_received")
                        self.status.emit("配信終了を検知しました。")
                        return
            except grpc.RpcError as exc:
                if self._stop_signal.is_set():
                    return
                rpc_error = True
                code = exc.code()
                grpc_code = code.name if code else "UNKNOWN"
                grpc_detail = safe_error_detail(exc)
                # Do not dump credentials, full requests or comments.
                self._logger.warning("stream_rpc_error code=%s detail=%s", grpc_code, grpc_detail)
                if code == grpc.StatusCode.RESOURCE_EXHAUSTED:
                    self._fatal("streamList: RESOURCE_EXHAUSTED（クォータまたは頻度制限）。"
                                f" 詳細: {grpc_detail}。監視を停止しました。")
                    return
                if code in (grpc.StatusCode.PERMISSION_DENIED,
                            grpc.StatusCode.UNAUTHENTICATED,
                            grpc.StatusCode.INVALID_ARGUMENT,
                            grpc.StatusCode.FAILED_PRECONDITION,
                            grpc.StatusCode.NOT_FOUND):
                    self._fatal(f"streamListが拒否されました（{grpc_code}）: {grpc_detail}")
                    return
            except Exception as exc:
                if self._stop_signal.is_set():
                    return
                self._logger.exception("stream_unexpected_exception type=%s", type(exc).__name__)
                self._fatal(f"streamListを開始・受信できませんでした: {safe_error_detail(exc)}")
                return

            if self._stop_signal.is_set():
                return
            lifetime = monotonic() - connected_at
            plan = recovery.on_disconnect(now=monotonic(), lifetime=lifetime,
                                          responses=response_count, progress=progressed,
                                          rpc_error=rpc_error)
            self._logger.warning(
                "stream_disconnected attempt=%d code=%s duration_s=%.1f responses=%d "
                "items=%d progress=%s empty_streak=%d short_streak=%d retry_s=%.1f detail=%s",
                connection_no, grpc_code, lifetime, response_count, item_count,
                progressed, recovery.empty_streak, recovery.early_closes,
                plan.delay_seconds, grpc_detail[:350])
            detail = (f"streamList接続終了 [{grpc_code}] {lifetime:.1f}秒 / "
                      f"応答{response_count}件・コメント{item_count}件 / "
                      f"{plan.delay_seconds:.0f}秒後に再接続")
            self.status.emit(detail)
            # Every disconnection is in the rotating local log; show a subset
            # in the event table to avoid flooding a long-running stream.
            if rpc_error or plan.quiet_period or connection_no <= 2:
                self.notice.emit(detail + f"（{plan.reason}）")
            self._stop_signal.wait(plan.delay_seconds)
        self._logger.info("monitor_stream_stopped")

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
            # API publishedAt is often second-precision. Include this whole second.
            started = datetime.now(timezone.utc).replace(microsecond=0)
            if self.config.fetch_mode == "stream":
                self._run_stream(db, api, detector, started)
                self.status.emit("監視停止（エラー詳細はログ・イベントを参照）" if self._fatal_error
                                 else "監視停止")
                return
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
                        mode = "テストモード・BANなし" if self.config.dry_run else "実制限有効"
                        self.status.emit(f"定期取得で監視中（{mode}）：投稿時刻で過去のコメントを除外")
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
                    interval = max(int(response.get("pollingIntervalMillis", 5000)) / 1000,
                                   self.config.minimum_poll_seconds)
                    self._stop_signal.wait(interval)
                except Exception as exc:
                    if is_quota_exhausted(exc):
                        self._fatal(f"クォータ超過のため監視停止: {readable_api_error(exc)}")
                        break
                    errors += 1
                    if errors >= 5:
                        self._fatal(f"API接続に連続失敗したため停止: {readable_api_error(exc)}")
                        break
                    self._logger.warning("rest_poll_retry attempt=%d %s", errors, safe_error_detail(exc))
                    self.notice.emit(f"REST通信エラー（再試行 {errors}/5）: {readable_api_error(exc)}")
                    cooldown = min(60 * (2 ** (errors - 1)), 300) if is_rate_limited(exc) else min(2 ** errors * 5, 60)
                    self._stop_signal.wait(cooldown)
            self.status.emit("監視停止（エラー詳細はログ・イベントを参照）" if self._fatal_error
                             else "監視停止")
        except Exception as exc:
            self._logger.exception("monitor_unhandled_exception")
            self._fatal(f"監視を開始できませんでした: {safe_error_detail(exc)}")
            self.status.emit("監視停止（予期しないエラー）")
        finally:
            if db is not None:
                db.close()
