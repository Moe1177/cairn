"""The read-only GitHub client and token lookup (no network: a fake transport answers)."""

import json
import threading
from collections.abc import Mapping

import pytest

from cairn.errors import CairnError
from cairn.remote.auth import check_host, github_token
from cairn.remote.github import GitHub, Response, _HttpsTransport, api_base


class FakeTransport:
    def __init__(self, *replies: Response) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, str, Mapping[str, str]]] = []

    def __call__(self, method: str, path: str, headers: Mapping[str, str]) -> Response:
        self.calls.append((method, path, headers))
        return self.replies.pop(0)


def reply(status: int = 200, body: object = None, **headers: str) -> Response:
    names = {k.replace("_", "-"): v for k, v in headers.items()}
    return Response(status, names, json.dumps(body if body is not None else {}).encode())


SEARCH = {
    "total_count": 2,
    "items": [
        {
            "path": "src/limiter.py",
            "repository": {"full_name": "acme/gateway"},
            "text_matches": [{"fragment": "class RateLimiter:"}],
        },
        {"path": "README.md", "repository": {"full_name": "acme/docs"}},
        {"path": 7, "repository": {"full_name": "acme/bad"}},  # malformed: skipped
    ],
}


def test_search_code_parses_hits_and_fragments() -> None:
    transport = FakeTransport(reply(body=SEARCH))
    page = GitHub("tok", transport=transport).search_code("rate limiter org:acme", per_page=5)
    assert [(h.repo, h.path) for h in page.hits] == [
        ("acme/gateway", "src/limiter.py"),
        ("acme/docs", "README.md"),
    ]
    assert page.hits[0].fragments == ("class RateLimiter:",)
    assert page.total == 2
    method, path, headers = transport.calls[0]
    assert method == "GET" and path.startswith("/search/code?q=rate+limiter+org%3Aacme")
    assert "per_page=5" in path
    assert headers["Authorization"] == "Bearer tok"
    assert "text-match" in headers["Accept"]


def test_enterprise_hosts_use_api_v3() -> None:
    transport = FakeTransport(reply(body=SEARCH))
    GitHub("tok", host="git.acme.com", transport=transport).search_code("x")
    assert transport.calls[0][1].startswith("/api/v3/search/code?")


def test_rate_limit_is_waited_out_then_retried() -> None:
    waits: list[float] = []
    transport = FakeTransport(
        reply(403, {"message": "rate limit"}, x_ratelimit_remaining="0", x_ratelimit_reset="160"),
        reply(body=SEARCH),
    )
    client = GitHub("tok", transport=transport, sleep=waits.append, clock=lambda: 100.0)
    page = client.search_code("x")
    assert waits == [61.0]  # until the reset, plus a second
    assert page.waited == 61.0 and len(page.hits) == 2


def test_retry_after_and_server_errors_are_retried() -> None:
    waits: list[float] = []
    transport = FakeTransport(reply(429, retry_after="3"), reply(502), reply(body=SEARCH))
    page = GitHub("tok", transport=transport, sleep=waits.append).search_code("x")
    assert waits == [3.0, 2.0] and len(page.hits) == 2


def test_a_wait_past_the_cap_fails_with_advice() -> None:
    transport = FakeTransport(reply(403, x_ratelimit_remaining="0", x_ratelimit_reset="9999"))
    client = GitHub("tok", transport=transport, sleep=lambda _: None, clock=lambda: 0.0)
    with pytest.raises(CairnError, match="rate limit"):
        client.search_code("x")


def test_a_forbidden_reply_without_rate_headers_is_an_error() -> None:
    transport = FakeTransport(reply(403, {"message": "Resource not accessible"}))
    with pytest.raises(CairnError, match="403: Resource not accessible"):
        GitHub("tok", transport=transport).search_code("x")


def test_bad_token_says_how_to_log_in() -> None:
    with pytest.raises(CairnError, match="gh auth login"):
        GitHub("tok", transport=FakeTransport(reply(401))).search_code("x")


def test_unsearchable_query_is_no_hits() -> None:
    page = GitHub("tok", transport=FakeTransport(reply(422))).search_code("AND OR")
    assert page.hits == () and page.total == 0


def test_file_exists() -> None:
    transport = FakeTransport(reply(body={"type": "file"}), reply(404), reply(body={"type": "dir"}))
    client = GitHub("tok", transport=transport)
    assert client.file_exists("acme/api", "src/a b.py")
    assert not client.file_exists("acme/api", "gone.py")
    assert not client.file_exists("acme/api", "src")
    assert transport.calls[0][1] == "/repos/acme/api/contents/src/a%20b.py"


@pytest.mark.parametrize("repo", ["acme", "acme/../x", "a/b/c", "-x/y", "acme/re po"])
def test_bad_repo_names_are_refused(repo: str) -> None:
    with pytest.raises(CairnError, match="isn't a GitHub repo"):
        GitHub("tok", transport=FakeTransport()).file_exists(repo, "x")


def test_token_from_environment_in_gh_order() -> None:
    env = {"GITHUB_TOKEN": "second", "GH_TOKEN": " first "}
    assert github_token(env=env, from_cli=lambda _: "cli") == "first"
    assert github_token(env={"GITHUB_TOKEN": "t"}, from_cli=lambda _: None) == "t"


def test_enterprise_token_variables() -> None:
    env = {"GH_TOKEN": "dotcom", "GH_ENTERPRISE_TOKEN": "ghe"}
    assert github_token("git.acme.com", env=env, from_cli=lambda _: None) == "ghe"


