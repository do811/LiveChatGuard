# 設計ノート

## データフロー

```text
Google OAuth（OS資格情報ストア）
        │
        ▼
YouTube Live API（liveBroadcasts.list / streamList【標準】 / list【予備】）
        │
        ▼
MonitorThread  ───→ SQLite History ──→ GUI履歴 ──→ TXTエクスポート
        │
        ▼
除外判定 → ユーザー単位のStreakDetector
        │
        ├─ 3連投 → 警告を記録 → 必要ならliveChatMessages.insert
        └─ 5連投 → モード判定 → liveChatBans.insert
                                 │
                                 └─ 実行成功/失敗/テストをSQLiteへ記録
                                    └─ 永久BAN成功時のみ
                                       → 同一配信/同一IDで記録済みメッセージを列挙
                                       → liveChatMessages.deleteを1件ずつ実行
                                       → 成否・未処理件数をSQLiteへ保存

ユーザー別履歴 ──→ BAN ID付きの成功記録を照会
             └─ 監視停止・テストモードOFF・利用者確認
                → liveChatBans.delete → 解除の成功/失敗をSQLiteへ記録

YouTube API呼び出し ──→ quota.sqlite3（方法/単位/太平洋時間の日付）
                    └─ 監視ダッシュボードにアプリ内推定使用量/推定残量
                       ※ 実際の残量はGoogle Cloud Consoleで別途確認
```

## 一連投の状態

- ユーザーごとに `last_published_at / count / warned / limited` を保持。
- 次のコメントとの間隔が `0 <= Δt <= window_seconds` なら `count += 1`。
- `Δt > window_seconds` やタイムスタンプ逆転では1にリセット。
- 一連投中は警告1回、制限1回まで。閾値は `2 <= warning_count < limit_count`。
- 初回に届く過去ログは、`publishedAt` が監視開始より古い場合に除外する。初回レスポンス全体を破棄するわけではない。
- SQLiteにmessage IDのUNIQUE制約を設定。再取得したコメントは重複記録・重複判定しない。

## データ保存

`messages(message_id, broadcast_id, channel_id, display_name, body, published_at, delete_outcome, delete_note, deleted_at)`

`actions(id, broadcast_id, channel_id, display_name, kind, detail, outcome, timestamp, ban_id)`

- `outcome`: `success`, `failure`, `dry_run`, `local_only` の4種類。
- `kind`: `warning`, `temporary_ban`, `permanent_ban`, `message_cleanup`, `ban_lift`。
- 削除記録の`delete_outcome`は `success` / `not_found` / `failure`。未試行はNULL。
- 再犯カウントは `temporary_ban` かつ `success` のみ参照。
- トークン・OAuth secretsはSQLiteや設定ファイルに保存しない。
- SQLiteはWALモードを利用し、GUIと監視スレッドはそれぞれ独立したDB接続を作成。
- APIデータは既定29日保存。起動時／監視開始時に古いデータを削除（常駐中の毎日掃除は今後の改善対象）。

## 明示的な制限・今後の課題

- YouTube側ではライブチャットが終了した後のコメント取得はできない。
- YouTube API/回線の遅延により制限開始までに追加コメントが投稿される可能性がある。
- 監視中のユーザーが膨大な場合、StreakDetectorのメモリから古いユーザー状態を定期的に掃除できると良い。
- 永久BANの解除は保存されたBAN IDを利用し、実際のAPI操作を履歴に残す。外部で行われたBANの一覧取得はできない。
- イベント詳細検索、期間指定検索は未実装。
- `streamList` はgRPC接続を維持し、新着メッセージがあるとサーバーから受信する。切断時はnextPageTokenを再利用。
- 代替の `list` 方式は最短間隔とpollingIntervalMillisを守るが、クォータ負担と遅延がある。
- ログ出力をGitに含めないこと。履歴には第三者の発言・ユーザーIDが含まれる。
