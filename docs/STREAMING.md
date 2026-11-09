# コメント取得方式について（v0.2.0）

## おすすめ：streamList（gRPC）

Google公式 `liveChatMessages.streamList` は、クライアントからYouTubeへ接続を確立し、YouTubeが新着コメントをpushする方式です。定期的な空振り問い合わせを回避できるため、BAN用途ではこちらを推奨します。

- API参照：https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages/streamList
- Pythonガイド：https://developers.google.com/youtube/data/live/streaming-live-chat
- 接続リクエストのクォータコスト：5ユニット
- 認証：既存のOAuthアクセストークン。APIキーの追加作成は不要
- 再接続：最後に取得した `nextPageToken` で再開
- データ判定：各 `publishedAt` を使用。到着時刻では判定しない
- クォータ上限や `RESOURCE_EXHAUSTED`：安全のため無限にリトライせず停止

`src/livechat_guard/stream_grpc.py` は公式プロトコル定義のうち、このアプリが参照するフィールドのみをprotobuf互換で定義しています。利用者のPCでコード生成する必要はありません。公式APIの変更時にはこのファイルの互換性を確認してください。

## 予備：REST定期取得

`liveChatMessages.list` を指定間隔で呼び出す方式です。新規設定の最短間隔は120秒です。YouTubeが返す `pollingIntervalMillis` より短くは呼びません。API仕様で1回5ユニットかかるため、**2分ごとの場合は約150ユニット/時間**です（配信検索・警告・制限の操作を除く）。

取得後は各コメントの `publishedAt` を利用して連投回数を更新します。ただし2分間に大量のコメントが届く配信では、APIの返却件数・ページ送り制約によって取りこぼしが起こりえます。リアルタイム性が必要なBAN目的では使用を推奨しません。

## バージョン更新時

v0.1.1までの設定ファイルに `fetch_mode` がない場合は、自動で `stream`（新規定義のデフォルト）になります。旧設定の `minimum_poll_seconds` は予備のREST方式用として引き継がれます。

**重要：** `quotaExceeded` は、すでに使用したユニットの問題です。取得方式を変えても使用枠は即時に回復しません。Google Cloud Consoleで割り当てと残量を確認してください。
