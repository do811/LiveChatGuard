# LiveChat Guard

**YouTubeライブのチャットをPythonで監視し、短い間隔で連続投稿するユーザーへの警告・投稿制限を支援する、Windows向けGUIアプリ（日本語対応）です。**

> **ステータス：v0.4.0 / gRPC再接続・障害ログを強化、永久BAN解除・クォータ推定表示に対応（要実配信検証）**  
> コメント判定・データ保存の自動テストを付属していますが、実際のYouTube配信アカウントへの接続／警告送信／BAN操作は、このリポジトリの作成時点では検証していません。まずはテスト配信で確認してください。

## v0.4.0：切断・障害対応の強化（2026-11-11）

- 以前のv0.3.0で「`streamListが短時間で5回切断`」と停止した問題に対応しました。接続が30秒未満で終わっただけでエラーと決めつけず、**コメントを受信したか、`nextPageToken` が進んだか、gRPCステータスは何か**を区別します。
- 接続が継続的に終了する場合、**待機時間を徐々に延長**します。10分間の接続開始数を最大10回に制限し、クォータの浪費を回避します。接続・切断のたびに新規API呼び出しが発生し得る点には注意してください。
- `UNAVAILABLE` 等の一時的通信エラーは再接続し、`RESOURCE_EXHAUSTED`、認証・権限・リクエストエラーは安全のため停止します。
- **ログ出力先：** `%LOCALAPPDATA%\LiveChatGuard\logs\livechat_guard.log`。接続秒数、応答件数、受信コメント件数、gRPCステータス、待機時間を追跡でき、GUIからログフォルダを開けます。ローテーションは1ファイル2 MiB、旧ログを3個保持します。チャット本文・OAuthトークンは意図的に記録しません。
- 監視ルール、警告・BAN・BAN解除、履歴、クォータ推定値の使い方はv0.3.0と同じです。設定・履歴フォルダを消さず、ZIPのソースを上書き後 `pip install -e .` してください。
- **実配信との接続は未検証です。** まずはテストモードで再確認し、障害再発時は `livechat_guard.log` の該当箇所をご確認ください。

詳しい障害別の挙動・ログの読み方は [docs/STREAMING.md](docs/STREAMING.md) にあります。

## 主な機能

- 自分のライブ配信をOAuth 2.0認証で取得し、GUIから選択
- **YouTube公式 `liveChatMessages.streamList`（gRPC）で新着コメントをプッシュ受信（標準・クォータ節約）**
- 代替として `liveChatMessages.list` による定期取得も選択可能（初期120秒間隔）
- **コメント1 → 次のコメントがn秒以内 → 次のコメントがn秒以内…** という連続投稿判定
- 標準モード：**警告（デフォルト3回目）→ 永久BAN（デフォルト5回目）**
- オプションモード：**警告 → 一時BAN → 再犯時に強化 → 規定回数で永久BAN**
- チャットへの警告投稿（設定でON/OFF可能）
- **永久BANのAPI成功確認後に、同じ配信で取得・記録済みの当該ユーザーのコメントを個別削除**（設定でON/OFF可能。初期ON）
- 削除APIの成否をコメント別に記録し、GUI・TXT履歴で確認可能
- **ユーザー別履歴から、アプリが記録した永久BANを解除**（YouTubeのBAN IDを使用。操作結果を履歴に保存）
- **監視ダッシュボードでAPIクォータの推定使用量・推定残量・操作別内訳を確認**（Google Cloudの実測値とは区別）
- 削除件数の上限を設定可能（**初期0＝取得済み全件**、安全のため上限を指定することも可能）
- ユーザーごとにSQLiteへコメントと警告・制限結果を記録
- GUIでユーザー履歴を検索・閲覧し、読みやすい **.txt** に書き出し
- 配信者・モデレーター・メンバー・指定チャンネルの除外設定
- **テストモードが初期設定でON**（判定のみ。警告投稿・BAN・BAN解除・コメント削除はYouTubeに送らない）
- `streamList` が切断された場合は続きから再開し、メッセージIDで重複排除
- 認証トークンはOSの資格情報ストアに保存。設定JSONには保存しない
- 保存済みAPIデータを最大29日で自動削除、ユーザー単位でもローカル履歴を削除可能

