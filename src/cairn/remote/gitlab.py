"""A read-only GitLab REST client (gitlab.com or self-managed, API v4): the questions cairn asks
GitHub, asked in GitLab's terms.

A group's projects include its subgroups', so a repo's name is its full path
(`acme/platform/api`). Code search across a group needs GitLab's advanced search (a paid tier on
gitlab.com, Elasticsearch or Zoekt when self-managed); without it, a search says so instead of
finding nothing. Rate limits are waited out (up to a cap), as with GitHub.
"""

import json
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlencode

from cairn.errors import CairnError
from cairn.remote.auth import check_host
from cairn.remote.host import CodeHit, RepoInfo, SearchPage
from cairn.remote.transport import (
    SERVER_ERRORS,
    HttpsTransport,
    Response,
    Transport,
    inside,
    is_binary,
    number,
    text_of,
)
from cairn.security.redact import redact

USER_AGENT = "cairn"
MAX_WAIT = 120.0  # seconds one call may wait for a rate limit before giving up
TREE_PAGES = 300  # 30,000 entries, folders included: a bigger tree is cut short
WINDOW = 60.0  # gitlab.com's limits refill every minute: only a longer wait is a budget
ROOT_PAGES = 10  # a cut tree's root listing: its folders come first, then its files
_TREE_WORKERS = 8  # one pool per client: a whole org's tree pages share it and its connections
_RETRIES = 3
_SEGMENT = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,254}"
_GROUP = re.compile(rf"^{_SEGMENT}(?:/{_SEGMENT}){{0,19}}$")
_PROJECT = re.compile(rf"^{_SEGMENT}(?:/{_SEGMENT}){{1,20}}$")
_TOKEN = re.compile(r"^[\x21-\x7e]{1,512}$")
_ORG_QUALIFIER = re.compile(r"(?:^|\s)org:(\S+)")
_LANGUAGE = re.compile(r"(?i)(?:^|(?<=\s))language:(\S+)")
# GitHub's language: as GitLab's extension: (advanced search has no language qualifier).
_EXTENSIONS = {
    "c": "c",
    "c#": "cs",
    "c++": "cpp",
    "csharp": "cs",
    "go": "go",
    "java": "java",
    "javascript": "js",
    "kotlin": "kt",
    "php": "php",
    "python": "py",
    "ruby": "rb",
    "rust": "rs",
    "scala": "scala",
    "shell": "sh",
    "swift": "swift",
    "typescript": "ts",
}


