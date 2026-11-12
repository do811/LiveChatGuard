## v0.4.0 — gRPC接続復旧・障害調査ログの強化（2026-11-11）

- streamListで30秒未満に正常終了した場合に即失敗扱いする判定を廃止
- 通信エラー / EOF / 権限・認証・日次クォータ問題を区別し、異常時の挙動を明確化
- 10分間の接続開始数に上限を設け、連続切断時にはクォータ保護の待機を挿入
- 短時間切断が続いても即時に監視を終了せず、長めの間隔で再接続を試行
- 接続寿命、受信応答・コメント件数、gRPCステータス、再接続待ち時間をログへ記録
- `%LOCALAPPDATA%\LiveChatGuard\logs\livechat_guard.log` に2MiB×4世代のローテートログを記録
- 監視画面に「障害ログの保存フォルダを開く」ボタンを追加
- gRPC受信キャンセルの排他制御と切断後の継続トークンを保持
- エラーログには原則としてOAuthトークン・チャット本文・チャンネルIDを含めない
- 既存の警告／BAN／BAN解除／クォータ推定表示・SQLite履歴は継続

# Changelog

## v0.3.0 (2026-11-10)

- Add **permanent BAN undo** by saved YouTube ban resource ID from the user-history tab.
  Only successful permanent bans are eligible; failed requests remain auditable.
- Require monitoring to be stopped, test mode to be disabled, and confirmation before
  sending `liveChatBans.delete` (200 quota units).
- Add the dashboard's **local estimated API quota used/remaining**, per-method
  breakdown and `quotaExceeded` indicator, with a Google Cloud link for actual usage.
- Add quota tracking for REST API calls and gRPC `streamList` initial connections,
  grouped by OAuth project and Pacific Time day with DST-aware rollover.
- Document differences between local estimates and actual Google Cloud quota;
  do not silently claim the Cloud project's remaining quota is available.
- Preserve the existing SQLite message/action history and existing user settings.
- Add isolated tests for ban lifecycle, quotas, PT resets and separate projects.

## v0.2.1 (2026-11-10)

- Add automatic cleanup of locally observed live-chat messages **after confirmed permanent ban**.
- Add cleanup toggle and optional per-user cap in GUI (`0` = all known messages).
- Stop cleanup on YouTube API errors instead of blindly retrying.
- Preserve local history and store per-message deletion outcome, plus summary actions.
- Migrate existing SQLite DB to new columns without removing message history.
- Add isolated automated tests of cleanup (no YouTube connection required).

## v0.2.0

- Default to YouTube streamList receiving and provide REST polling as fallback.