def test_token_falls_back_to_gh_cli() -> None:
    hosts: list[str] = []
    token = github_token("GitHub.com", env={}, from_cli=lambda h: hosts.append(h) or "cli")
    assert token == "cli" and hosts == ["github.com"]


def test_no_token_says_how_to_log_in() -> None:
    with pytest.raises(CairnError, match="gh auth login --hostname git.acme.com"):
        github_token("git.acme.com", env={}, from_cli=lambda _: None)


@pytest.mark.parametrize("host", ["https://github.com", "github.com/x", "a b", "localhost", ""])
def test_bad_hosts_are_refused(host: str) -> None:
    with pytest.raises(CairnError, match="isn't a host name"):
        check_host(host)


def test_secondary_rate_limit_waits_a_minute() -> None:
    waits: list[float] = []
    transport = FakeTransport(
        reply(403, {"message": "You have exceeded a secondary rate limit."}), reply(body=SEARCH)
    )
    page = GitHub("tok", transport=transport, sleep=waits.append).search_code("x")
    assert waits == [60.0] and page.waited == 60.0 and len(page.hits) == 2


def test_server_error_backoff_counts_as_time_not_rate_limit() -> None:
    waits: list[float] = []
    transport = FakeTransport(reply(502), reply(body=SEARCH))
    page = GitHub("tok", transport=transport, sleep=waits.append).search_code("x")
    assert waits == [1.0] and page.waited == 0.0 and page.ms >= 1000


def test_a_moved_repo_is_an_error_not_a_missing_file() -> None:
    transport = FakeTransport(reply(301, {"message": "Moved Permanently"}))
    with pytest.raises(CairnError, match="has moved"):
        GitHub("tok", transport=transport).file_exists("acme/old-name", "a.py")


@pytest.mark.parametrize("token", ["", "gho_ab cd", "gho_ab\ncd", "gho_ab\tcd"])
def test_tokens_with_spaces_or_controls_are_refused_without_echoing(token: str) -> None:
    with pytest.raises(CairnError) as raised:
        GitHub(token, transport=FakeTransport())
    assert "control characters" in str(raised.value)
    assert not token or token not in str(raised.value)


@pytest.mark.parametrize(
    ("host", "base"),
    [
        ("github.com", ("api.github.com", "")),
        ("api.github.com", ("api.github.com", "")),
        ("acme.ghe.com", ("api.acme.ghe.com", "")),
        ("api.acme.ghe.com", ("api.acme.ghe.com", "")),
        ("git.acme.com", ("git.acme.com", "/api/v3")),
    ],
)
def test_api_base_per_kind_of_host(host: str, base: tuple[str, str]) -> None:
    assert api_base(host) == base


@pytest.mark.parametrize("repo", ["acme/.", "acme/.."])
def test_dot_repo_names_are_refused(repo: str) -> None:
    with pytest.raises(CairnError, match="isn't a GitHub repo"):
        GitHub("tok", transport=FakeTransport()).file_exists(repo, "x")


class FakeConnection:
    """Stands in for http.client.HTTPSConnection; `fail` makes its next request raise."""

    made: list["FakeConnection"] = []

    def __init__(self, host: str, timeout: float) -> None:
        self.host = host
        self.fail = False
        self.closed = False
        self.requests = 0
        FakeConnection.made.append(self)

    def request(self, method: str, path: str, headers: dict) -> None:
        self.requests += 1
        if self.fail:
            raise ConnectionResetError("closed by peer")

    def getresponse(self) -> "FakeReply":
        return FakeReply()

    def close(self) -> None:
        self.closed = True


class FakeReply:
    status = 200

    def read(self) -> bytes:
        return b"{}"

    def getheaders(self) -> list[tuple[str, str]]:
        return [("X-RateLimit-Remaining", "9")]


@pytest.fixture
def connections(monkeypatch: pytest.MonkeyPatch) -> list[FakeConnection]:
    FakeConnection.made = []
    monkeypatch.setattr("cairn.remote.github.http.client.HTTPSConnection", FakeConnection)
    return FakeConnection.made


def test_transport_keeps_one_connection_alive(connections: list[FakeConnection]) -> None:
    transport = _HttpsTransport("api.github.com")
    first = transport("GET", "/a", {})
    transport("GET", "/b", {})
    assert first.status == 200 and first.headers == {"x-ratelimit-remaining": "9"}
    assert len(connections) == 1 and connections[0].requests == 2


def test_transport_reopens_a_connection_the_server_closed(
    connections: list[FakeConnection],
) -> None:
    transport = _HttpsTransport("api.github.com")
    transport("GET", "/a", {})
    connections[0].fail = True
    assert transport("GET", "/b", {}).status == 200
    assert len(connections) == 2 and connections[0].closed


def test_transport_fails_once_on_a_dead_host(
    connections: list[FakeConnection], monkeypatch: pytest.MonkeyPatch
) -> None:
    class Dead(FakeConnection):
        def request(self, method: str, path: str, headers: dict) -> None:
            raise OSError("unreachable")

    monkeypatch.setattr("cairn.remote.github.http.client.HTTPSConnection", Dead)
    with pytest.raises(CairnError, match="couldn't reach api.github.com"):
        _HttpsTransport("api.github.com")("GET", "/a", {})
    assert len(connections) == 1  # one try: a second would only double the timeout


def test_transport_connections_are_per_thread(connections: list[FakeConnection]) -> None:
    transport = _HttpsTransport("api.github.com")
    transport("GET", "/a", {})
    worker = threading.Thread(target=lambda: transport("GET", "/b", {}))
    worker.start()
    worker.join()
    assert len(connections) == 2