class GitLab:
    def __init__(
        self,
        token: str,
        *,
        host: str = "gitlab.com",
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        max_wait: float = MAX_WAIT,
    ) -> None:
        """`token` may be empty only to read public groups (cairn's own lookup always finds
        one or says how to log in)."""
        if token and not _TOKEN.fullmatch(token):
            raise CairnError("the GitLab token has spaces or control characters in it")
        self._host = check_host(host)
        self._token = token
        self._transport = transport or HttpsTransport(self._host)
        self._sleep = sleep
        self._clock = clock
        self._max_wait = max_wait
        self._limit: tuple[int, float] | None = None  # (requests left, unix time it refills)
        self._lock = threading.Lock()
        self._projects: dict[int, str] = {}  # project id -> full path, learnt from listings
        self._branches: dict[str, str] = {}  # full path (lower case) -> default branch
        self._pool = ThreadPoolExecutor(_TREE_WORKERS, thread_name_prefix="cairn-tree")

    def search_code(self, query: str, *, per_page: int = 10) -> SearchPage:
        """The group's code search (advanced search), best match first, with the matched
        lines."""
        group, words = _scoped(query)
        params = urlencode({"scope": "blobs", "search": words, "per_page": _per_page(per_page)})
        response, ms, waited = self._get(f"/groups/{_id(group)}/search?{params}")
        if response.status == 400 and b"scope" in response.body.lower():
            raise CairnError(
                f"{self._host} can't search code across {group}: that needs GitLab's advanced "
                "search (a paid tier on gitlab.com, Elasticsearch or Zoekt when self-managed)"
            )
        items = _list(self._checked(response))
        hits = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                continue
            repo = self._project_name(item.get("project_id"))
            if repo:
                data = item.get("data")
                hits.append(CodeHit(repo, item["path"], (data,) if isinstance(data, str) else ()))
        total = response.headers.get("x-total", "")
        return SearchPage(tuple(hits), int(total) if total.isdigit() else len(hits), ms, waited)

    def search_repos(self, query: str, *, per_page: int = 10) -> tuple[tuple[str, ...], float]:
        """The group's projects matching the words, best first: (full path of each, ms)."""
        group, words = _scoped(query)
        params = urlencode(
            {
                "search": words,
                "include_subgroups": "true",
                "with_shared": "false",
                "archived": "false",
                "order_by": "similarity",
                "per_page": _per_page(per_page),
            }
        )
        response, ms, _ = self._get(f"/groups/{_id(group)}/projects?{params}")
        infos = [self._info(i) for i in _list(self._checked(response)) if _project_ok(i)]
        return tuple(info.name for info in infos), ms

    def file_exists(self, repo: str, path: str) -> bool:
        """Whether `path` is a file on `repo`'s default branch."""
        response, _, _ = self._get(self._file_url(repo, path), method="HEAD")
        if response.status == 404:
            return False
        self._checked(response)
        return True

    def read_file(self, repo: str, path: str, *, max_bytes: int = 200_000) -> str | None:
        """A file's text on `repo`'s default branch: None when it isn't there (a folder isn't
        a file), is binary, or is longer than `max_bytes`."""
        response, _, _ = self._get(self._file_url(repo, path, raw=True))
        if response.status == 404:
            return None
        body = self._checked(response).body
        if len(body) > max_bytes or is_binary(body):
            return None
        return text_of(body)

    def list_repos(self, owner: str, *, page: int = 1, per_page: int = 100) -> tuple[RepoInfo, ...]:
        """One page of a group's projects, its subgroups' included (a user's when `owner` is no
        group), last active first. Archived projects are left out; an empty one (no branch
        yet) is kept, so a short page still means the last one."""
        common = {
            "per_page": _per_page(per_page),
            "page": page,
            "archived": "false",
            "order_by": "last_activity_at",
            "sort": "desc",
        }
        group = urlencode({**common, "include_subgroups": "true", "with_shared": "false"})
        response, _, _ = self._get(f"/groups/{_id(_group(owner))}/projects?{group}")
        if response.status == 404 and "/" not in owner:
            response, _, _ = self._get(f"/users/{_id(owner)}/projects?{urlencode(common)}")
        items = _list(self._checked(response))
        return tuple(self._info(item) for item in items if _project_ok(item))

    def tree(self, repo: str, ref: str) -> tuple[tuple[str, ...], bool]:
        """Every file path on branch `ref`, and whether the list was cut short (over
        TREE_PAGES pages of 100). An empty repo has no tree: ((), False). A page going
        missing partway (the branch deleted meanwhile) fails the read rather than cut it.

        GitLab lists a tree 100 entries a page, every folder before any file, so pages are read
        side by side. A cut list also gets the root's own files, so a repo's top-level manifests
        are never the part left out."""
        base = f"/projects/{_id(_project(repo))}/repository/tree?"
        if not ref:  # an empty project
            return (), False

        def page(n: int, *, recursive: bool = True) -> Response:
            params = {"ref": ref, "per_page": 100, "page": n}
            query = urlencode({"recursive": "true", **params} if recursive else params)
            return self._checked(self._get(base + query)[0], allow=(404,))

        first = page(1)
        if first.status == 404:  # an empty repo, or a branch gone since the listing
            return (), False
        responses = [first]
        total = first.headers.get("x-total-pages", "")
        if total.isdigit():  # every page is known
            responses += self._pool.map(page, range(2, min(int(total), TREE_PAGES) + 1))
            cut = int(total) > TREE_PAGES
        else:  # GitLab leaves totals out of lists over 10,000: read waves until one ends
            cut = _more(first)
            while cut and len(responses) < TREE_PAGES:
                after = len(responses) + 1
                wave = range(after, min(after + _TREE_WORKERS, TREE_PAGES + 1))
                got = list(self._pool.map(page, wave))
                responses += got
                cut = all(_more(r) for r in got)
        if any(r.status == 404 for r in responses):
            raise CairnError(f"{repo}'s tree changed while cairn read it")
        if cut:  # the root's own files, past its folders
            root = [page(1, recursive=False)]
            while _more(root[-1]) and len(root) < ROOT_PAGES:
                root.append(page(int(root[-1].headers["x-next-page"]), recursive=False))
            responses += [r for r in root if r.status != 404]
        paths = dict.fromkeys(
            entry["path"]
            for response in responses
            for entry in _list(response)
            if isinstance(entry, dict)
            and entry.get("type") == "blob"
            and isinstance(entry.get("path"), str)
        )
        return tuple(paths), cut

    def prefetch(self, repo: str, paths: Sequence[str]) -> None:
        """Nothing to do: the API reads each file on its own."""

    def remaining(self, resource: str = "core") -> int | None:
        """Requests left before the rate limit, as GitLab last said. None when it hasn't said
        or the limit refills within a minute (gitlab.com's do): a short wait isn't a budget."""
        with self._lock:
            limit = self._limit
        if limit is None or limit[1] - self._clock() <= WINDOW:
            return None
        return limit[0]

    def _checked(self, response: Response, *, allow: tuple[int, ...] = ()) -> Response:
        if response.status in allow:
            return response
        return _checked(response, self._host, token=bool(self._token))

    def _file_url(self, repo: str, path: str, *, raw: bool = False) -> str:
        ref = self._branches.get(repo.lower()) or "HEAD"
        name = quote(inside(path), safe="")
        return (
            f"/projects/{_id(_project(repo))}/repository/files/{name}"
            + ("/raw" if raw else "")
            + f"?{urlencode({'ref': ref})}"
        )

    def _info(self, item: dict) -> RepoInfo:
        name, branch = item["path_with_namespace"], item.get("default_branch") or ""
        with self._lock:
            if isinstance(item.get("id"), int):
                self._projects[item["id"]] = name
            self._branches[name.lower()] = branch
        topics = item.get("topics") or item.get("tag_list")
        return RepoInfo(
            name=name,
            default_branch=branch,
            topics=tuple(
                t for t in (topics if isinstance(topics, list) else []) if isinstance(t, str)
            ),
            archived=item.get("archived") is True,
            fork=isinstance(item.get("forked_from_project"), dict),
            pushed=_text(item.get("last_activity_at")),
            description=_text(item.get("description")),
        )

    def _project_name(self, project_id: object) -> str:
        """A search hit's project, by id: from a listing already read, else asked once."""
        if not isinstance(project_id, int):
            return ""
        with self._lock:
            known = self._projects.get(project_id)
        if known is not None:
            return known
        response, _, _ = self._get(f"/projects/{project_id}")
        item = {} if response.status == 404 else _json(self._checked(response))
        name = self._info(item).name if _project_ok(item) else ""
        with self._lock:
            self._projects[project_id] = name
        return name

    def _get(self, path: str, *, method: str = "GET") -> tuple[Response, float, float]:
        """(response, ms of the last request, seconds waited for rate limits)."""
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        waited = 0.0
        slow = 0.0  # server-error backoff, seconds
        for attempt in range(_RETRIES + 1):
            started = time.perf_counter()
            response = self._transport(method, "/api/v4" + path, headers)
            ms = (time.perf_counter() - started + slow) * 1000
            self._note_limit(response.headers)
            limit = self._rate_limit_wait(response)
            if attempt == _RETRIES or (limit is None and response.status not in SERVER_ERRORS):
                return response, ms, waited
            if limit is None:
                self._sleep(2.0**attempt)
                slow += 2.0**attempt
                continue
            if waited + limit > self._max_wait:
                raise CairnError(
                    f"{self._host}'s rate limit needs a {limit:.0f}s wait, longer than cairn "
                    "waits: try again in a few minutes"
                )
            self._sleep(limit)
            waited += limit
        raise AssertionError("unreachable")

    def _note_limit(self, headers: Mapping[str, str]) -> None:
        left, reset = headers.get("ratelimit-remaining", ""), headers.get("ratelimit-reset", "")
        if left.isdigit() and reset.isdigit():
            with self._lock:
                self._limit = (int(left), float(reset))

    def _rate_limit_wait(self, response: Response) -> float | None:
        if response.status != 429:
            return None
        headers = response.headers
        if "retry-after" in headers:
            return max(1.0, number(headers["retry-after"]))
        if "ratelimit-reset" in headers:
            return max(1.0, number(headers["ratelimit-reset"]) - self._clock() + 1)
        return WINDOW


