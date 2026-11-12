"""Japanese PySide6 desktop interface."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSpinBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .auth import disconnect_google
from .diagnostics import get_logger, log_path, safe_error_detail
from .quota import QuotaLedger, oauth_project_key
from .settings import Settings, data_dir, load_settings, save_settings
from .storage import History, user_txt
from .worker import AuthThread, BanLiftThread, BroadcastThread, MonitorThread


def spin(minimum: int, maximum: int, value: int, suffix: str = "") -> QSpinBox:
    item = QSpinBox()
    item.setRange(minimum, maximum)
    item.setValue(value)
    if suffix:
        item.setSuffix(suffix)
    return item


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.base = data_dir()
        self.base.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base / "history.sqlite3"
        self.saved = load_settings()
        with_history = History(self.db_path)
        with_history.purge_expired(self.saved.retention_days)
        with_history.close()
        self.monitor: MonitorThread | None = None
        self.auth_job: AuthThread | None = None
        self.broadcast_job: BroadcastThread | None = None
        self.unban_job: BanLiftThread | None = None
        self.broadcasts: list[dict] = []
        self.selected_channel_id = ""

        self.setWindowTitle("LiveChat Guard v0.4.0")
        self.resize(1050, 740)
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.addTab(self._dashboard(), "監視ダッシュボード")
        self.tabs.addTab(self._settings(), "監視ルール・接続設定")
        self.tabs.addTab(self._history_tab(), "ユーザー別履歴")
        self.statusBar().showMessage(f"データ保存先: {self.base}")
        self._refresh_history_users()
        self._refresh_quota()
        self.timer = QTimer(self)
        self.timer.setInterval(2500)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _dashboard(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("YouTube Live コメント監視"))
        self.connection = QLabel("Google認証後に配信一覧を取得してください。")
        layout.addWidget(self.connection)
        row = QHBoxLayout()
        self.fetch_button = QPushButton("自分の配信一覧を取得")
        self.fetch_button.clicked.connect(self._fetch_broadcasts)
        row.addWidget(self.fetch_button)
        self.broadcast_combo = QComboBox()
        self.broadcast_combo.setMinimumWidth(350)
        row.addWidget(self.broadcast_combo, stretch=1)
        layout.addLayout(row)

        actions = QHBoxLayout()
        self.start_button = QPushButton("▶ 監視開始")
        self.start_button.clicked.connect(self._start)
        self.stop_button = QPushButton("■ 監視停止")
        self.stop_button.clicked.connect(self._stop)
        self.stop_button.setEnabled(False)
        actions.addWidget(self.start_button)
        actions.addWidget(self.stop_button)
        layout.addLayout(actions)
        self.monitor_state = QLabel("停止中")
        layout.addWidget(self.monitor_state)
        diagnostic_row = QHBoxLayout()
        diagnostic_button = QPushButton("障害ログの保存フォルダを開く")
        diagnostic_button.clicked.connect(self._open_diagnostic_logs)
        diagnostic_row.addWidget(diagnostic_button)
        diagnostic_row.addWidget(QLabel("APIエラー・切断・再接続をローカルに記録します（認証トークンやコメント本文は記録しません）"))
        layout.addLayout(diagnostic_row)

        quota_group = QGroupBox("YouTube API クォータ（このアプリの推定値）")
        quota_layout = QVBoxLayout(quota_group)
        self.quota_used_label = QLabel("集計中…")
        self.quota_remaining_label = QLabel("")
        self.quota_bar = QProgressBar()
        self.quota_bar.setTextVisible(False)
        quota_layout.addWidget(self.quota_used_label)
        quota_layout.addWidget(self.quota_remaining_label)
        quota_layout.addWidget(self.quota_bar)
        self.quota_breakdown = QLabel("")
        self.quota_breakdown.setWordWrap(True)
        quota_layout.addWidget(self.quota_breakdown)
        quota_buttons = QHBoxLayout()
        quota_refresh = QPushButton("推定使用量を更新")
        quota_refresh.clicked.connect(self._refresh_quota)
        cloud_button = QPushButton("Google Cloudで正確な使用量を確認")
        cloud_button.clicked.connect(self._open_cloud_quota)
        quota_buttons.addWidget(quota_refresh)
        quota_buttons.addWidget(cloud_button)
        quota_layout.addLayout(quota_buttons)
        quota_note = QLabel(
            "※ このPCのv0.3.0以降のAPIリクエストを記録した推定値です。"
            "別のアプリ・Google Cloud Console・旧バージョンの消費は含まれず、実残量とは異なります。"
            "日次集計は太平洋時間0時に切り替わります。")
        quota_note.setWordWrap(True)
        quota_layout.addWidget(quota_note)
        layout.addWidget(quota_group)
        self.events = QTableWidget(0, 3)
        self.events.setHorizontalHeaderLabels(["イベント", "ユーザー", "内容・API結果"])
        self.events.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.events.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.events)
        note = QLabel("※ テストモードではBAN・BAN解除・警告投稿・過去コメント削除を実行しません。\n"
                      "※ 永久BAN成功後は、この配信で取得済みの対象者のコメントを個別削除できます（1件20ユニット）。\n"
                      "※ クォータ超過時は追加削除と監視を停止します。")
        note.setWordWrap(True)
        layout.addWidget(note)
        return page

    def _settings(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.seconds = spin(1, 3600, self.saved.window_seconds, " 秒")
        self.fetch_mode = QComboBox()
        self.fetch_mode.addItem("リアルタイム受信（推奨・streamList）", "stream")
        self.fetch_mode.addItem("定期取得（REST・予備モード）", "poll")
        self.fetch_mode.setCurrentIndex(0 if self.saved.fetch_mode == "stream" else 1)
        self.poll_seconds = spin(5, 300, self.saved.minimum_poll_seconds, " 秒")
        self.warn = spin(2, 99, self.saved.warning_count, " 回")
        self.limit = spin(3, 100, self.saved.limit_count, " 回")
        self.mode = QComboBox()
        self.mode.addItem("警告 → 永久BAN【標準】", "permanent")
        self.mode.addItem("警告 → 一時制限 → 再犯時の制限強化", "staged")
        self.mode.setCurrentIndex(0 if self.saved.mode == "permanent" else 1)
        self.first_duration = spin(1, 86400, self.saved.first_timeout_seconds, " 秒")
        self.second_duration = spin(1, 86400, self.saved.second_timeout_seconds, " 秒")
        self.permanent_after = spin(2, 10, self.saved.permanent_after, " 回目")
        self.repeat_hours = spin(1, 720, self.saved.repeat_window_hours, " 時間")
        self.retention = spin(1, 29, self.saved.retention_days, " 日")
        self.quota_limit_spin = spin(1, 100000000, self.saved.daily_quota_limit, " ユニット")
        self.cleanup_cap = spin(0, 10000, self.saved.max_cleanup_messages, " 件")
        self.cleanup_cap.setSpecialValueText("0 = 全件（上限なし）")
        form.addRow("Google Cloudの1日クォータ上限", self.quota_limit_spin)
        form.addRow("連投判定の最大コメント間隔", self.seconds)
        form.addRow("コメント取得方式", self.fetch_mode)
        form.addRow("定期取得モードの最短間隔", self.poll_seconds)
        form.addRow("警告発動までの連投回数", self.warn)
        form.addRow("制限発動までの連投回数", self.limit)
        form.addRow("処理モード", self.mode)
        form.addRow("初回一時制限", self.first_duration)
        form.addRow("2回目以降の一時制限", self.second_duration)
        form.addRow("何回目の違反で永久BAN", self.permanent_after)
        form.addRow("再犯の判定期間", self.repeat_hours)
        form.addRow("履歴自動削除までの期間", self.retention)
        form.addRow("BAN後に削除するコメント件数の上限", self.cleanup_cap)
        layout.addLayout(form)
        self.chat_warning = QCheckBox("警告時にYouTubeチャットへ警告文を送信")
        self.chat_warning.setChecked(self.saved.chat_warning)
        self.auto_cleanup = QCheckBox("永久BAN成功後、取得済みの対象者のコメントをYouTubeから削除（20ユニット/件）")
        self.auto_cleanup.setChecked(self.saved.delete_messages_after_permanent_ban)
        self.exclude_mod = QCheckBox("配信者・モデレーターは判定から除外")
        self.exclude_mod.setChecked(self.saved.exclude_moderators)
        self.exclude_members = QCheckBox("メンバーシップ加入者を判定から除外")
        self.exclude_members.setChecked(self.saved.exclude_members)
        self.dry_run = QCheckBox("テストモード（警告送信・BAN・BAN解除・コメント削除を実行しない）")
        self.dry_run.setChecked(self.saved.dry_run)
        self.dry_run.toggled.connect(self._update_unban_button)
        for checkbox in (self.chat_warning, self.auto_cleanup, self.exclude_mod, self.exclude_members, self.dry_run):
            layout.addWidget(checkbox)

        exempt_row = QHBoxLayout()
        exempt_row.addWidget(QLabel("除外するチャンネルID（1行1件）"))
        self.exclusions = QPlainTextEdit(self.saved.excluded_channels)
        self.exclusions.setMaximumHeight(60)
        exempt_row.addWidget(self.exclusions, stretch=1)
        layout.addLayout(exempt_row)

        oauth = QGroupBox("Google OAuth 接続（APIキーではBANできません）")
        oauth_layout = QVBoxLayout(oauth)
        client_row = QHBoxLayout()
        self.client_path = QLineEdit(self.saved.client_secrets_path)
        self.client_path.setPlaceholderText("Google CloudのデスクトップOAuthクライアントJSONのパス")
        browse = QPushButton("参照")
        browse.clicked.connect(self._browse_client)
        client_row.addWidget(self.client_path, stretch=1)
        client_row.addWidget(browse)
        oauth_layout.addLayout(client_row)
        buttons = QHBoxLayout()
        self.login_button = QPushButton("Googleアカウントで認証")
        self.login_button.clicked.connect(self._login)
        disconnect = QPushButton("保存した認証を削除")
        disconnect.clicked.connect(self._disconnect)
        buttons.addWidget(self.login_button)
        buttons.addWidget(disconnect)
        oauth_layout.addLayout(buttons)
        layout.addWidget(oauth)
        save = QPushButton("設定を保存")
        save.clicked.connect(self._save_settings)
        layout.addWidget(save)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll

    def _history_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("ユーザー名・チャンネルIDで検索")
        self.search_box.textChanged.connect(self._refresh_history_users)
        self.only_actions = QCheckBox("警告・BAN履歴あり")
        self.only_actions.stateChanged.connect(self._refresh_history_users)
        row.addWidget(self.search_box, stretch=1)
        row.addWidget(self.only_actions)
        layout.addLayout(row)

        self.users = QTableWidget(0, 4)
        self.users.setHorizontalHeaderLabels(["ユーザー名", "チャンネルID", "コメント", "処理履歴"])
        self.users.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.users.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.users.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.users.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.users.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.users.itemSelectionChanged.connect(self._show_history)
        layout.addWidget(self.users, stretch=2)

        self.history_details = QPlainTextEdit()
        self.history_details.setReadOnly(True)
        layout.addWidget(self.history_details, stretch=3)
        actions = QHBoxLayout()
        refresh = QPushButton("履歴を再読込")
        refresh.clicked.connect(self._refresh_history_users)
        export = QPushButton("選択ユーザーの履歴をTXTで保存")
        export.clicked.connect(self._export_user)
        delete = QPushButton("選択ユーザーのローカル履歴を削除")
        delete.clicked.connect(self._delete_user)
        self.unban_button = QPushButton("選択ユーザーの永久BANを解除")
        self.unban_button.setEnabled(False)
        self.unban_button.clicked.connect(self._release_ban)
        actions.addWidget(refresh)
        actions.addWidget(export)
        actions.addWidget(self.unban_button)
        actions.addWidget(delete)
        layout.addLayout(actions)
        unban_note = QLabel("※ BAN解除はAPI操作（200ユニット）です。監視停止中かつテストモードOFFのときのみ可能です。"
                            "解除しても削除済みコメントは復元されません。")
        unban_note.setWordWrap(True)
        layout.addWidget(unban_note)
        layout.addWidget(QLabel("※ 履歴削除はこのPC内の記録のみです。YouTube側のコメントやBANは変化しません。"))
        return page

    def _collect(self) -> Settings:
        result = Settings(
            client_secrets_path=self.client_path.text().strip(),
            window_seconds=self.seconds.value(),
            minimum_poll_seconds=self.poll_seconds.value(), fetch_mode=self.fetch_mode.currentData(),
            warning_count=self.warn.value(),
            limit_count=self.limit.value(), mode=self.mode.currentData(),
            first_timeout_seconds=self.first_duration.value(),
            second_timeout_seconds=self.second_duration.value(),
            permanent_after=self.permanent_after.value(),
            repeat_window_hours=self.repeat_hours.value(),
            chat_warning=self.chat_warning.isChecked(),
            delete_messages_after_permanent_ban=self.auto_cleanup.isChecked(),
            max_cleanup_messages=self.cleanup_cap.value(),
            exclude_moderators=self.exclude_mod.isChecked(),
            exclude_members=self.exclude_members.isChecked(),
            excluded_channels=self.exclusions.toPlainText().strip(),
            dry_run=self.dry_run.isChecked(), retention_days=self.retention.value(),
            daily_quota_limit=self.quota_limit_spin.value(),
        )
        result.validate()
        return result

    def _save_settings(self) -> bool:
        try:
            self.saved = self._collect()
            save_settings(self.saved)
            self._refresh_quota()
            self._update_unban_button()
            self.statusBar().showMessage("設定を保存しました。監視中の場合は次の監視開始時から反映されます。", 7000)
            return True
        except Exception as exc:
            QMessageBox.warning(self, "設定エラー", str(exc))
            return False

    def _refresh_quota(self) -> None:
        """No network requests are made when refreshing this counter."""
        try:
            project = oauth_project_key(self.saved.client_secrets_path)
            ledger = QuotaLedger(project=project)
            summary = ledger.snapshot(self.saved.daily_quota_limit)
            self.quota_used_label.setText(
                f"本日のアプリ内推定消費：{summary.used:,} / {summary.limit:,} ユニット "
                f"（{summary.calls:,} 回、PT {summary.date_pt}）")
            if summary.quota_exceeded:
                self.quota_remaining_label.setText(
                    "APIから quotaExceeded を検知：実際の残量は不明です。Google Cloudで確認してください。")
            else:
                self.quota_remaining_label.setText(
                    f"このアプリの記録だけから計算した残量目安：{summary.estimated_remaining:,} ユニット"
                )
            self.quota_bar.setRange(0, summary.limit)
            self.quota_bar.setValue(min(summary.used, summary.limit))
            methods = ledger.breakdown()
            if methods:
                self.quota_breakdown.setText(
                    "本日の内訳：" + " / ".join(
                        f"{method} {units:,}（{calls:,}回）" for method, calls, units in methods))
            else:
                self.quota_breakdown.setText("このバージョンで記録したAPI呼び出しはまだありません。")
        except Exception as exc:
            self.quota_used_label.setText(f"ローカルクォータ集計エラー: {exc}")
            self.quota_remaining_label.setText("Google Cloudから直接取得するには管理画面を開いてください。")
            self.quota_breakdown.clear()

    def _open_cloud_quota(self) -> None:
        project = oauth_project_key(self.saved.client_secrets_path)
        url = "https://console.cloud.google.com/apis/api/youtube.googleapis.com/quotas"
        if project != "unknown-project" and not project.startswith("client-"):
            url += "?project=" + quote(project, safe="")
        QDesktopServices.openUrl(QUrl(url))

    def _browse_client(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "OAuthクライアントJSONを選択", "", "JSON (*.json)")
        if path:
            self.client_path.setText(path)

    def _login(self) -> None:
        if not self._save_settings():
            return
        if self.auth_job is not None and self.auth_job.isRunning():
            return
        self.login_button.setEnabled(False)
        self.auth_job = AuthThread(self.saved.client_secrets_path)
        self.auth_job.completed.connect(lambda: self.connection.setText("認証成功。配信一覧を取得してください。"))
        self.auth_job.failed.connect(lambda error: QMessageBox.warning(self, "Google認証失敗", error))
        self.auth_job.finished.connect(lambda: self.login_button.setEnabled(True))
        self.auth_job.start()

    def _disconnect(self) -> None:
        if (self.monitor is not None and self.monitor.isRunning()) or (
                self.unban_job is not None and self.unban_job.isRunning()):
            QMessageBox.warning(self, "API操作中", "監視・BAN解除が終わってから認証を削除してください。")
            return
        try:
            disconnect_google()
            self.connection.setText("保存した認証を削除しました。")
            self.broadcast_combo.clear()
            self.broadcasts = []
        except Exception as exc:
            QMessageBox.warning(self, "認証削除失敗", str(exc))

    def _fetch_broadcasts(self) -> None:
        if self.broadcast_job is not None and self.broadcast_job.isRunning():
            return
        self.fetch_button.setEnabled(False)
        self.connection.setText("配信一覧を取得中…")
        self.broadcast_job = BroadcastThread()
        self.broadcast_job.completed.connect(self._set_broadcasts)
        self.broadcast_job.failed.connect(lambda error: self.connection.setText(f"取得失敗: {error}"))
        self.broadcast_job.finished.connect(lambda: self.fetch_button.setEnabled(True))
        self.broadcast_job.start()

    def _set_broadcasts(self, broadcasts: list[dict]) -> None:
        self.broadcasts = broadcasts
        self.broadcast_combo.clear()
        for stream in broadcasts:
            self.broadcast_combo.addItem(f"{stream['title']} ({stream['id']})", stream)
        self.connection.setText(f"ライブ配信が {len(broadcasts)} 件見つかりました。"
                                if broadcasts else "ライブ配信が見つかりません。YouTube側の配信状態をご確認ください。")

    def _start(self) -> None:
        if self.monitor is not None and self.monitor.isRunning():
            return
        if self.unban_job is not None and self.unban_job.isRunning():
            QMessageBox.information(self, "BAN解除中", "BAN解除の終了後に監視を開始してください。")
            return
        if not self._save_settings():
            return
        broadcast = self.broadcast_combo.currentData()
        if not isinstance(broadcast, dict):
            QMessageBox.warning(self, "配信未選択", "先に配信一覧を取得して対象の配信を選択してください。")
            return
        if not self.saved.dry_run:
            answer = QMessageBox.question(
                self, "実制限の確認",
                "テストモードがOFFです。違反が発生すると実際にYouTubeへ警告・BAN操作を送信します。\n"
                + ("永久BAN成功後は記録済みのコメントをYouTubeから個別削除します。\n"
                   + f"削除上限：{'全件（無制限）' if self.saved.max_cleanup_messages == 0 else str(self.saved.max_cleanup_messages) + '件'}。"
                   + "1件20ユニットを消費し、元に戻せません。\n"
                   if self.saved.delete_messages_after_permanent_ban else "")
                + f"モード: {self.mode.currentText()}\n続行しますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.monitor = MonitorThread(self.saved, self.db_path, broadcast)
        self.monitor.notification.connect(self._receive_event)
        self.monitor.status.connect(self.monitor_state.setText)
        self.monitor.failed.connect(self._worker_error)
        self.monitor.notice.connect(self._worker_notice)
        self.monitor.finished.connect(self._monitor_finished)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.fetch_button.setEnabled(False)
        self.monitor_state.setText("接続中…" + ("（テストモード）" if self.saved.dry_run else "（実制限有効）"))
        self.monitor.start()
        self._update_unban_button()

    def _stop(self) -> None:
        if self.monitor is not None and self.monitor.isRunning():
            self.monitor.stop()
            self.monitor_state.setText("停止処理中…")
            self.stop_button.setEnabled(False)

    def _monitor_finished(self) -> None:
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.fetch_button.setEnabled(True)
        self._update_unban_button()

    def _open_diagnostic_logs(self) -> None:
        folder = log_path().parent
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _worker_notice(self, detail: str) -> None:
        self._receive_event({"label": "接続通知", "name": "システム", "detail": detail})

    def _worker_error(self, error: str) -> None:
        self.statusBar().showMessage(error, 16000)
        self._receive_event({"label": "error", "name": "システム", "detail": error})

    def _receive_event(self, event: dict) -> None:
        row = 0
        self.events.insertRow(row)
        for column, value in enumerate((event.get("label", ""), event.get("name", ""),
                                        event.get("detail", ""))):
            self.events.setItem(row, column, QTableWidgetItem(str(value)))
        if self.events.rowCount() > 300:
            self.events.removeRow(300)

    def _tick(self) -> None:
        self._refresh_quota()
        if self.tabs.currentIndex() == 2:
            self._refresh_history_users()

    def _refresh_history_users(self) -> None:
        current = self.selected_channel_id
        db = History(self.db_path)
        try:
            results = db.recent_users(self.search_box.text(), self.only_actions.isChecked())
        finally:
            db.close()
        self.users.blockSignals(True)
        self.users.setRowCount(0)
        selected_row = -1
        for number, item in enumerate(results):
            self.users.insertRow(number)
            data = (item["display_name"], item["channel_id"],
                    str(item["messages"]), str(item["actions"]))
            for i, value in enumerate(data):
                self.users.setItem(number, i, QTableWidgetItem(value))
            if item["channel_id"] == current:
                selected_row = number
        if selected_row >= 0:
            self.users.selectRow(selected_row)
        self.users.blockSignals(False)
        if selected_row == -1:
            self.selected_channel_id = ""
            self.history_details.clear()
            self.unban_button.setEnabled(False)
        else:
            self._show_history()

    def _show_history(self) -> None:
        selected = self.users.selectedItems()
        if not selected:
            return
        channel_id = self.users.item(selected[0].row(), 1).text()
        self.selected_channel_id = channel_id
        db = History(self.db_path)
        try:
            text = user_txt(channel_id, db.history_for_user(channel_id))
        finally:
            db.close()
        if text != self.history_details.toPlainText():
            self.history_details.setPlainText(text)
        self._update_unban_button()

    def _update_unban_button(self) -> None:
        if not self.selected_channel_id:
            self.unban_button.setEnabled(False)
            return
        if ((self.monitor is not None and self.monitor.isRunning()) or
                (self.unban_job is not None and self.unban_job.isRunning())):
            self.unban_button.setEnabled(False)
            return
        db = History(self.db_path)
        try:
            active = db.active_permanent_bans(self.selected_channel_id)
        finally:
            db.close()
        can_act = (not self.saved.dry_run and not self.dry_run.isChecked())
        self.unban_button.setEnabled(bool(active) and can_act)
        self.unban_button.setText(
            f"永久BANを解除（{len(active)}件）" if active else "解除可能な永久BANなし")
        if active and not can_act:
            self.unban_button.setToolTip("監視ルール・接続設定でテストモードをOFFにして設定を保存してください。")
        else:
            self.unban_button.setToolTip("")

    def _release_ban(self) -> None:
        if not self.selected_channel_id:
            return
        if self.saved.dry_run or self.dry_run.isChecked():
            QMessageBox.information(self, "テストモード", "BAN解除はYouTube上の操作です。テストモードをOFFにして設定を保存してください。")
            return
        if self.monitor is not None and self.monitor.isRunning():
            QMessageBox.warning(self, "監視中", "監視を停止してからBANを解除してください。")
            return
        if self.unban_job is not None and self.unban_job.isRunning():
            return
        db = History(self.db_path)
        try:
            bans = db.active_permanent_bans(self.selected_channel_id)
        finally:
            db.close()
        if not bans:
            QMessageBox.information(self, "BAN解除", "解除可能な永久BAN記録がありません。")
            self._update_unban_button()
            return
        if len(bans) > 1:
            labels = [f"{x['broadcast_id']} / {x['timestamp']} / {x['ban_id']}" for x in bans]
            label, ok = QInputDialog.getItem(self, "解除するBANを選択", "配信ID / BAN日時 / BAN ID", labels, 0, False)
            if not ok:
                return
            target = bans[labels.index(label)]
        else:
            target = bans[0]
        answer = QMessageBox.question(
            self, "永久BAN解除の確認",
            f"{target['display_name']} の永久BANを解除しますか？\n"
            f"対象配信: {target['broadcast_id']}\n"
            "YouTube APIにBAN解除を送信します（200ユニット）。\n"
            "削除済みコメントは復元されません。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.unban_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.unban_job = BanLiftThread(self.db_path, target)
        self.unban_job.completed.connect(self._unban_success)
        self.unban_job.failed.connect(lambda detail: QMessageBox.warning(self, "BAN解除失敗", detail))
        self.unban_job.finished.connect(self._unban_finished)
        self.unban_job.start()

    def _unban_success(self, channel_id: str, detail: str) -> None:
        self._receive_event({"label": "ban_lift", "name": channel_id, "detail": detail})
        self.statusBar().showMessage(detail, 12000)
        self._refresh_history_users()
        self._refresh_quota()

    def _unban_finished(self) -> None:
        self.start_button.setEnabled(self.monitor is None or not self.monitor.isRunning())
        self._refresh_history_users()
        self._update_unban_button()
        self._refresh_quota()

    def _export_user(self) -> None:
        channel_id = self.selected_channel_id
        if not channel_id:
            QMessageBox.information(self, "未選択", "ユーザーを選択してください。")
            return
        db = History(self.db_path)
        try:
            data = user_txt(channel_id, db.history_for_user(channel_id))
        finally:
            db.close()
        export_dir = self.base / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        # Identifiers may not be filesystem-safe if data came from unexpected sources.
        safe_id = "".join(c for c in channel_id if c.isalnum() or c in "-_")
        filename, _ = QFileDialog.getSaveFileName(
            self, "ユーザー履歴のTXT保存", str(export_dir / f"{safe_id}.txt"), "Text files (*.txt)")
        if filename:
            try:
                Path(filename).write_text(data, encoding="utf-8-sig")
                self.statusBar().showMessage(f"保存しました: {filename}", 10000)
            except OSError as exc:
                QMessageBox.warning(self, "保存失敗", str(exc))

    def _delete_user(self) -> None:
        channel_id = self.selected_channel_id
        if not channel_id:
            return
        response = QMessageBox.question(
            self, "ローカル履歴削除",
            f"{channel_id} の保存済みコメント・警告・BAN履歴をこのPCから削除します。\n"
            "YouTube上のコメントやBANには影響しません。続行しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        db = History(self.db_path)
        try:
            db.delete_user(channel_id)
        finally:
            db.close()
        self.selected_channel_id = ""
        self._refresh_history_users()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self.monitor is not None and self.monitor.isRunning():
            self.monitor.stop()
            # APIs have network timeouts; do not destroy a running Qt thread.
            self.monitor.wait()
        for job in (self.auth_job, self.broadcast_job, self.unban_job):
            if job is not None and job.isRunning():
                job.wait()
        event.accept()


def main() -> None:
    import sys

    logger = get_logger()
    old_hook = sys.excepthook

    def log_uncaught(exc_type, exc_value, exc_traceback):
        logger.critical("uncaught_gui_exception", exc_info=(exc_type, exc_value, exc_traceback))
        old_hook(exc_type, exc_value, exc_traceback)

    sys.excepthook = log_uncaught
    app = QApplication([])
    app.setApplicationName("LiveChatGuard")
    try:
        window = MainWindow()
    except Exception as exc:
        logger.exception("startup_failed")
        QMessageBox.critical(None, "起動失敗", f"設定またはデータを読み込めませんでした。\n{exc}")
        raise SystemExit(1) from exc
    window.show()
    raise SystemExit(app.exec())