## 重要：制限の条件

このアプリは「直近10秒の投稿総数」方式ではありません。**同じユーザーの隣り合うコメント間隔**が基準です。

設定例：`判定時間 = 10秒 / 警告 = 3連投 / BAN = 5連投`

| コメント | 時刻（例） | 前回との差 | 連投カウント | 動作 |
|---|---|---|---|---|
| 1 | 00:00 | - | 1 | - |
| 2 | 00:05 | 5秒 | 2 | - |
| 3 | 00:13 | 8秒 | 3 | 警告 |
| 4 | 00:17 | 4秒 | 4 | - |
| 5 | 00:22 | 5秒 | 5 | 永久BAN |
| 6 | 00:40 | 18秒 | 1 | カウントリセット |

- 投稿間隔が**指定秒数以下**ならカウントを増やします。指定秒数を超えたら、そのコメントを1回目としてリセットします。
- **同じ連投の最中、警告とBANの判定は各1回**です。連投が途切れると再び警告対象になります。
- 別ユーザーのコメントは一切カウントに影響しません。
- YouTubeが返す投稿時刻を使用し、取得済みメッセージIDの重複は除外します。
- 標準モードでの永久BANは、その連投が途切れず5回に達したときに実行します。

## 永久BAN後の既存コメント削除（v0.2.1）

通常の `liveChatBans.insert(type=permanent)` は、対象ユーザーが**当該ライブチャットへ今後参加できないようにする**操作です。これだけで過去コメントが全部削除されると仮定しないでください。YouTube Studioの「チャンネルでユーザーを非表示にする」も別の操作です。

このアプリでは、**永久BANがYouTube APIで成功（BAN IDが返る）した場合のみ**、同じライブ配信で**このアプリが取得してSQLiteに記録している**対象者のコメントIDを列挙し、`liveChatMessages.delete` を1件ずつ実行します。警告・一時BAN・`dry_run`・永久BAN失敗では削除しません。BAN直後にまだストリームから届くコメントにも削除を試みます。**アプリを起動する前のコメント、別配信のコメント、通常動画コメント、未取得のコメントを一括削除する機能ではありません。**

- `liveChatMessages.delete` は **1件20クォータユニット**（例：5件100、50件1,000）。**初期設定は取得済み全件**です。大勢のコメントを削除すると再び `quotaExceeded` になり得ます。心配な場合、GUIで「BAN後に削除するコメント件数の上限」を例として10～50件にしてください。0なら全件です。
- クォータ超過・権限エラー・その他API失敗時はその時点で削除バッチを止めます。クォータ超過なら監視も停止します。
- `404` は「YouTube上では対象コメントが既に存在しない」として記録し、削除成功とは区別します。APIエラー時に削除できなかった件数もGUIのイベントとTXTの履歴に表示します。
- **YouTube上の削除は取り消せません**。一方で監査目的のローカル履歴テキストは自動消去しません（履歴の保持期間設定が適用されます）。
- 従来のSQLite履歴は起動時に新しい列を自動追加し、以前の記録を引き継ぎます。
- BAN・削除の実行可否はアプリのOAuth権限やYouTube側の状態に依存します。実配信での連続動作は未検証です。

