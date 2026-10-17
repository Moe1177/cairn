"""HTTPS for the host clients: one keep-alive connection per thread, so a run of requests pays
for TLS once. Standard library only."""

import http.client
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from cairn.errors import CairnError

TIMEOUT = 30.0
SERVER_ERRORS = frozenset({500, 502, 503, 504})


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str]  # lower-case names
    body: bytes


# (method, path with query, headers) -> Response. Tests pass a fake; the default talks HTTPS.
Transport = Callable[[str, str, Mapping[str, str]], Response]


class HttpsTransport:
    """One keep-alive HTTPS connection per thread, reopened when the server drops it."""

    def __init__(self, host: str) -> None:
        self._host = host
        self._local = threading.local()

    def __call__(self, method: str, path: str, headers: Mapping[str, str]) -> Response:
        kept = getattr(self._local, "connection", None)
        try:
            return self._send(kept or self._connect(), method, path, headers)
        except (http.client.HTTPException, OSError) as exc:
            if kept is None:  # a new connection failed: the host is down or unreachable
                raise CairnError(f"couldn't reach {self._host}: {exc}") from exc
        # A kept-alive connection the server closed while idle: one more try on a new one.
        try:
            return self._send(self._connect(), method, path, headers)
        except (http.client.HTTPException, OSError) as exc:
            raise CairnError(f"couldn't reach {self._host}: {exc}") from exc

    def _send(
        self,
        connection: http.client.HTTPSConnection,
        method: str,
        path: str,
        headers: Mapping[str, str],
    ) -> Response:
        try:
            connection.request(method, path, headers=dict(headers))
            reply = connection.getresponse()
            body = reply.read()
        except (http.client.HTTPException, OSError):
            connection.close()
            self._local.connection = None
            raise
        names = {name.lower(): value for name, value in reply.getheaders()}
        return Response(reply.status, names, body)

    def _connect(self) -> http.client.HTTPSConnection:
        connection = http.client.HTTPSConnection(self._host, timeout=TIMEOUT)
        self._local.connection = connection
        return connection


def number(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0


def inside(path: str) -> str:
    """A path inside a repo: no `..` or empty segments, no leading slash."""
    parts = path.split("/")
    if not path or any(part in ("", ".", "..") for part in parts):
        raise CairnError(f"{path!r} isn't a path inside a repo")
    return path


def is_binary(body: bytes) -> bool:
    return b"\x00" in body[:8192]


def text_of(body: bytes) -> str:
    return body.decode("utf-8", errors="replace").removeprefix("\ufeff")
