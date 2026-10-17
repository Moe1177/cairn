"""A read-only GitHub REST client (github.com or Enterprise): code search and file lookups.

Standard library only. Each thread keeps one HTTPS connection open, so a run of requests pays
for TLS once. Rate limits are waited out (up to a cap) instead of failing the caller: code
search allows only 10 requests a minute, and an agent's work should slow down, not break.
"""

import http.client
import json
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import quote, urlencode

from cairn.errors import CairnError
from cairn.remote.auth import check_host
from cairn.security.redact import redact

API_VERSION = "2022-11-28"
USER_AGENT = "cairn"
TIMEOUT = 30.0
MAX_WAIT = 120.0  # seconds one call may wait for a rate limit before giving up
_RETRIES = 3
_REPO = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/(?!\.{1,2}$)[A-Za-z0-9._-]{1,100}$")
_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
# Printable ASCII only: a CR or LF would let a token split the Authorization header.
_TOKEN = re.compile(r"^[\x21-\x7e]{1,512}$")
# GitHub's secondary limits (too many requests at once) say so in the body, not the headers.
_SECONDARY = re.compile(rb"secondary rate limit|abuse", re.IGNORECASE)
SECONDARY_WAIT = 60.0  # GitHub asks for at least a minute when it doesn't say how long
_TEXT_MATCH = "application/vnd.github.text-match+json"


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str]  # lower-case names
    body: bytes


# (method, path with query, headers) -> Response. Tests pass a fake; the default talks HTTPS.
Transport = Callable[[str, str, Mapping[str, str]], Response]


@dataclass(frozen=True)
class CodeHit:
    repo: str  # owner/name
    path: str
    fragments: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchPage:
    hits: tuple[CodeHit, ...]
    total: int
    ms: float  # time spent on the request itself
    waited: float = 0.0  # seconds spent waiting out rate limits first


@dataclass(frozen=True)
class RepoInfo:
    name: str  # owner/name
    default_branch: str
    language: str = ""
    topics: tuple[str, ...] = ()
    archived: bool = False
    fork: bool = False
    pushed: str = ""  # ISO time of the last push
    description: str = ""


