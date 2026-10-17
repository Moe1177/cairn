"""The read-only GitLab client, its token lookup, and GitLab orgs in the config (no network: a
fake transport answers by path)."""

import json
import threading
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from cairn.config import CairnConfig, OrgSource
from cairn.errors import CairnError
from cairn.org import access, view
from cairn.org.access import client_for, org_repo
from cairn.org.catalog import CatalogIndex, CatalogRepo, OrgCatalog, find_repo
from cairn.remote.auth import gitlab_token
from cairn.remote.gitlab import TREE_PAGES, GitLab
from cairn.remote.transport import Response

Route = Callable[[str, str], Response]


class FakeTransport:
    def __init__(self, route: Route) -> None:
        self.route = route
        self.calls: list[tuple[str, str, Mapping[str, str]]] = []
        self._lock = threading.Lock()

    def __call__(self, method: str, path: str, headers: Mapping[str, str]) -> Response:
        with self._lock:
            self.calls.append((method, path, headers))
        return self.route(method, path)

    def paths(self) -> list[str]:
        return [path for _, path, _ in self.calls]


def reply(status: int = 200, body: object = None, **headers: str) -> Response:
    names = {k.replace("_", "-"): v for k, v in headers.items()}
    data = (
        body if isinstance(body, bytes) else json.dumps(body if body is not None else {}).encode()
    )
    return Response(status, names, data)


def project(path: str, pid: int = 1, **extra: object) -> dict:
    return {"id": pid, "path_with_namespace": path, "default_branch": "main", **extra}


def client(route: Route, token: str = "tok", **kwargs: object) -> tuple[GitLab, FakeTransport]:
    transport = FakeTransport(route)
    return GitLab(token, transport=transport, **kwargs), transport  # type: ignore[arg-type]


def test_list_repos_reads_a_group_and_its_subgroups() -> None:
    listing = [
        project(
            "acme/platform/api",
            7,
            description="The API",
            topics=["go"],
            last_activity_at="2026-10-01T00:00:00Z",
        ),
        project("acme/tools", 8, forked_from_project={"id": 1}, tag_list=["cli"]),
        # Empty: no branch yet. Kept, so a page of 100 with one still reads as full.
        {"id": 9, "path_with_namespace": "acme/empty", "default_branch": None},
        {"id": 10, "path_with_namespace": "../evil", "default_branch": "main"},
    ]
    gitlab, transport = client(lambda m, p: reply(body=listing))
    repos = gitlab.list_repos("acme", page=2)
    assert [r.name for r in repos] == ["acme/platform/api", "acme/tools", "acme/empty"]
    api, tools, empty = repos
    assert empty.default_branch == "" and gitlab.tree("acme/empty", "") == ((), False)
    assert len(transport.calls) == 1  # an empty project's tree isn't asked for
    assert (api.description, api.topics, api.pushed, api.fork) == (
        "The API",
        ("go",),
        "2026-10-01T00:00:00Z",
        False,
    )
    assert tools.fork and tools.topics == ("cli",)
    method, path, headers = transport.calls[0]
    assert method == "GET" and path.startswith("/api/v4/groups/acme/projects?")
    assert "include_subgroups=true" in path and "archived=false" in path and "page=2" in path
    assert headers["Authorization"] == "Bearer tok"


def test_list_repos_falls_back_to_a_user_and_encodes_subgroups() -> None:
    def route(method: str, path: str) -> Response:
        return (
            reply(404, {"message": "404 Group Not Found"}) if "/groups/" in path else reply(body=[])
        )

    gitlab, transport = client(route)
    assert gitlab.list_repos("someone") == ()
    assert transport.paths()[1].startswith("/api/v4/users/someone/projects?")
    with pytest.raises(CairnError, match="404 Group Not Found"):
        gitlab.list_repos("acme/platform")  # a subgroup is no user: no fallback
    assert transport.paths()[2].startswith("/api/v4/groups/acme%2Fplatform/projects?")
    assert len(transport.calls) == 3


