"""Minimal WebDAV client for a Nextcloud server, plus its settings and stored credentials."""

from __future__ import annotations

import base64
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlparse
from xml.etree import ElementTree

TOKEN_FILENAME = "webdav.token"
PASSWORD_ENVIRONMENT_VARIABLE = "HANDOFF_WEBDAV_PASSWORD"
REQUEST_TIMEOUT_SECONDS = 15.0
USER_AGENT = "handoff-sync (+https://github.com/nedasadamavicius/handoff)"
ERROR_SNIPPET_LENGTH = 200
HTTP_OK = 200
HTTP_CREATED = 201
HTTP_NO_CONTENT = 204
HTTP_MULTI_STATUS = 207
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
HTTP_METHOD_NOT_ALLOWED = 405
HTTP_PRECONDITION_FAILED = 412


class SyncError(Exception):
    pass


class OfflineError(SyncError):
    pass


class AuthError(SyncError):
    pass


class PreconditionFailed(SyncError):
    pass


@dataclass(frozen=True)
class SyncSettings:
    server: str
    username: str
    folder: str = "handoff"


def load_password(root: Path) -> str | None:
    value = os.environ.get(PASSWORD_ENVIRONMENT_VARIABLE)
    if value:
        return value
    token = root / TOKEN_FILENAME
    return token.read_text(encoding="utf-8").strip() if token.exists() else None


def save_password(root: Path, password: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    token = root / TOKEN_FILENAME
    token.write_text(password, encoding="utf-8")
    try:
        token.chmod(0o600)
    except OSError:
        pass


def _clean_etag(value: str | None) -> str:
    if not value:
        return ""
    cleaned = value.strip()
    if cleaned.startswith("W/"):
        cleaned = cleaned[2:]
    return cleaned.strip('"')


def _lowercase_headers(headers) -> dict[str, str]:
    return {name.lower(): value for name, value in headers.items()}


class WebDAVClient:
    def __init__(self, settings: SyncSettings, password: str, timeout: float = REQUEST_TIMEOUT_SECONDS) -> None:
        self.root_url = f"{settings.server.rstrip('/')}/remote.php/dav/files/{quote(settings.username)}"
        self.timeout = timeout
        token = base64.b64encode(f"{settings.username}:{password}".encode()).decode()
        self._auth = f"Basic {token}"

    def _url(self, path: str) -> str:
        return f"{self.root_url}/{quote(path.strip('/'), safe='/')}" if path.strip("/") else self.root_url

    def request(
        self, method: str, path: str, data: bytes | None = None, headers: dict[str, str] | None = None
    ) -> tuple[int, dict[str, str], bytes]:
        http_request = urllib.request.Request(self._url(path), data=data, method=method)
        http_request.add_header("Authorization", self._auth)
        http_request.add_header("User-Agent", USER_AGENT)
        for header_name, header_value in (headers or {}).items():
            http_request.add_header(header_name, header_value)
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout) as response:
                return response.status, _lowercase_headers(response.headers), response.read()
        except urllib.error.HTTPError as error:
            body = error.read()
            if error.code == HTTP_UNAUTHORIZED:
                raise AuthError("Authentication failed; run `handoff sync login`") from error
            if error.code == HTTP_FORBIDDEN:
                snippet = body[:ERROR_SNIPPET_LENGTH].decode("utf-8", errors="replace").strip()
                raise SyncError(f"Server refused the request (403), not a login problem: {snippet}") from error
            if error.code == HTTP_PRECONDITION_FAILED:
                raise PreconditionFailed(path) from error
            return error.code, _lowercase_headers(error.headers), body
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as error:
            raise OfflineError(str(getattr(error, "reason", error))) from error

    def make_collection(self, path: str) -> None:
        status, _, _ = self.request("MKCOL", path)
        if status not in (HTTP_CREATED, HTTP_METHOD_NOT_ALLOWED):
            raise SyncError(f"MKCOL {path} failed ({status})")

    def list_directory(self, path: str) -> dict[str, tuple[str, bool]]:
        body = (
            b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop>'
            b"<d:getetag/><d:resourcetype/></d:prop></d:propfind>"
        )
        status, _, content = self.request("PROPFIND", path, body, {"Depth": "1", "Content-Type": "application/xml"})
        if status == HTTP_NOT_FOUND:
            return {}
        if status not in (HTTP_OK, HTTP_MULTI_STATUS):
            raise SyncError(f"PROPFIND {path} failed ({status})")
        own_path = unquote(urlparse(self._url(path)).path).rstrip("/")
        entries: dict[str, tuple[str, bool]] = {}
        for item in ElementTree.fromstring(content).findall("{DAV:}response"):
            item_path = unquote(urlparse(item.findtext("{DAV:}href") or "").path).rstrip("/")
            if item_path == own_path:
                continue
            etag = _clean_etag(item.findtext(".//{DAV:}getetag"))
            is_directory = item.find(".//{DAV:}resourcetype/{DAV:}collection") is not None
            entries[item_path.rsplit("/", 1)[-1]] = (etag, is_directory)
        return entries

    def download(self, path: str) -> bytes:
        status, _, content = self.request("GET", path)
        if status != HTTP_OK:
            raise SyncError(f"GET {path} failed ({status})")
        return content

    def upload(self, path: str, data: bytes, etag: str | None = None) -> str:
        headers = {"If-Match": f'"{etag}"'} if etag else {"If-None-Match": "*"}
        status, response_headers, _ = self.request("PUT", path, data, headers)
        if status not in (HTTP_OK, HTTP_CREATED, HTTP_NO_CONTENT):
            raise SyncError(f"PUT {path} failed ({status})")
        new_etag = _clean_etag(response_headers.get("oc-etag") or response_headers.get("etag"))
        if new_etag:
            return new_etag
        parent, _, name = path.rpartition("/")
        return self.list_directory(parent).get(name, ("", False))[0]
