from types import SimpleNamespace as NS

import pytest
from beeos import BeeOS
from beeos.streams import parse_events, read_chunk
from beeos_sdk.exceptions import ApiException


class Response:
    def __init__(self, chunks=(), status=200, content_type="text/event-stream"):
        self.chunks = iter(chunks)
        self.status = status
        self.headers = {"Content-Type": content_type}
        self.closed = self.released = False

    def read1(self, *args, **kwargs):
        return next(self.chunks, b"")

    def close(self):
        self.closed = True

    def release_conn(self):
        self.released = True


def test_old_urllib3_stream_does_not_buffer_until_eof():
    calls = []
    class LegacyResponse:
        def read(self, size, *, decode_content):
            calls.append((size, decode_content))
            return b"x"
    response = LegacyResponse()
    assert read_chunk(response, 65536, streaming=True) == b"x"
    assert read_chunk(response, 1024) == b"x"
    assert calls == [(1, True), (1024, True)]


def test_sse_split_utf8_crlf_and_noncontiguous_ids():
    raw = 'id: 40\r\nevent: message\r\ndata: {"text":"你好"}\r\n\r\nid: 42\ndata: {}\n\n'.encode()
    events = list(parse_events([bytes([b]) for b in raw]))
    assert [e.id for e in events] == ["40", "42"]
    assert events[0].json() == {"text": "你好"}
    assert list(parse_events([b'data: {"partial":true}'])) == []


def test_sse_size_guard_and_large_batch_of_small_frames():
    with pytest.raises(ValueError, match="max_event_bytes"):
        list(parse_events([b"data: " + b"x" * 30], max_event_bytes=20))
    assert len(list(parse_events([b"data: {}\n\n" * 100], max_event_bytes=20))) == 100


def test_task_events_use_generated_api_and_close_early(monkeypatch):
    with BeeOS(api_key="key") as client:
        response = Response([b"id: 42\ndata: {}\n\n"])
        calls = []
        def stream(**kwargs):
            calls.append(kwargs)
            return response
        monkeypatch.setattr(client.tasks._api, "stream_task_events_without_preload_content", stream)
        events = client.task("agent", "task").events(since=40, timeout=9)
        assert next(events).id == "42"
        events.close()
        assert response.closed and response.released
        assert calls == [{"agent_id": "agent", "task_id": "task", "since": 40, "_request_timeout": 9.0}]


@pytest.mark.parametrize("status,content_type,exception", [(200, "application/json", ValueError), (401, "application/json", ApiException)])
def test_stream_errors_are_not_empty_success(monkeypatch, status, content_type, exception):
    with BeeOS(api_key="key") as client:
        response = Response(status=status, content_type=content_type)
        monkeypatch.setattr(client.tasks._api, "stream_task_events_without_preload_content", lambda **_: response)
        with pytest.raises(exception):
            list(client.task("agent", "task").events())
        assert response.closed and response.released


def test_stream_end_releases_without_waiting_for_eof(monkeypatch):
    with BeeOS(api_key="key") as client:
        response = Response([b"event: end\ndata: {}\n\n"])
        monkeypatch.setattr(client.tasks._api, "stream_task_events_without_preload_content", lambda **_: response)
        assert len(list(client.task("agent", "task").events())) == 1
        assert response.closed and response.released


def file_fixture(monkeypatch, client, *, url="https://objects.example/report", chunks=(b"%PDF-test",), status=200):
    meta = NS(file_id="file", size=None, download_url=url)
    calls = []
    def lookup(**kwargs):
        calls.append(("lookup", kwargs))
        return NS(success=True, data=meta)
    monkeypatch.setattr(client.files.api, "get_file", lookup)
    response = Response(chunks, status=status, content_type="application/pdf")
    class Pool:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def request(self, *args, **kwargs):
            calls.append(("download", args, kwargs))
            return response
    monkeypatch.setattr("beeos.files.urllib3.PoolManager", Pool)
    return meta, calls, response


def test_file_download_is_credential_isolated_and_bounded(monkeypatch):
    with BeeOS(api_key="secret") as client:
        _, calls, response = file_fixture(monkeypatch, client)
        assert client.files.download("file", expected_content_type="application/pdf") == b"%PDF-test"
        assert calls[0][1]["id"] == "file"
        assert calls[1][2]["headers"] == {}
        assert calls[1][2]["redirect"] is False
        assert calls[1][2]["retries"] is False
        assert response.closed and response.released


@pytest.mark.parametrize("url", ["http://objects.example/file", "file:///etc/passwd", "https://user:pass@objects.example/file"])
def test_file_url_rejected_before_download(monkeypatch, url):
    with BeeOS(api_key="key") as client:
        _, calls, _ = file_fixture(monkeypatch, client, url=url)
        with pytest.raises(ValueError, match="HTTPS"):
            client.files.download("file")
        assert len(calls) == 1


def test_download_oversize_closes_stream(monkeypatch):
    with BeeOS(api_key="key") as client:
        _, _, response = file_fixture(monkeypatch, client, chunks=(b"123", b"456"))
        with pytest.raises(ValueError, match="max_bytes"):
            client.files.download("file", max_bytes=4)
        assert response.closed and response.released


def test_wrong_file_identity_does_not_download(monkeypatch):
    with BeeOS(api_key="key") as client:
        meta, calls, _ = file_fixture(monkeypatch, client)
        meta.file_id = "other"
        with pytest.raises(ValueError, match="authorized"):
            client.files.download("file")
        assert len(calls) == 1


@pytest.mark.parametrize("status", [302, 403, 500])
def test_file_http_error_is_not_an_artifact(monkeypatch, status):
    with BeeOS(api_key="key") as client:
        _, _, response = file_fixture(monkeypatch, client, status=status)
        with pytest.raises(RuntimeError, match=f"HTTP {status}"):
            client.files.download("file")
        assert response.closed and response.released