def test_tree_reads_known_pages_side_by_side_files_only() -> None:
    def route(method: str, path: str) -> Response:
        n = int(path.rsplit("page=", 1)[1])
        entries = [{"type": "tree", "path": "src"}] if n == 1 else []
        entries.append({"type": "blob", "path": f"src/f{n}.go"})
        return reply(body=entries, x_total_pages="3")

    gitlab, transport = client(route)
    paths, cut = gitlab.tree("acme/platform/api", "main")
    assert sorted(paths) == ["src/f1.go", "src/f2.go", "src/f3.go"] and not cut
    assert transport.paths()[0].startswith(
        "/api/v4/projects/acme%2Fplatform%2Fapi/repository/tree?recursive=true&ref=main"
    )


def test_a_long_tree_without_totals_is_read_in_waves_and_keeps_the_root_files() -> None:
    def route(method: str, path: str) -> Response:
        if "recursive" not in path:
            return reply(body=[{"type": "blob", "path": "go.mod"}, {"type": "tree", "path": "a"}])
        n = int(path.rsplit("page=", 1)[1])
        return reply(body=[{"type": "tree", "path": f"d{n}"}], x_next_page=str(n + 1))

    gitlab, transport = client(route)
    paths, cut = gitlab.tree("acme/big", "main")
    assert cut and paths == ("go.mod",)  # folders first: the root's files are what's left
    assert sum("recursive" in p for p in transport.paths()) == TREE_PAGES


def test_a_tree_without_totals_stops_at_its_last_page() -> None:
    def route(method: str, path: str) -> Response:
        n = int(path.rsplit("page=", 1)[1])
        if n > 12:
            return reply(body=[])
        more = {"x-next-page": str(n + 1)} if n < 12 else {}
        return Response(200, more, json.dumps([{"type": "blob", "path": f"f{n}"}]).encode())

    gitlab, transport = client(route)
    paths, cut = gitlab.tree("acme/mid", "main")
    assert not cut and sorted(paths, key=lambda p: int(p[1:])) == [f"f{n}" for n in range(1, 13)]
    assert len(transport.calls) <= 12 + 8  # the last wave may ask a few pages past the end


def test_a_cut_tree_reads_the_roots_files_past_its_folders() -> None:
    def route(method: str, path: str) -> Response:
        n = int(path.rsplit("page=", 1)[1])
        if "recursive" in path:
            return reply(body=[{"type": "tree", "path": f"d{n}"}], x_next_page=str(n + 1))
        if n == 1:  # a root of over 100 folders: its files start on the next page
            return reply(body=[{"type": "tree", "path": "a"}], x_next_page="2")
        return reply(body=[{"type": "blob", "path": "package.json"}])

    gitlab, _ = client(route)
    assert gitlab.tree("acme/big", "main") == (("package.json",), True)


def test_a_page_going_missing_fails_the_tree() -> None:
    def route(method: str, path: str) -> Response:
        n = int(path.rsplit("page=", 1)[1])
        if n == 3:
            return reply(404, {"message": "404 Tree Not Found"})
        return reply(body=[{"type": "blob", "path": f"f{n}"}], x_total_pages="4")

    gitlab, _ = client(route)
    with pytest.raises(CairnError, match="changed while cairn read it"):
        gitlab.tree("acme/api", "main")


def test_an_empty_repo_has_no_tree() -> None:
    gitlab, _ = client(lambda m, p: reply(404, {"message": "404 Tree Not Found"}))
    assert gitlab.tree("acme/empty", "main") == ((), False)


