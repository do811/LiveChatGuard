# LiveChat Guard

**YouTubeライブのチャットをPythonで監視し、短い間隔で連続投稿するユーザーへの警告・投稿制限を支援する、Windows向けGUIアプリ（日本語対応）です。**

> **ステータス：v0.2.0 / ストリーミング受信対応（要実配信検証）**  
> コメント判定・データ保存の自動テストを付属していますが、実際のYouTube配信アカウントへの接続／警告送信／BAN操作は、このリポジトリの作成時点では検証していません。まずはテスト配信で確認してください。

## 主な機能

- 自分のライブ配信をOAuth 2.0認証で取得し、GUIから選択
- **YouTube公式 `liveChatMessages.streamList`（gRPC）で新着コメントをプッシュ受信（標準・クォータ節約）**
- 代替として `liveChatMessages.list` による定期取得も選択可能（初期120秒間隔）
- **コメント1 → 次のコメントがn秒以内 → 次のコメントがn秒以内…** という連続投稿判定
- 標準モード：**警告（デフォルト3回目）→ 永久BAN（デフォルト5回目）**
- オプションモード：**警告 → 一時BAN → 再犯時に強化 → 規定回数で永久BAN**
- チャットへの警告投稿（設定でON/OFF可能）
- ユーザーごとにSQLiteへコメントと警告・制限結果を記録
- GUIでユーザー履歴を検索・閲覧し、読みやすい **.txt** に書き出し
- 配信者・モデレーター・メンバー・指定チャンネルの除外設定
- **テストモードが初期設定でON**（判定はするがYouTubeには投稿もBANもしない）
- `streamList` が切断された場合は続きから再開し、メッセージIDで重複排除
- 認証トークンはOSの資格情報ストアに保存。設定JSONには保存しない
- 保存済みAPIデータを最大29日で自動削除、ユーザー単位でもローカル履歴を削除可能

## 重要：制限の条件

**同じユーザーの隣り合うコメント間隔**が基準です。

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
py -m venv .venv
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

- **監視ダッシュボード**：配信選択、開始・停止、取得コメントと処理イベントの直近300件
- **監視ルール・接続設定**：判定秒数、警告回数、BAN回数、モード、再犯条件、OAuth、テストモード、除外設定
- **ユーザー別履歴**：ユーザー検索、コメント・警告・BANの時系列閲覧、TXT書き出し、ローカル履歴の削除

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
├── history.sqlite3        # コメント・操作履歴
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
- 永久BANはYouTube上の**ライブチャット参加禁止**です。
- OAuthの検証状態やテストユーザー登録、スコープ審査、クォータ制限により使用できない場合があります。第三者向け公開前にGoogleの要件を確認してください。
- YouTube API Servicesポリシーに合わせ、アプリのSQLite記録は最大29日で削除します。**エクスポートしたTXT・バックアップ等は自動削除されないため、利用者側で期限内に削除・適切に管理してください。** 認証失効・APIアクセス撤回時の保存データの取り扱いも考慮してください。
- ここではGoogleのアカウント認証情報そのものを収集しません。OAuthクライアントJSONに含まれるシークレットやtokenは公開リポジトリに含めないでください。

公式ドキュメント：

- [LiveChatMessages: streamList](https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages/streamList)
- [Streaming Live Chat (gRPC / Python)](https://developers.google.com/youtube/data/live/streaming-live-chat)
- [LiveChatMessages: list](https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages/list)
- [LiveChatBans: insert](https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatBans/insert)
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
│   ├── youtube_api.py      # YouTube公式REST API
│   ├── stream_grpc.py      # streamList / gRPCの受信・protobuf互換形式
│   ├── moderation.py       # 連投判定エンジン
│   ├── storage.py          # SQLite・TXT出力
│   └── worker.py           # 別スレッド監視・制限処理
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
- BAN成功後でも過去のコメントを自動削除する機能は未搭載です。

## 今後の改善候補

- 実配信での `streamList` 回線耐久テスト・APIクォータ計測
- APIレベルの手動BAN解除、手動BAN操作、コメント削除
- 履歴の期間指定・配信別絞り込み、コメント増加率グラフ
- PyInstallerによるWindowsアプリの配布

## ライセンス

MIT License。GoogleやYouTubeの公式提供アプリではありません。