class GitHub:
    def __init__(
        self,
        token: str,
        *,
        host: str = "github.com",
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        max_wait: float = MAX_WAIT,
    ) -> None:
        if not _TOKEN.fullmatch(token):
            raise CairnError("the GitHub token has spaces or control characters in it")
        self._api_host, self._prefix = api_base(check_host(host))
        self._token = token
        self._transport = transport or _HttpsTransport(self._api_host)
        self._sleep = sleep
        self._clock = clock
        self._max_wait = max_wait
        self._remaining: dict[str, int] = {}  # rate limit resource (core, search) -> requests left

    def search_code(self, query: str, *, per_page: int = 10) -> SearchPage:
        """GitHub's code search, best match first, with the matched fragments."""
        params = urlencode({"q": query, "per_page": max(1, min(per_page, 100))})
        response, ms, waited = self._get(f"/search/code?{params}", accept=_TEXT_MATCH)
        if response.status == 422:  # a query GitHub can't run (too long, only operators)
            return SearchPage((), 0, ms, waited)
        data = _json(_checked(response))
        hits = tuple(_hit(item) for item in data.get("items", []) if _hit_ok(item))
        return SearchPage(hits, int(data.get("total_count") or 0), ms, waited)

    def search_repos(self, query: str, *, per_page: int = 10) -> tuple[tuple[str, ...], float]:
        """GitHub's repository search, best match first: (owner/name of each, ms)."""
        params = urlencode({"q": query, "per_page": max(1, min(per_page, 100))})
        response, ms, _ = self._get(f"/search/repositories?{params}")
        if response.status == 422:
            return (), ms
        items = _json(_checked(response)).get("items", [])
        return tuple(i["full_name"] for i in items if _repo_ok(i)), ms

    def file_exists(self, repo: str, path: str) -> bool:
        """Whether `path` is a file on `repo`'s default branch (what code search indexes)."""
        response, _, _ = self._get(
            f"/repos/{_repo(repo)}/contents/{quote(_inside(path), safe='/')}"
        )
        if response.status == 404:
            return False
        if 300 <= response.status < 400:
            raise CairnError(f"{repo} has moved (renamed or transferred): update the key")
        data = _json(_checked(response))
        return isinstance(data, dict) and data.get("type") == "file"

    def read_file(self, repo: str, path: str, *, max_bytes: int = 200_000) -> str | None:
        """A file's text on `repo`'s default branch: None when it isn't there, is binary, or
        is longer than `max_bytes` (an agent reads prior art, not datasets)."""
        url = f"/repos/{_repo(repo)}/contents/{quote(_inside(path), safe='/')}"
        response, _, _ = self._get(url, accept="application/vnd.github.raw+json")
        if response.status == 404:
            return None
        if 300 <= response.status < 400:
            raise CairnError(f"{repo} has moved (renamed or transferred)")
        body = _checked(response).body
        if response.headers.get("content-type", "").startswith("application/json"):
            return None  # a folder: GitHub lists its entries instead of sending a file
        if len(body) > max_bytes or b"\x00" in body[:8192]:
            return None
        return body.decode("utf-8", errors="replace").removeprefix("﻿")

    def list_repos(self, owner: str, *, page: int = 1, per_page: int = 100) -> tuple[RepoInfo, ...]:
        """One page of an org's repos (a user's when `owner` is no org), last pushed first."""
        params = urlencode({"per_page": max(1, min(per_page, 100)), "page": page, "sort": "pushed"})
        owner = _owner(owner)
        response, _, _ = self._get(f"/orgs/{owner}/repos?type=all&{params}")
        if response.status == 404:
            response, _, _ = self._get(f"/users/{owner}/repos?type=all&{params}")
        try:
            items = json.loads(_checked(response).body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise CairnError(
                f"GitHub sent a repo list cairn can't read ({response.status})"
            ) from exc
        return (
            tuple(_repo_info(item) for item in items if _repo_ok(item))
            if isinstance(items, list)
            else ()
        )

    def tree(self, repo: str, ref: str) -> tuple[tuple[str, ...], bool]:
        """Every file path on branch `ref`, and whether GitHub cut the list short (a repo over
        100,000 files). An empty repo has no tree: ((), False)."""
        url = f"/repos/{_repo(repo)}/git/trees/{quote(ref, safe='')}?recursive=1"
        response, _, _ = self._get(url)
        if response.status in (404, 409):  # 409: the repo is empty
            return (), False
        if 300 <= response.status < 400:
            raise CairnError(f"{repo} has moved (renamed or transferred)")
        data = _json(_checked(response))
        entries = data.get("tree")
        paths = tuple(
            entry["path"]
            for entry in (entries if isinstance(entries, list) else [])
            if isinstance(entry, dict)
            and entry.get("type") == "blob"
            and isinstance(entry.get("path"), str)
        )
        return paths, bool(data.get("truncated"))

    def remaining(self, resource: str = "core") -> int | None:
        """Requests left in the rate limit `resource`, as GitHub last said (None: not yet)."""
        return self._remaining.get(resource)

    def _get(
        self, path: str, *, accept: str = "application/vnd.github+json"
    ) -> tuple[Response, float, float]:
        """(response, ms of the last request, seconds waited for rate limits). Backoff after a
        server error counts in ms: that is GitHub being slow, not a limit being waited out."""
        headers = {
            "Accept": accept,
            "Authorization": f"Bearer {self._token}",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": API_VERSION,
        }
        waited = 0.0
        slow = 0.0  # server-error backoff, seconds
        for attempt in range(_RETRIES + 1):
            started = time.perf_counter()
            response = self._transport("GET", self._prefix + path, headers)
            ms = (time.perf_counter() - started + slow) * 1000
            self._note_remaining(response.headers)
            limit = self._rate_limit_wait(response)
            if attempt == _RETRIES or (limit is None and response.status not in _SERVER_ERRORS):
                return response, ms, waited
            if limit is None:  # GitHub times out heavy requests now and then
                self._sleep(2.0**attempt)
                slow += 2.0**attempt
                continue
            if waited + limit > self._max_wait:
                raise CairnError(
                    f"GitHub's rate limit needs a {limit:.0f}s wait, longer than cairn waits: "
                    "try again in a few minutes"
                )
            self._sleep(limit)
            waited += limit
        raise AssertionError("unreachable")

    def _note_remaining(self, headers: Mapping[str, str]) -> None:
        left = headers.get("x-ratelimit-remaining", "")
        if left.isdigit():
            self._remaining[headers.get("x-ratelimit-resource", "core")] = int(left)

    def _rate_limit_wait(self, response: Response) -> float | None:
        """Seconds a rate-limited response asks for, or None when it isn't one."""
        status, headers = response.status, response.headers
        if status not in (403, 429):
            return None
        if "retry-after" in headers:
            return max(1.0, _number(headers["retry-after"]))
        if _exhausted(headers):
            return max(1.0, _number(headers.get("x-ratelimit-reset", "0")) - self._clock() + 1)
        if _SECONDARY.search(response.body):
            return SECONDARY_WAIT
        return None


_SERVER_ERRORS = frozenset({500, 502, 503, 504})


def api_base(host: str) -> tuple[str, str]:
    """(API host, path prefix) for a GitHub host: github.com, GHE.com data residency
    (`acme.ghe.com` -> `api.acme.ghe.com`), or GitHub Enterprise Server (`/api/v3`)."""
    if host in ("github.com", "api.github.com"):
        return "api.github.com", ""
    if host.endswith(".ghe.com"):
        return (host if host.startswith("api.") else f"api.{host}"), ""
    return host, "/api/v3"


def _exhausted(headers: Mapping[str, str]) -> bool:
    return headers.get("x-ratelimit-remaining") == "0"


def _number(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0


def _repo(repo: str) -> str:
    if not _REPO.fullmatch(repo):
        raise CairnError(f"{repo!r} isn't a GitHub repo (owner/name)")
    return repo


def _owner(owner: str) -> str:
    if not _OWNER.fullmatch(owner):
        raise CairnError(f"{owner!r} isn't a GitHub org or user name")
    return owner


def _repo_ok(item: object) -> bool:
    return (
        isinstance(item, dict)
        and isinstance(item.get("full_name"), str)
        and _REPO.fullmatch(item["full_name"]) is not None
        and isinstance(item.get("default_branch"), str)
    )


def _repo_info(item: dict) -> RepoInfo:
    topics = item.get("topics")
    return RepoInfo(
        name=item["full_name"],
        default_branch=item["default_branch"],
        language=_text(item.get("language")),
        topics=tuple(t for t in (topics if isinstance(topics, list) else []) if isinstance(t, str)),
        archived=item.get("archived") is True,
        fork=item.get("fork") is True,
        pushed=_text(item.get("pushed_at")),
        description=_text(item.get("description")),
    )


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _inside(path: str) -> str:
    """A path inside a repo: no `..` or empty segments, no leading slash."""
    parts = path.split("/")
    if not path or any(part in ("", ".", "..") for part in parts):
        raise CairnError(f"{path!r} isn't a path inside a repo")
    return path


def _checked(response: Response) -> Response:
    if response.status == 401:
        raise CairnError("GitHub rejected the token: log in again with `gh auth login`")
    if response.status >= 400:
        try:
            message = str(_json(response).get("message") or "")
        except CairnError:
            message = ""
        raise CairnError(f"GitHub answered {response.status}: {redact(message)[:200]}")
    return response


def _json(response: Response) -> dict:
    try:
        data = json.loads(response.body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise CairnError(f"GitHub sent a reply cairn can't read ({response.status})") from exc
    return data if isinstance(data, dict) else {}


def _hit_ok(item: object) -> bool:
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        return False
    repository = item.get("repository")
    return isinstance(repository, dict) and isinstance(repository.get("full_name"), str)


def _hit(item: dict) -> CodeHit:
    matches = item.get("text_matches")
    fragments = tuple(
        m["fragment"]
        for m in (matches if isinstance(matches, list) else [])
        if isinstance(m, dict) and isinstance(m.get("fragment"), str)
    )
    return CodeHit(repo=item["repository"]["full_name"], path=item["path"], fragments=fragments)


class _HttpsTransport:
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