def test_files_are_read_raw_on_the_listed_default_branch() -> None:
    files = {
        "docs%2Fguide.md": b"\xef\xbb\xbf# Guide\n",
        "logo.png": b"PNG\x00\x01",
        "big.txt": b"x" * 50,
    }

    def route(method: str, path: str) -> Response:
        if "/groups/" in path:
            return reply(body=[project("acme/api", 3, default_branch="trunk")])
        name = path.split("/repository/files/", 1)[1].split("?")[0].removesuffix("/raw")
        if name not in files:
            return reply(404, {"message": "404 File Not Found"})
        return reply(body=b"" if method == "HEAD" else files[name])

    gitlab, transport = client(route)
    gitlab.list_repos("acme")
    assert gitlab.read_file("acme/api", "docs/guide.md") == "# Guide\n"
    assert transport.paths()[-1] == (
        "/api/v4/projects/acme%2Fapi/repository/files/docs%2Fguide.md/raw?ref=trunk"
    )
    assert gitlab.read_file("acme/api", "logo.png") is None  # binary
    assert gitlab.read_file("acme/api", "big.txt", max_bytes=10) is None
    assert gitlab.read_file("acme/api", "docs") is None  # a folder isn't a file
    assert gitlab.file_exists("acme/api", "docs/guide.md")
    assert not gitlab.file_exists("acme/api", "missing.md")
    assert transport.calls[-1][0] == "HEAD"
    assert gitlab.read_file("acme/other", "x.md") is None
    assert transport.paths()[-1].endswith("/raw?ref=HEAD")  # not listed: the default branch
    with pytest.raises(CairnError, match="isn't a path inside a repo"):
        gitlab.read_file("acme/api", "../secrets")
    with pytest.raises(CairnError, match="isn't a GitLab project"):
        gitlab.read_file("acme", "x.md")


def test_search_code_searches_the_group_and_names_each_hit_once() -> None:
    hits = [
        {"path": "kit/log.go", "data": "func New()", "project_id": 7},
        {"path": "main.go", "data": "log.New()", "project_id": 9},
        {"path": "x.go", "project_id": 9},
        {"path": 5, "project_id": 7},  # malformed: skipped
        {"path": "y.go", "project_id": 404},  # a project it can't see: skipped
    ]

    def route(method: str, path: str) -> Response:
        if "/search?" in path:
            return reply(body=hits, x_total="40")
        if "/groups/" in path:
            return reply(body=[project("acme/kit", 7)])
        if path == "/api/v4/projects/9":
            return reply(body=project("acme/platform/svc", 9))
        return reply(404, {"message": "404 Project Not Found"})

    gitlab, transport = client(route)
    gitlab.list_repos("acme")
    page = gitlab.search_code('"log.New" org:acme/platform', per_page=30)
    assert [(h.repo, h.path, h.fragments) for h in page.hits] == [
        ("acme/kit", "kit/log.go", ("func New()",)),
        ("acme/platform/svc", "main.go", ("log.New()",)),
        ("acme/platform/svc", "x.go", ()),
    ]
    assert page.total == 40
    search = next(p for p in transport.paths() if "/search?" in p)
    assert search.startswith("/api/v4/groups/acme%2Fplatform/search?scope=blobs")
    assert "search=%22log.New%22" in search and "per_page=30" in search
    assert transport.paths().count("/api/v4/projects/9") == 1  # asked once, then known


def test_search_without_advanced_search_says_so() -> None:
    gitlab, _ = client(
        lambda m, p: reply(400, {"error": "Scope supported only with advanced search"})
    )
    with pytest.raises(CairnError, match="needs GitLab's advanced search"):
        gitlab.search_code("RateLimiter org:acme")
    with pytest.raises(CairnError, match="needs a group"):
        gitlab.search_code("RateLimiter")


def test_search_repos_in_the_group() -> None:
    gitlab, transport = client(lambda m, p: reply(body=[project("acme/platform/api")]))
    names, _ = gitlab.search_repos("api gateway org:acme")
    assert names == ("acme/platform/api",)
    assert "search=api+gateway" in transport.paths()[0]
    assert "include_subgroups=true" in transport.paths()[0]
    assert "with_shared=false" in transport.paths()[0]  # projects shared in aren't the org's


