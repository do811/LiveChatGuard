"""YouTube Live Chat server stream using gRPC and a small compatible protobuf schema.

The field numbers below follow Google's public stream_list.proto. The schema includes
only the fields this app needs: protobuf wire compatibility permits unknown fields.
No generated *_pb2.py or grpcio-tools is necessary at installation time.

See https://developers.google.com/youtube/data/live/streaming-live-chat
"""

from __future__ import annotations

from threading import Event
from typing import Iterator

import grpc
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory



# Proto2 field numbers from the YouTube public streaming protocol.
def _message_class():
    fd = descriptor_pb2.FileDescriptorProto()
    fd.name = "livechat_guard_stream.proto"
    fd.package = "youtube.api.v3"
    fd.syntax = "proto2"

    def add_message(name: str):
        return fd.message_type.add(name=name)

    def field(m, name, num, typ, *, repeated=False, message=None):
        f = m.field.add(name=name, number=num)
        f.label = (f.LABEL_REPEATED if repeated else f.LABEL_OPTIONAL)
        f.type = typ
        if message:
            f.type_name = f".youtube.api.v3.{message}"
        return f

    s = descriptor_pb2.FieldDescriptorProto
    req = add_message("LiveChatMessageListRequest")
    field(req, "live_chat_id", 1, s.TYPE_STRING)
    field(req, "page_token", 99, s.TYPE_STRING)
    field(req, "part", 100, s.TYPE_STRING, repeated=True)

    res = add_message("LiveChatMessageListResponse")
    field(res, "offline_at", 2, s.TYPE_STRING)
    field(res, "next_page_token", 100602, s.TYPE_STRING)
    field(res, "items", 1007, s.TYPE_MESSAGE, repeated=True, message="LiveChatMessage")

    msg = add_message("LiveChatMessage")
    field(msg, "id", 101, s.TYPE_STRING)
    field(msg, "snippet", 2, s.TYPE_MESSAGE, message="LiveChatMessageSnippet")
    field(msg, "author_details", 3, s.TYPE_MESSAGE, message="LiveChatMessageAuthorDetails")

    auth = add_message("LiveChatMessageAuthorDetails")
    field(auth, "channel_id", 10101, s.TYPE_STRING)
    field(auth, "display_name", 103, s.TYPE_STRING)
    field(auth, "is_chat_owner", 5, s.TYPE_BOOL)
    field(auth, "is_chat_sponsor", 6, s.TYPE_BOOL)
    field(auth, "is_chat_moderator", 7, s.TYPE_BOOL)

    snip = add_message("LiveChatMessageSnippet")
    field(snip, "type", 1, s.TYPE_INT32)  # enum 1 = TEXT_MESSAGE_EVENT
    field(snip, "author_channel_id", 301, s.TYPE_STRING)
    field(snip, "published_at", 4, s.TYPE_STRING)
    field(snip, "display_message", 16, s.TYPE_STRING)
    field(snip, "text_message_details", 19, s.TYPE_MESSAGE, message="LiveChatTextMessageDetails")

    detail = add_message("LiveChatTextMessageDetails")
    field(detail, "message_text", 1, s.TYPE_STRING)

    svc = fd.service.add(name="V3DataLiveChatMessageService")
    method = svc.method.add(name="StreamList")
    method.input_type = ".youtube.api.v3.LiveChatMessageListRequest"
    method.output_type = ".youtube.api.v3.LiveChatMessageListResponse"
    method.server_streaming = True

    pool = descriptor_pool.DescriptorPool()
    pool.Add(fd)
    request_class = message_factory.GetMessageClass(
        pool.FindMessageTypeByName("youtube.api.v3.LiveChatMessageListRequest")
    )
    response_class = message_factory.GetMessageClass(
        pool.FindMessageTypeByName("youtube.api.v3.LiveChatMessageListResponse")
    )
    return request_class, response_class


Request, Response = _message_class()


def normalize(response) -> dict:
    """Convert gRPC proto fields to the REST-shaped dict used by the worker."""
    items = []
    for msg in response.items:
        if msg.snippet.type != 1:  # Only ordinary text comments trigger moderation.
            continue
        details = msg.author_details
        snippet = msg.snippet
        items.append({
            "id": msg.id,
            "snippet": {
                "type": "textMessageEvent",
                "publishedAt": snippet.published_at,
                "authorChannelId": snippet.author_channel_id,
                "displayMessage": snippet.display_message,
                "textMessageDetails": {"messageText": snippet.text_message_details.message_text},
            },
            "authorDetails": {
                "channelId": details.channel_id,
                "displayName": details.display_name,
                "isChatOwner": details.is_chat_owner,
                "isChatModerator": details.is_chat_moderator,
                "isChatSponsor": details.is_chat_sponsor,
            },
        })
    return {"items": items, "nextPageToken": response.next_page_token,
            "offlineAt": response.offline_at}


class LiveChatStream:
    """One long-lived stream. Reconnecting is controlled by the monitor worker."""

    def __init__(self):
        self._call = None

    def cancel(self):
        if self._call is not None:
            self._call.cancel()

    def responses(self, chat_id: str, page_token: str | None, stop: Event) -> Iterator[dict]:
        if stop.is_set():
            return
        from .auth import get_credentials

        token = get_credentials().token  # Refreshes expired token when necessary.
        request = Request(live_chat_id=chat_id, part=["id", "snippet", "authorDetails"])
        if page_token:
            request.page_token = page_token
        with grpc.secure_channel("youtube.googleapis.com:443", grpc.ssl_channel_credentials()) as ch:
            method = ch.unary_stream(
                "/youtube.api.v3.V3DataLiveChatMessageService/StreamList",
                request_serializer=lambda v: v.SerializeToString(),
                response_deserializer=Response.FromString,
            )
            self._call = method(
                request, metadata=(("authorization", "Bearer " + token),),
                wait_for_ready=False,
            )
            try:
                if stop.is_set():
                    self._call.cancel()
                    return
                for response in self._call:
                    if stop.is_set():
                        break
                    yield normalize(response)
            finally:
                self._call.cancel()
                self._call = None