YouTube公式仕様： [BAN API](https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatBans/insert)、[コメント削除API](https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages/delete)、[チャンネルでユーザーを非表示](https://support.google.com/youtube/answer/9482361?hl=ja-jp)。

## 永久BANの解除（v0.3.0）

YouTubeの `liveChatBans.delete` により、以前発行した **BAN ID** を指定して当該ライブチャットのBANを解除できます。**ユーザーのチャンネルIDだけでは解除できません。** 解除後はそのライブチャットに再び投稿できるようになりますが、**削除済みのチャットコメントは復元されません。**

1. 監視ダッシュボードで **「■ 監視停止」** を押します。
2. 「監視ルール・接続設定」で **テストモードをOFFにして設定を保存** します（解除は実際のYouTube書き込み操作のため）。
3. 「ユーザー別履歴」でBANされたユーザーを選択します。
4. **「永久BANを解除」** を押します。複数の配信でBANした履歴がある場合、対象配信・BAN日時・BAN IDを選びます。
5. 確認ダイアログで対象を確認し、実行すると解除の成功・失敗が履歴とTXTに保存されます。

- 解除対象は、**このアプリのSQLite履歴にBAN ID付きで `permanent_ban / success` と記録されているもののみ**です。`dry_run` や失敗したBAN、外部ツール・YouTube Studioで行ったBANは自動検索・解除できません。
- 解除APIは **1回200ユニット** 消費します。クォータ上限に達していると解除できません。
- API失敗時は、ローカルでは「BAN中」の状態を維持します。ただし **404（対象のBANが見つからない）** ときは「解除済みまたはID無効」として履歴に記録し、再度解除を試みません。既に解除済みのBAN IDにも再度APIを呼びません。
- 自動保存履歴を削除した場合、あるいは保持期限が切れた場合はBAN IDが失われ、**このアプリから過去のBANを解除できません。** YouTube Studio側の管理と併用してください。
- 解除が成功しても、監視中の連投判定履歴が過去に記録した違反として残る場合があります。監視停止中のみ解除できるため、次回監視開始時には連投カウントが新規に開始されます。ローカル履歴そのものは削除しません。

公式仕様：[LiveChatBans: delete](https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatBans/delete)

## APIクォータの確認（v0.3.0）

「監視ダッシュボード」の **「YouTube API クォータ（このアプリの推定値）」** 欄に、次の値が表示されます。

- **本日のアプリ内推定消費ユニット数**：v0.3.0で記録を開始してから、このPCでこのOAuthプロジェクトを使用して行った各APIリクエストの費用合計。
- **推定残量**：設定した1日クォータ上限 － このアプリが記録した推定消費量（下限0）。**Google Cloudプロジェクトの実際の残量ではありません。**
- **操作別内訳**：配信一覧取得・リアルタイム受信接続・REST取得・警告・BAN・BAN解除・コメント削除の呼び出し数と推定費用。
- **`quotaExceeded` 検知**：APIから明確なクォータ超過エラーが返ったときは、推定残量に関係なく警告を表示。
- **「Google Cloudで正確な使用量を確認」ボタン**：ブラウザーでYouTube Data API v3の割り当てページを開く（該当Google Cloudプロジェクトを確認）。

**実際のクォータ残量をYouTube Data APIから直接取得できるメソッドはありません。** このアプリのカウンターはローカルSQLite（`quota.sqlite3`）に送信予定のAPIリクエストを記録した推定値です。**古いバージョン・他のPC・ほかのアプリ・Google Cloudコンソールで使用した分は計上できません**。認証エラーなどでサーバーに届かなかった試行も記録するため、逆に多く見積もる場合もあります。最終確認はGoogle Cloudの管理画面で行ってください。

| 操作（公式API） | 1回の費用 |
|---|---:|
| `liveBroadcasts.list` / 配信一覧取得 | 1ユニット |
| `liveChatMessages.streamList` / ストリーム接続 | 5ユニット |
| `liveChatMessages.list` / RESTでチャット取得 | 5ユニット |
| `liveChatMessages.insert` / チャットに警告を投稿 | 20ユニット |
| `liveChatBans.insert` / 一時・永久BAN | 200ユニット |
| `liveChatBans.delete` / BAN解除 | 200ユニット |
| `liveChatMessages.delete` / コメント削除 | 20ユニット/件 |

1日のクォータ上限の初期値は **10,000ユニット**ですが、Google Cloud側の実際の上限に合わせて「監視ルール・接続設定」から変更してください。**日次集計は米国太平洋時間（夏時間を含む）の午前0時に切り替わります**（日本時間では夏時間中16時／標準時間中17時）。クォータ記録は約1か月で自動整理します。表示更新は自動・手動の両方に対応しています。

公式仕様：[クォータ費用表](https://developers.google.com/youtube/data/determine_quota_cost)、[Google Cloud APIの割り当て](https://console.cloud.google.com/apis/api/youtube.googleapis.com/quotas)

## 動作環境

- Python 3.10以上（Windows 10/11 + Python 3.12を推奨）
- YouTubeでライブ配信できるアカウント
- Google Cloudプロジェクト・YouTube Data API v3の有効化
- Googleの **OAuth 2.0 クライアント（デスクトップアプリ用JSON）**
- インターネット接続

**APIキーのみではBANやチャット投稿はできません。OAuth 2.0認証が必須です。**

## Windowsセットアップ

PowerShellで：

```powershell
cd LiveChatGuard
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m livechat_guard
```

PowerShellの実行ポリシーにより仮想環境を有効化できない場合は、代わりに以下のように実行できます。

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m livechat_guard
```

セットアップ後は `start_windows.bat` をダブルクリックして起動できます。

### Google Cloudの認証設定

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成します。
2. **YouTube Data API v3** を有効にします。
3. OAuth同意画面を設定します。テストモードのOAuthアプリなら、認証するアカウントをテストユーザーとして登録する必要がある場合があります。
4. OAuthクライアントIDの種類は **デスクトップアプリ** を選択し、JSONをダウンロードします。
5. GUIの「監視ルール・接続設定」タブでJSONファイルの場所を設定し、「Googleアカウントで認証」をクリックします。
6. ブラウザーでライブ配信しているアカウントを選択し、必要なYouTube権限を許可します。
7. 「監視ダッシュボード」タブで **自分の配信一覧を取得** → 配信選択 → **監視開始**。
8. 初期設定のテストモードで挙動を確認し、必要な場合のみテストモードをOFFにして実制限を有効化します。

詳細は [docs/API_SETUP.md](docs/API_SETUP.md) を参照してください。

## GUIの画面

- **監視ダッシュボード**：配信選択、開始・停止、取得コメントと処理イベントの直近300件、**APIクォータの推定使用量・推定残量・内訳**、Google Cloud管理画面へのリンク
- **監視ルール・接続設定**：判定秒数、警告回数、BAN回数、モード、再犯条件、**BAN後のコメント削除ON/OFF・件数上限**、**1日クォータ上限**、OAuth、テストモード、除外設定
- **ユーザー別履歴**：ユーザー検索、コメント・警告・BAN・解除の時系列閲覧、**BAN解除ボタン**、TXT書き出し、ローカル履歴の削除

**取得方式は「リアルタイム受信（推奨）」を選択してください。** 以前のv0.1.1の設定が残っている場合も、新しい `fetch_mode` は自動的に `stream` になります。

定期取得モードの120秒設定は**連投判定時間とは独立**しています。取得が遅れても、YouTubeの投稿時刻で判定します。ただし違反検知から制限発動まで最大約2分の遅延が生じ、投稿が集中すると一部のメッセージを取りこぼす可能性があるため、BAN目的ではストリーミングを推奨します。

変更した設定は保存後、**次の監視開始**から反映されます。

## 履歴の書き出し例

```text
アカウント：User_A
チャンネルID：UCxxxxxxxx

[2026/11/09 16:02:00] こんにちは
[2026/11/09 16:02:05] コメント2
[2026/11/09 16:02:13] コメント3
＝＝警告発動＝＝
[2026/11/09 16:02:13] 10秒以内の連続投稿 3回
処理結果：success
[2026/11/09 16:02:17] コメント4
[2026/11/09 16:02:22] コメント5
＝＝永久BAN発動＝＝
[2026/11/09 16:02:22] 10秒以内の連続投稿 5回
処理結果：success
＝＝過去コメント削除＝＝
[2026/11/09 16:02:22] 削除成功 5件 / 既に存在しない 0件 / 失敗 0件 / 未処理 0件
処理結果：success
＝＝永久BAN解除＝＝
[2026/11/10 14:50:00] BAN解除成功（配信ID: example_video_id、BAN ID: example_ban_id）
処理結果：success
```

※ 実際の記録では警告・BANをAPIで処理した時刻とコメント時刻が異なることがあります。

## 段階的制限モード

デフォルト例（24時間内の成功した一時BAN履歴を参照）：

| 違反到達回数 | 制限 |
|---|---|
| 1回目 | 5分間の一時BAN |
| 2回目 | 30分間の一時BAN |
| 3回目 | 永久BAN |

違反到達ごとに警告閾値と制限閾値を判定します。**実際に成功した一時BAN** のみ次回の制限強化にカウントされ、API失敗やテストモードはカウントされません。チャット警告OFF時は警告イベントを `local_only` として保存します。再犯の判定期間を超えた履歴もこの判定から除外します。

## ローカルデータの保存場所

Windowsでは通常 `%LOCALAPPDATA%\LiveChatGuard\` です。

```text
LiveChatGuard (ローカルデータ)
├── settings.json          # 一般設定のみ（OAuthトークンは含まない）
├── history.sqlite3        # コメント・操作履歴（BAN ID・解除履歴を含む）
├── quota.sqlite3          # API消費の推定値（本PCのv0.3.0以降のみ）
└── exports/               # GUIで保存したTXT（利用者が管理）
```

OAuth認証情報は、Pythonの `keyring` 経由でWindows資格情報マネージャー等に保存します。**client_secrets JSON、認証トークン、実ユーザーのログをGitHubにアップロードしないでください。**

## YouTube APIの制約・注意

- **コメントの投稿自体を未然には止められません。** コメントを取得してから違反判定し、その後に制限します。投稿とAPI受信には遅延があります。
- 監視開始前のコメントは、各メッセージの `publishedAt` で除外します。初回の配信レスポンスが過去ログを含んでいても、その内容でBANしません。タイムスタンプの秒精度の都合で開始と同じ秒の一部コメントは含まれ得ます。
- **標準はgRPCの `liveChatMessages.streamList` 方式です。** 最初に接続し、新しいコメントが届くたびにYouTubeから送信されるため、空のコメント欄を繰り返し問い合わせません。接続には5ユニット必要です。通信切断時は最後の `nextPageToken` から再開します。クォータ残量が0ならこの方法でも利用できません。
- **予備のREST定期取得** は `liveChatMessages.list` を使用し、YouTubeの `pollingIntervalMillis` と設定した最短間隔の長い方を守ります（新規設定の既定値は120秒）。`list` は現在5ユニット/回です。120秒間隔なら30回/時間 × 5 = **約150ユニット/時間**（コメント取得のみの目安）。高負荷チャットではページ上限などで取りこぼしの可能性があります。
- YouTube側の権限が不足していると警告やBANは失敗します。失敗はイベント・履歴に記録します。
- すべてのチャットの種類を数えるわけではなく、通常のテキストチャット `textMessageEvent` のみを判定します。
- 永久BANはYouTube上の**ライブチャット参加禁止**です。Googleアカウント全体を停止するものではありません。
- OAuthの検証状態やテストユーザー登録、スコープ審査、クォータ制限により使用できない場合があります。第三者向け公開前にGoogleの要件を確認してください。
- YouTube API Servicesポリシーに合わせ、アプリのSQLite記録は最大29日で削除します。**エクスポートしたTXT・バックアップ等は自動削除されないため、利用者側で期限内に削除・適切に管理してください。** 認証失効・APIアクセス撤回時の保存データの取り扱いも考慮してください。
- ここではGoogleのアカウント認証情報そのものを収集しません。OAuthクライアントJSONに含まれるシークレットやtokenは公開リポジトリに含めないでください。

公式ドキュメント：

- [LiveChatMessages: streamList](https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages/streamList)
- [Streaming Live Chat (gRPC / Python)](https://developers.google.com/youtube/data/live/streaming-live-chat)
- [LiveChatMessages: list](https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages/list)
- [LiveChatBans: insert](https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatBans/insert)
- [LiveChatBans: delete](https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatBans/delete)
- [YouTube Data APIクォータ費用表](https://developers.google.com/youtube/data/determine_quota_cost)
- [LiveChatMessages: insert](https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages/insert)
- [LiveBroadcasts: list](https://developers.google.com/youtube/data/live/reference/rest/v3/liveBroadcasts/list)
- [YouTube API Services - Developer Policies](https://developers.google.com/youtube/terms/developer-policies)

## ソースディレクトリ

```text
LiveChatGuard/
├── src/livechat_guard/
│   ├── __main__.py         # エントリーポイント
│   ├── gui.py              # PySide6 GUI
│   ├── settings.py         # 設定保存と検証
│   ├── auth.py             # OAuth認証・安全なトークン保存
│   ├── youtube_api.py      # YouTube公式REST API・クォータ記録
│   ├── quota.py            # PT日次・API別ユニット推定集計
│   ├── ban_control.py      # BAN IDによる解除・結果監査
│   ├── stream_grpc.py      # streamList / gRPCの受信・protobuf互換形式
│   ├── moderation.py       # 連投判定エンジン
│   ├── storage.py          # SQLite・TXT出力
│   └── worker.py           # 別スレッド監視・制限・BAN解除処理
├── tests/                  # オフラインで動くユニットテスト
├── docs/                   # API設定・設計
├── .github/workflows/      # GitHub Actions
├── config.example.json
├── pyproject.toml
├── requirements.txt
├── start_windows.bat
├── .gitignore
└── LICENSE
```

## テストの実行

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

オフラインの判定とSQLiteテストは、実際のGoogleアカウントやAPIキーなしで動作します。**認証や実制限操作に関するE2Eテストは未実施**です。

## v0.2.0：新着コメントのプッシュ受信（推奨）

- **通常は「リアルタイム受信（推奨・streamList）」** を選択してください。API呼び出しを定期的に繰り返さず、新着コメントが届き次第受け取ります。**コールバックで外部からPCにアクセスする仕組みではなく、PCからYouTubeへ張った接続を維持する方式**です。
- 公式gRPC APIを利用しています。`grpcio` と `protobuf` は `pip install -e .` で自動導入されます。`grpcio-tools` やコード生成は不要です。
- ストリームが切れた場合、最後の `nextPageToken` から再接続します。重複コメントはDBのメッセージIDで排除します。API側のエラー時には状況に応じて停止または待機し、無限にリクエストしません。
- 過去コメントの除外と連投判定には、受信時刻でなくYouTubeの `publishedAt` を使います。判定秒数・警告回数・BAN回数・制限モード・TXT履歴・OAuthは従来どおりです。
- GUIの「定期取得（REST・予備モード）」に切り替えると、初期120秒間隔で問い合わせます。コメント間隔の判定そのものは変わりませんが、制限が遅くなるため、テスト用途を想定しています。
- **`quotaExceeded` が発生した時点でその日のクォータを使い切っている場合、方式を変えても即時復旧はしません。** Google CloudでAPI使用量とリセットを確認してください。

**更新方法（旧バージョンから）**：監視を停止してアプリを終了 → 新ZIPのソースファイルを上書き（`%LOCALAPPDATA%\LiveChatGuard` にあるログ・設定を消さない） → `.\.venv\Scripts\python.exe -m pip install -e .` で依存関係を更新 → アプリを再起動してください。認証情報はOS側に残るので、基本的にOAuthの再認証は必要ありません。

**未検証事項**：実配信のgRPC接続、GoogleアカウントでのOAuth実動作、BAN・警告送信はこの制作環境では検証できていません。配信者アカウントで必ずテストモードから試してください。

## v0.1.1で追加した安全対策（継続）

- `quotaExceeded` 等を検知したら無駄な再試行を避けます。
- 「テストのみ・実行なし」「API成功」「API失敗」をGUI履歴に明示します。
- BAN IDがYouTube APIから返らないときは、成功と判断しません。
- 永久BAN成功後、取得済みのコメントを個別に削除できます（v0.2.1以降）。

## 今後の改善候補

- 実配信での `streamList` 回線耐久テスト・APIクォータ計測
- APIレベルの手動BAN操作・任意コメントの削除（BAN解除はv0.3.0で対応済み）
- GUIからのBAN理由編集、警告文テンプレート編集
- 履歴の期間指定・配信別絞り込み、コメント増加率グラフ
- PyInstallerによるWindowsアプリの配布

## ライセンス

MIT License。GoogleやYouTubeの公式提供アプリではありません。
