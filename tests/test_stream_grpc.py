"""Offline protocol and message normalization tests; no network/OAuth needed."""

from datetime import datetime, timedelta, timezone

from livechat_guard.stream_grpc import Request, Response, normalize
from livechat_guard.moderation import StreakDetector


def test_proto_request_has_expected_fields():
    request = Request(live_chat_id="CHAT_ID", part=["id", "snippet", "authorDetails"])
    request.page_token = "PAGE"
    parsed = Request.FromString(request.SerializeToString())
    assert parsed.live_chat_id == "CHAT_ID"
    assert parsed.page_token == "PAGE"
    assert parsed.part == ["id", "snippet", "authorDetails"]
    assert Request.DESCRIPTOR.fields_by_name["page_token"].number == 99
    assert Response.DESCRIPTOR.fields_by_name["next_page_token"].number == 100602


def test_normalize_text_and_ignore_nontext():
    response = Response(next_page_token="NEXT")
    message = response.items.add()
    message.id = "M1"
    message.snippet.type = 1
    message.snippet.published_at = "2026-11-09T12:34:56Z"
    message.snippet.text_message_details.message_text = "こんにちは"
    message.author_details.channel_id = "UC000"
    message.author_details.display_name = "Aさん"
    message.author_details.is_chat_moderator = True
    other = response.items.add()
    other.id = "M2"
    other.snippet.type = 15  # Super Chat

    restored = Response.FromString(response.SerializeToString())
    result = normalize(restored)
    assert result["nextPageToken"] == "NEXT"
    assert len(result["items"]) == 1
    assert result["items"][0]["authorDetails"]["channelId"] == "UC000"
    assert result["items"][0]["authorDetails"]["isChatModerator"] is True
    assert result["items"][0]["snippet"]["textMessageDetails"]["messageText"] == "こんにちは"


def test_timestamp_based_streak_even_when_delivered_in_one_batch():
    """Batch arrival does not matter: use published_at, not receive time."""
    response = Response()
    for i, elapsed in enumerate((0, 5, 13, 17, 22), 1):
        item = response.items.add()
        item.id = str(i)
        item.snippet.type = 1
        item.snippet.published_at = (
            datetime(2026, 11, 9, tzinfo=timezone.utc) + timedelta(seconds=elapsed)
        ).isoformat()
        item.author_details.channel_id = "U"
    detector = StreakDetector(10, 3, 5)
    events = []
    for item in normalize(response)["items"]:
        stamp = datetime.fromisoformat(item["snippet"]["publishedAt"])
        events.append(detector.on_comment("U", stamp)[1])
    assert events == [None, None, "warning", None, "limit"]
