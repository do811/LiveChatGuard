"""OAuth desktop flow. Tokens live in the operating-system keyring, not a file."""

from __future__ import annotations

import json
from pathlib import Path

import keyring
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
KEYRING_SERVICE = "LiveChatGuard.YouTube"
KEYRING_USERNAME = "oauth_credentials"


def _save(credentials: Credentials) -> None:
    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, credentials.to_json())


def get_credentials() -> Credentials:
    raw = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    if not raw:
        raise RuntimeError("未認証です。接続設定からGoogleアカウントを認証してください。")
    creds = Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save(creds)
        else:
            raise RuntimeError("認証の有効期限が切れました。Google認証をやり直してください。")
    return creds


def connect_google(client_secrets_path: str) -> None:
    path = Path(client_secrets_path).expanduser()
    if not path.is_file():
        raise ValueError("Google OAuthクライアントJSONファイルを選択してください。")
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
        if "installed" not in info:
            raise ValueError("Google Cloudで『デスクトップアプリ』のOAuthクライアントを作成してください。")
    except json.JSONDecodeError as exc:
        raise ValueError("OAuthクライアントJSONを読み込めません。") from exc
    flow = InstalledAppFlow.from_client_secrets_file(str(path), SCOPES)
    creds = flow.run_local_server(host="127.0.0.1", port=0, open_browser=True,
                                  authorization_prompt_message="ブラウザーでGoogle認証してください: {url}")
    _save(creds)


def disconnect_google() -> None:
    keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
