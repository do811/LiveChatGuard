# Google / YouTube API 初期設定

1. [Google Cloud Console](https://console.cloud.google.com/) にログインし、利用するプロジェクトを選択／作成。
2. APIとサービスから **YouTube Data API v3** を有効化。
3. Google Auth Platform（旧OAuth同意画面）の必要項目を入力。テスト中は自分のGoogleアカウントをテストユーザーとして指定。
4. デスクトップアプリとして OAuth 2.0 クライアントIDを作成。
5. クライアントJSONをダウンロード。**ファイルをリポジトリに置いたりコミットしたりしない。**
6. LiveChat Guardの「監視ルール・接続設定」でJSONを参照 → 「Googleアカウントで認証」。
7. デフォルトブラウザーでGoogle認証し、配信しているチャンネルを適切に選択。
8. ダッシュボードで配信一覧を取得。ライブ中の配信（`lifeCycleStatus=live`）のみ表示。
9. 初回はテストモードのまま監視し、問題がなければ実制限へ切り替える。

## 必要スコープ

`https://www.googleapis.com/auth/youtube.force-ssl`

このスコープで所有チャンネルの配信一覧を読んだり、権限のあるライブチャットに警告を投稿したり、ユーザーのチャット参加を禁止できます。実際のAPI操作には、配信者またはモデレーター権限が必要です。

## よくあるエラー

- **ライブ配信0件**：配信は実際にライブ状態か、認証したGoogleアカウントがそのチャンネルの所有者か確認。
- **403 insufficientPermissions**：誤ったアカウント・権限不足・許可スコープ不足の可能性。認証情報を削除して再認証。
- **403 liveChatDisabled/liveChatEnded**：ライブチャットが無効または終了。
- **429/403 rateLimitExceeded/quotaExceeded**：API制限。アプリは失敗時に再試行し、一定回数後に停止します。
- **アクセスがブロックされた**：OAuth同意画面の公開状態、テストユーザー、アプリ審査の条件を確認。
- **再認証が必要**：Google OAuthテストモード等でリフレッシュトークンが短期間で失効する場合があります。

YouTube APIの利用にはGoogleの利用規約・デベロッパーポリシーが適用されます。公開アプリとして多人数に配布する場合、認証・公開審査・プライバシーポリシーの要件も確認してください。

関連資料：
- https://developers.google.com/youtube/v3/guides/authentication
- https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatBans/insert
- https://developers.google.com/youtube/terms/developer-policies