def test_githubs_language_qualifier_becomes_an_extension() -> None:
    gitlab, transport = client(lambda m, p: reply(body=[]))
    gitlab.search_code("RateLimiter language:Python org:acme")
    gitlab.search_code("RateLimiter language:cobol org:acme")
    first, second = (p for p in transport.paths())
    assert "search=RateLimiter+extension%3Apy&" in first
    assert "search=RateLimiter&" in second  # no extension known: left out, not searched for


def test_a_rejected_token_and_a_missing_one_say_how_to_log_in() -> None:
    rejected, _ = client(lambda m, p: reply(401, {"message": "401 Unauthorized"}))
    with pytest.raises(CairnError, match="GitLab rejected the token: log in again with `glab"):
        rejected.list_repos("acme")
    anonymous, transport = client(lambda m, p: reply(401, {}), token="")
    with pytest.raises(CairnError, match="GitLab needs a token for that"):
        anonymous.search_code("x org:acme")
    assert "Authorization" not in transport.calls[0][2]
    with pytest.raises(CairnError, match="control characters"):
        GitLab("tok\nX-Evil: 1")


def test_rate_limits_are_waited_out_and_a_long_window_is_a_budget() -> None:
    now = 1_000_000.0
    replies = [
        reply(429, {}, retry_after="3"),
        reply(body=[], ratelimit_remaining="40", ratelimit_reset=str(int(now + 30))),
        reply(body=[], ratelimit_remaining="700", ratelimit_reset=str(int(now + 3600))),
    ]
    slept: list[float] = []
    gitlab, _ = client(lambda m, p: replies.pop(0), sleep=slept.append, clock=lambda: now)
    gitlab.list_repos("acme")
    assert slept == [3.0]
    assert gitlab.remaining() is None  # refills within the minute: just wait if it runs out
    gitlab.list_repos("acme")
    assert gitlab.remaining() == 700  # an hour's budget: cairn spends it carefully
    stuck, _ = client(
        lambda m, p: reply(429, {}, retry_after="600"), sleep=slept.append, clock=lambda: now
    )
    with pytest.raises(CairnError, match="longer than cairn waits"):
        stuck.list_repos("acme")


def test_gitlab_token_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    assert gitlab_token(env={"GITLAB_TOKEN": " t1 "}, from_cli=lambda h: "cli") == "t1"
    assert gitlab_token(env={"GITLAB_ACCESS_TOKEN": "t2"}, from_cli=lambda h: None) == "t2"
    asked: list[str] = []
    token = gitlab_token("git.acme.io", env={}, from_cli=lambda h: asked.append(h) or "cli")
    assert token == "cli" and asked == ["git.acme.io"]
    with pytest.raises(CairnError, match="glab auth login --hostname gitlab.com"):
        gitlab_token(env={}, from_cli=lambda h: None)
    # The variable is gitlab.com's, or GITLAB_HOST's: another host never gets it.
    other = gitlab_token(
        "gitlab.partner.io", env={"GITLAB_TOKEN": "dotcom"}, from_cli=lambda h: "own"
    )
    assert other == "own"
    named = {"GITLAB_TOKEN": "ours", "GITLAB_HOST": "https://git.acme.io/"}
    assert gitlab_token("git.acme.io", env=named, from_cli=lambda h: None) == "ours"
    assert gitlab_token("gitlab.com", env=named, from_cli=lambda h: "cli") == "cli"


def test_config_reads_gitlab_hosts_and_groups() -> None:
    assert OrgSource(org="acme").kind == "github"
    assert OrgSource(org="acme/platform", host="gitlab.com").kind == "gitlab"
    assert OrgSource(org="acme", host="gitlab.acme.io").kind == "gitlab"
    assert OrgSource(org="acme", host="git.acme.io", kind="gitlab").kind == "gitlab"
    assert OrgSource(org="acme", host="gitlab.com", kind="github").kind == "github"
    loaded = CairnConfig.model_validate({"orgs": [{"org": "acme/platform", "host": "gitlab.com"}]})
    assert loaded.orgs[0].kind == "gitlab"
    for bad in (
        {"org": "acme/platform"},  # a GitHub org has no subgroups
        {"org": "a b", "host": "gitlab.com"},
        {"org": "acme/../x", "host": "gitlab.com"},
        {"org": "acme/x.git", "host": "gitlab.com"},
        {"org": "acme", "host": "gitlab.com", "kind": "bitbucket"},
    ):
        with pytest.raises(ValueError):
            OrgSource.model_validate(bad)


