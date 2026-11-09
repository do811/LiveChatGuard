"""Small wrapper around the official YouTube Data API v3."""

from __future__ import annotations

import httplib2
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build

from .auth import get_credentials


class YouTubeAPI:
    def __init__(self):
        creds = get_credentials()
        authorized_http = AuthorizedHttp(creds, http=httplib2.Http(timeout=25))
        self.service = build("youtube", "v3", http=authorized_http, cache_discovery=False)

    def active_broadcasts(self) -> list[dict]:
        result: list[dict] = []
        page = None
        while True:
            arguments = {"part": "id,snippet,status", "mine": True, "maxResults": 50}
            if page:
                arguments["pageToken"] = page
            response = self.service.liveBroadcasts().list(**arguments).execute()
            for item in response.get("items", []):
                chat_id = item.get("snippet", {}).get("liveChatId")
                status = item.get("status", {}).get("lifeCycleStatus")
                if chat_id and status == "live":
                    result.append({
                        "id": item["id"],
                        "title": item.get("snippet", {}).get("title", "無題の配信"),
                        "chat_id": chat_id,
                    })
            page = response.get("nextPageToken")
            if not page:
                break
        return result

    def list_messages(self, chat_id: str, page_token: str | None = None) -> dict:
        kwargs = {"liveChatId": chat_id, "part": "id,snippet,authorDetails", "maxResults": 200}
        if page_token:
            kwargs["pageToken"] = page_token
        return self.service.liveChatMessages().list(**kwargs).execute()

    def warn(self, chat_id: str, display_name: str) -> None:
        # Avoid repeating the user's arbitrary chat message in our warning.
        safe_name = display_name.replace("\r", " ").replace("\n", " ")[:60]
        text = f"@{safe_name} さん、短時間での連続投稿を検知しました。連投を控えてください。"
        self.service.liveChatMessages().insert(
            part="snippet", body={"snippet": {
                "liveChatId": chat_id,
                "type": "textMessageEvent",
                "textMessageDetails": {"messageText": text},
            }}
        ).execute()

    def ban(self, chat_id: str, channel_id: str, *, seconds: int | None = None) -> str:
        snippet = {"liveChatId": chat_id,
                   "type": "temporary" if seconds is not None else "permanent",
                   "bannedUserDetails": {"channelId": channel_id}}
        if seconds is not None:
            snippet["banDurationSeconds"] = str(seconds)
        result = self.service.liveChatBans().insert(part="snippet", body={"snippet": snippet}).execute()
        return str(result.get("id", ""))
