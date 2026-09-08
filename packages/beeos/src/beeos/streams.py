"""Streaming helpers that leave task ownership with the caller."""

from __future__ import annotations

import codecs
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class TaskEvent:
    event: str
    id: str
    data: str

    def json(self):
        return json.loads(self.data)


def read_chunk(response, size: int, *, streaming=False):
    read1 = getattr(response, "read1", None)
    if callable(read1):
        return read1(size, decode_content=True)
    # urllib3 2.1 lacks read1(). For SSE, read one byte rather than buffering a
    # whole block and delaying a small event until the server closes the stream.
    return response.read(1 if streaming else size, decode_content=True)


def parse_events(chunks, *, max_event_bytes=4 * 1024 * 1024):
    """Parse SSE across arbitrary UTF-8, LF and CRLF chunk boundaries."""
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    pending = ""
    event = ""
    last_id = ""
    data = []
    event_bytes = 0
    for chunk in chunks:
        pending += decoder.decode(chunk)
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            line = line.rstrip("\r")
            event_bytes += len(line.encode("utf-8")) + 1
            if event_bytes > max_event_bytes:
                raise ValueError("Task event exceeds max_event_bytes")
            if not line:
                if data:
                    yield TaskEvent(event or "message", last_id, "\n".join(data))
                event, data, event_bytes = "", [], 0
                continue
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "event":
                event = value
            elif field == "id" and "\x00" not in value:
                last_id = value
            elif field == "data":
                data.append(value)
        if event_bytes + len(pending.encode("utf-8")) > max_event_bytes:
            raise ValueError("Task event exceeds max_event_bytes")
    decoder.decode(b"", final=True)
    # An unframed tail is incomplete. Never promote it to a successful event.
