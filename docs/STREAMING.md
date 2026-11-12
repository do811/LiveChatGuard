# ストリーミング受信の障害対応（v0.4.0）

## 仕様

`liveChatMessages.streamList` は接続を維持して新しいチャットを受信しますが、接続が正常に終わることも通信エラーになることもあります。**30秒以内に接続が終わったという事実だけでAPI障害とは判断しません。**

- `EOF`：サーバーからのストリームが通常終了した。故障とは限らず、最後の `nextPageToken` から再開
- `UNAVAILABLE`、`DEADLINE_EXCEEDED`、`INTERNAL` など：一時的な通信障害として再接続
- `UNAUTHENTICATED` / `PERMISSION_DENIED` / `INVALID_ARGUMENT` / `FAILED_PRECONDITION` / `NOT_FOUND`：原則停止して原因を表示
- `RESOURCE_EXHAUSTED`：クォータや頻度制限のおそれがあるため自動再試行しない
- `offlineAt`：配信終了として停止
- 手動停止：ストリームをキャンセルし再接続しない

正常終了・通信エラーの後は、最低5〜15秒の待機を挟みます。短時間終了・新着なし終了が続くと待機が増え、**10分以内の接続開始数が10回に達したときには回数制限を優先**します。接続維持の失敗が続いても無限の高速再試行はしません。

`nextPageToken` は接続し直す際に再利用します。コメントの重複は既存のSQLiteのメッセージIDで排除します。トークン保存は同じ監視セッションのメモリ内のみです。アプリを終了するとサーバーから最近のログを取得し、監視開始前の投稿時刻は従来どおり除外されます。

## 障害ログ

ログは `%LOCALAPPDATA%\LiveChatGuard\logs\livechat_guard.log`（Windows）に保存されます。監視ダッシュボードの **「障害ログの保存フォルダを開く」** を使って確認してください。通常は `livechat_guard.log`、古い履歴は `.1`、`.2`、`.3` にローテートされます。

典型例（架空）:

```text
2026-11-11 12:00:00 INFO Thread-1 stream_connect attempt=1 resume=no
2026-11-11 12:02:00 WARNING Thread-1 stream_rpc_error code=UNAVAILABLE detail=...
2026-11-11 12:02:00 WARNING Thread-1 stream_disconnected attempt=1 code=UNAVAILABLE duration_s=120.0 responses=6 items=7 progress=True empty_streak=0 short_streak=0 retry_s=5.0 detail=...
2026-11-11 12:02:05 INFO Thread-1 stream_connect attempt=2 resume=yes
```

共有する場合は、トークンをログに出さないよう設計していますが、パスやユーザー情報などの機微な情報が紛れ込んでいないか必ず確認してから共有してください。**GoogleのOAuthクライアントJSON、history.sqlite3、settings.jsonを公開しないでください。**

## 実配信の検証

1. テストモードONで限定公開配信を開始
2. ライブチャットを複数件送信しGUIに表示されることを確認
3. 20〜30分ほど接続維持と切断の有無を確認
4. 切断したらログの `stream_disconnected` / `stream_rpc_error` を比較
5. クォータ使用量はGoogle Cloud Consoleで実測確認（ダッシュボードは推定値）

この環境では実YouTubeアカウントを使ったE2Eテストは未実施です。復旧処理が必ず動く保証ではありません。

