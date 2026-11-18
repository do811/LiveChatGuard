# LiveChatGuard v0.5.0 — PyInstaller Windows リリース手順

この3つのファイルを `C:\LiveChatGuard\`（`pyproject.toml` がある場所）にコピーします。

- `build_release.bat`
- `LiveChatGuard.spec`
- `livechat_guard_launcher.py`

## ビルド

PowerShell で次を実行します。

```powershell
cd C:\LiveChatGuard
.\build_release.bat
```

`.venv\Scripts\python.exe` が無い場合は、先に `py -3.12 -m venv .venv` で仮想環境を作成します。`build_release.bat` は既存の venv にアプリと PyInstaller をインストールします。実際のWindows用EXEのビルドはWindows上で行ってください。

### ビルドモード

| コマンド | 成果物 | 推奨用途 |
|---|---|---|
| `.\build_release.bat` | `dist\LiveChatGuard\LiveChatGuard.exe` とフォルダ一式 | **初回公開推奨** |
| `.\build_release.bat onefile` | `dist\LiveChatGuard.exe` | 単一EXE配布 |
| `.\build_release.bat debug` | フォルダ版＋コンソール表示 | 起動失敗の原因調査 |
| `.\build_release.bat onefile debug` | 単一EXE＋コンソール表示 | 単一版の原因調査 |

パッケージには、READMEとLICENSEを付けたリリースZIPが `dist\` に生成されます。

## EXE化で特に重要なこと

- `src/livechat_guard/__main__.py` を直接 PyInstaller に渡すと相対importで失敗し得るため、専用launcherを使います。
- `PySide6` は標準フックで収集。`keyring`（Windows資格情報ストア）、`googleapiclient`（動的discovery）、`tzdata`（太平洋時間集計）、`certifi` の補助ファイルを明示して収集します。
- OAuthクライアントJSON、OAuthトークン、ユーザーログ、SQLite履歴は**配布ZIPに含めません**。各ユーザーが自分の認証設定を行う必要があります。
- `settings.json` / `history.sqlite3` / `quota.sqlite3` は `%LOCALAPPDATA%\LiveChatGuard\`。ログは `LiveChatGuard.exe` の隣の `logs\livechat_guard.log`（書込み不可の場合は代替先）です。
- `--onefile` は初回起動が遅くなりやすく、ウイルス対策ソフトによる誤検出を受ける場合もあります。まず `--onedir` で機能確認してください。
- 受信・BAN・BAN解除・クォータ表示など、実際のYouTubeを使う試験は配布前に別PCのWindows環境で行ってください。初回はテストモードONを推奨します。
- `release_stage` はビルド作業フォルダで、配布されるZIPには含みません。

## GitHub Releases

1. `dist\LiveChatGuard_v0.5.0_Windows_onedir.zip` があることを確認します。
2. [GitHub Releases](https://github.com/do811/LiveChatGuard/releases) → **Draft a new release**。
3. タグを例として `v0.5.0`、説明文に機能と既知の制限を記載します。
4. **Attach binaries** に生成したZIPを追加して公開します。

GitHubの自動生成する **Source code (zip)** はPythonソースであり、実行可能なWindows版とは別です。

**注意:** 現在GitHubに公開されているソースがローカルのv0.5.0より古い場合、リリース前にバージョンを揃えてください。
