"""Owner-authorized file lookup and credential-isolated object download."""

import time
from urllib.parse import urlsplit

import urllib3
from beeos_sdk import FilesApi

from .resources import call, require_id, timeout_seconds
from .streams import read_chunk


class Files:
    def __init__(self, api_client):
        self.api = FilesApi(api_client)

    def get(self, file_id: str, *, timeout=30.0):
        return call(self.api.get_file, id=require_id(file_id, "file_id"), timeout=timeout)

    def download(self, file_id: str, *, timeout=30.0, max_bytes=32 * 1024 * 1024,
                 expected_content_type=None, allow_insecure_http=False) -> bytes:
        """Download by file ID. Never forward API credentials to a presigned URL."""
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        deadline = time.monotonic() + timeout_seconds(timeout)
        response = self.get(file_id, timeout=timeout)
        meta = response.data
        if not response.success or meta is None or meta.file_id != file_id or not meta.download_url:
            raise ValueError("File response is missing an authorized download URL")
        url = urlsplit(meta.download_url)
        allowed = {"https", "http"} if allow_insecure_http else {"https"}
        if url.scheme not in allowed or not url.hostname or url.username or url.password:
            raise ValueError("File download requires an HTTPS URL without embedded credentials")
        if meta.size is not None and meta.size > max_bytes:
            raise ValueError("File exceeds max_bytes")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("File download timed out")
        # This separate pool must not inherit access tokens, cookies or client
        # certificates from the authenticated Platform API connection.
        with urllib3.PoolManager() as pool:
            download = pool.request("GET", meta.download_url, headers={}, preload_content=False,
                                    redirect=False, retries=False, timeout=urllib3.Timeout(total=remaining))
            try:
                if not 200 <= download.status < 300:
                    raise RuntimeError(f"File download failed: HTTP {download.status}")
                actual_type = download.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if expected_content_type and actual_type != expected_content_type.lower():
                    raise ValueError("Downloaded file has an unexpected content type")
                result = bytearray()
                while True:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("File download timed out")
                    chunk = read_chunk(download, min(65536, max_bytes - len(result) + 1))
                    if time.monotonic() >= deadline:
                        raise TimeoutError("File download timed out")
                    if not chunk:
                        return bytes(result)
                    result.extend(chunk)
                    if len(result) > max_bytes:
                        raise ValueError("File exceeds max_bytes")
            finally:
                download.close()
                download.release_conn()