def _scoped(query: str) -> tuple[str, str]:
    """(group, words) of a query in GitHub's syntax: its `org:` qualifier is the group."""
    found = _ORG_QUALIFIER.search(query)
    if found is None:
        raise CairnError("a GitLab search needs a group to search in (org:<group>)")
    words = _LANGUAGE.sub(_extension, _ORG_QUALIFIER.sub(" ", query))
    return _group(found.group(1)), " ".join(words.split())


def _extension(found: re.Match[str]) -> str:
    extension = _EXTENSIONS.get(found.group(1).lower())
    return f"extension:{extension}" if extension else ""


def _per_page(per_page: int) -> int:
    return max(1, min(per_page, 100))


def _id(path: str) -> str:
    """A group or project as GitLab's API names it in a URL: its full path, encoded."""
    return quote(path, safe="")


def _group(group: str) -> str:
    if not _GROUP.fullmatch(group):
        raise CairnError(f"{group!r} isn't a GitLab group or user name")
    return group


def _project(repo: str) -> str:
    if not _PROJECT.fullmatch(repo):
        raise CairnError(f"{repo!r} isn't a GitLab project (group/name)")
    return repo


def _project_ok(item: object) -> bool:
    return (
        isinstance(item, dict)
        and isinstance(item.get("path_with_namespace"), str)
        and _PROJECT.fullmatch(item["path_with_namespace"]) is not None
        and isinstance(item.get("default_branch"), str | None)  # an empty project has none
    )


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _more(response: Response) -> bool:
    return response.headers.get("x-next-page", "").isdigit()


def _checked(response: Response, host: str, *, token: bool = True) -> Response:
    if response.status == 401:
        login = f"`glab auth login --hostname {host}`"
        raise CairnError(
            f"GitLab rejected the token: log in again with {login}"
            if token
            else f"GitLab needs a token for that: run {login}, or set GITLAB_TOKEN"
        )
    if response.status >= 400:
        try:
            data = _json(response)
            message = str(data.get("message") or data.get("error") or "")
        except CairnError:
            message = ""
        raise CairnError(f"GitLab answered {response.status}: {redact(message)[:200]}")
    return response


def _decoded(response: Response) -> object:
    try:
        return json.loads(response.body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise CairnError(f"GitLab sent a reply cairn can't read ({response.status})") from exc


def _json(response: Response) -> dict:
    data = _decoded(response)
    return data if isinstance(data, dict) else {}


def _list(response: Response) -> list:
    data = _decoded(response)
    return data if isinstance(data, list) else []