def test_client_for_picks_the_hosts_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(access, "_CLIENTS", {})
    monkeypatch.setattr(access, "gitlab_token", lambda host: "gl")
    monkeypatch.setattr(access, "github_token", lambda host: "gh")
    lab = client_for(OrgSource(org="acme", host="gitlab.com"))
    assert isinstance(lab, GitLab)
    assert client_for(OrgSource(org="acme/platform", host="gitlab.com")) is lab
    assert client_for(OrgSource(org="acme")) is not lab


def test_org_repo_on_gitlab_stays_inside_the_group() -> None:
    group = OrgSource(org="acme", host="gitlab.com")
    assert org_repo(group, "api") == "acme/api"
    assert org_repo(group, "platform/api") == "acme/platform/api"  # a subgroup's repo
    assert org_repo(group, "ACME/platform/api") == "acme/platform/api"
    assert org_repo(group, "other/api") == "acme/other/api"  # never another group's
    sub = OrgSource(org="acme/platform", host="gitlab.com")
    assert org_repo(sub, "acme/platform/api") == "acme/platform/api"


CATALOG = OrgCatalog(
    org="acme",
    host="gitlab.com",
    built="2026-10-17T00:00:00+00:00",
    ms=1.0,
    repos=(
        CatalogRepo(name="acme/platform/api", description="The platform API"),
        CatalogRepo(name="acme/tools/api"),
        CatalogRepo(name="acme/tools/cli"),
    ),
)


def test_find_repo_reaches_subgroup_repos() -> None:
    assert find_repo(CATALOG, "acme/platform/api").name == "acme/platform/api"  # type: ignore[union-attr]
    assert find_repo(CATALOG, "tools/api").name == "acme/tools/api"  # type: ignore[union-attr]
    assert find_repo(CATALOG, "cli").name == "acme/tools/cli"  # type: ignore[union-attr]
    assert find_repo(CATALOG, "api") is None  # two repos are called api: say which


def test_org_card_on_gitlab_reads_subgroup_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".cairn").mkdir()
    (tmp_path / ".cairn" / "config.yaml").write_text(
        "orgs:\n  - org: acme\n    host: gitlab.com\n", encoding="utf-8"
    )
    monkeypatch.setattr(view, "catalog_index", lambda ws, source: CatalogIndex.of(CATALOG))
    from cairn.model.graph import Workspace

    workspace = Workspace(workspace_root=str(tmp_path), generated_at="now", repos=())
    for name in ("platform/api", "acme/platform/api", "gitlab.com/acme/platform/api"):
        card = view.org_card(tmp_path, workspace, name)
        assert card is not None and "The platform API" in card, name
    assert view.org_card(tmp_path, workspace, "github.com/acme/platform/api") is None
    card = view.org_card(tmp_path, workspace, "platform/api")
    assert card is not None and "read_org_file (repo acme/platform/api," in card


def test_a_subgroup_org_finds_what_it_shows() -> None:
    sub = CATALOG.model_copy(update={"org": "acme/platform"})
    assert find_repo(sub, "platform/api").name == "acme/platform/api"  # type: ignore[union-attr]
    assert find_repo(sub, "api").name == "acme/platform/api"  # type: ignore[union-attr]
    dotted = OrgSource(org="acme.io", host="gitlab.com")
    assert view._inside_org(dotted, "acme.io/platform/api") == "platform/api"
    assert view._inside_org(dotted, "gitlab.com/acme.io/api") == "api"
    assert view._inside_org(OrgSource(org="acme"), "git.acme.com/acme/api") is None
