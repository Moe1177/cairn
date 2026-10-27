"""The org's own packages: who defines each, who uses it, and where (no network: a fake client)."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cairn.errors import CairnError
from cairn.mcp_server import tools
from cairn.org.packages import (
    INDEX_VERSION,
    RESERVE,
    Defined,
    OrgPackage,
    PackageIndex,
    RepoPackages,
    Used,
    build_index,
    find_packages,
    import_name,
    load_index,
    manifest_description,
    needs_build,
    org_packages,
    package_manifests,
    render_choices,
    render_package,
    render_packages,
    repo_packages,
    save_index,
    usage_files,
)
from cairn.remote.github import CodeHit, RepoInfo, SearchPage

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


class FakeGitHub:
    def __init__(
        self,
        repos: list[RepoInfo],
        trees: dict[str, tuple[str, ...]],
        files: dict[str, str],
        *,
        broken: frozenset[str] = frozenset(),
        left: int | None = None,
        hits: tuple[CodeHit, ...] = (),
    ) -> None:
        self.repos = repos
        self.trees = trees
        self.files = files
        self.broken = broken
        self.left = left
        self.hits = hits
        self.read: list[str] = []
        self.prefetched: list[tuple[str, tuple[str, ...]]] = []
        self.queries: list[str] = []
        self.error = "GitHub answered 500"

    def list_repos(self, owner: str, *, page: int = 1, per_page: int = 100) -> tuple[RepoInfo, ...]:
        return tuple(self.repos[(page - 1) * per_page : page * per_page])

    def tree(self, repo: str, ref: str) -> tuple[tuple[str, ...], bool]:
        self.read.append(repo)
        self._spend()
        if repo in self.broken and not self.trees.get(repo):
            raise CairnError(self.error)
        return self.trees.get(repo, ()), False

    def prefetch(self, repo: str, paths: Sequence[str]) -> None:
        self.prefetched.append((repo, tuple(paths)))

    def read_file(self, repo: str, path: str, *, max_bytes: int = 200_000) -> str | None:
        self._spend()
        if repo in self.broken:
            raise CairnError(self.error)
        return self.files.get(f"{repo}/{path}")

    def _spend(self) -> None:
        if self.left is not None:
            self.left -= 1

    def remaining(self, resource: str = "core") -> int | None:
        return self.left

    def search_code(self, query: str, *, per_page: int = 10) -> SearchPage:
        self.queries.append(query)
        return SearchPage(self.hits, len(self.hits), 1.0)


def info(name: str, **kw: object) -> RepoInfo:
    kw.setdefault("pushed", "2026-10-01T00:00:00Z")
    return RepoInfo(name=f"acme/{name}", default_branch="main", **kw)  # type: ignore[arg-type]


def record(name: str, defines=(), uses=(), **kw: object) -> RepoPackages:  # type: ignore[no-untyped-def]
    return RepoPackages(
        repo=f"acme/{name}",
        defines=tuple(Defined(name=n, path=p, description=d) for n, p, d in defines),
        uses=tuple(Used(name=n, path=p) for n, p in uses),
        **kw,  # type: ignore[arg-type]
    )


def index(*records: RepoPackages, **kw: object) -> PackageIndex:
    return PackageIndex(
        version=INDEX_VERSION,
        org="acme",
        host="github.com",
        built=NOW.isoformat(),
        ms=1.0,
        repos=records,
        **kw,  # type: ignore[arg-type]
    )


def test_repo_packages_reads_each_manifest_and_drops_a_monorepos_own_uses() -> None:
    texts = [
        ("package.json", '{"name": "@acme/web", "dependencies": {"@acme/ui": "1", "react": "1"}}'),
        (
            "packages/ui/package.json",
            '{"name": "@acme/ui", "description": "Our\\nbuttons <!-- x -->", '
            '"dependencies": {"@acme/log": "1", "bad name": "1"}}',
        ),
    ]
    got = repo_packages(info("web", description="The\x07 site"), texts)
    assert [(d.name, d.path) for d in got.defines] == [
        ("npm:@acme/web", "package.json"),
        ("npm:@acme/ui", "packages/ui/package.json"),
    ]
    assert got.defines[1].description == "Our buttons x"
    assert {(u.name, u.path) for u in got.uses} == {
        ("npm:react", "package.json"),
        ("npm:@acme/log", "packages/ui/package.json"),
    }  # @acme/ui is the repo's own; "bad name" isn't a package name
    assert got.description == "The site" and got.pushed == "2026-10-01T00:00:00Z"


@pytest.mark.parametrize(
    ("path", "text", "expected"),
    [
        ("package.json", '{"description": "UI kit"}', "UI kit"),
        ("pyproject.toml", '[project]\ndescription = "Log helpers"\n', "Log helpers"),
        ("pyproject.toml", '[tool.poetry]\ndescription = "Old style"\n', "Old style"),
        ("Cargo.toml", '[package]\ndescription = "Fast"\n', "Fast"),
        ("go.mod", "module x\n", ""),
        ("package.json", '{"description": 5}', ""),
        pytest.param("package.json", "[" * 50_000, "", id="nested-too-deep"),
    ],
)
def test_manifest_description(path: str, text: str, expected: str) -> None:
    assert manifest_description(path, text) == expected


def test_org_packages_find_homes_and_users() -> None:
    idx = index(
        record("vault", defines=[("go:github.com/acme/vault/api", "api/go.mod", "")]),
        record("hclog", defines=[("go:github.com/acme/hclog", "go.mod", "")], description="Logs"),
        record(
            "svc",
            uses=[
                ("go:github.com/acme/hclog", "go.mod"),
                ("go:github.com/acme/vault/api", "go.mod"),
                ("go:github.com/acme/vault/api", "tools/go.mod"),
                ("go:github.com/spf13/cobra", "go.mod"),  # public: not the org's
            ],
        ),
        record("cli", uses=[("go:github.com/acme/hclog", "go.mod")]),
        # An example inside the library's own repo is no user of it.
        record("vault-example", uses=[("go:github.com/acme/vault/api", "go.mod")]),
    )
    found = {p.name: p for p in org_packages(idx)}
    assert list(found) == ["go:github.com/acme/hclog", "go:github.com/acme/vault/api"]
    hclog = found["go:github.com/acme/hclog"]
    assert (hclog.home, hclog.path, hclog.description) == ("acme/hclog", "go.mod", "Logs")
    assert [repo for repo, _ in hclog.users] == ["acme/svc", "acme/cli"]
    api = found["go:github.com/acme/vault/api"]
    assert api.description == ""  # a subfolder module isn't what the repo describes
    assert dict(api.users)["acme/svc"] == ("go.mod", "tools/go.mod")
    assert len(api.users) == 2


def test_go_major_versions_are_one_package_and_homes_come_from_the_module_path() -> None:
    idx = index(
        record("hcl", defines=[("go:github.com/acme/hcl/v2", "go.mod", "")]),
        record("a", uses=[("go:github.com/acme/hcl/v2", "go.mod")]),
        record("b", uses=[("go:github.com/acme/hcl", "go.mod")]),
        # No manifest read defines this one, but its path names an active repo.
        record("kit", description="Shared kit"),
        record(
            "c",
            uses=[("go:github.com/acme/kit/log", "go.mod"), ("go:github.com/acme/kit", "go.mod")],
        ),
    )
    found = {p.name: p for p in org_packages(idx)}
    assert len(found["go:github.com/acme/hcl/v2"].users) == 2
    kit = found["go:github.com/acme/kit/log"]
    assert (kit.home, kit.path, kit.description) == ("acme/kit", "", "")  # a part of kit
    assert found["go:github.com/acme/kit"].description == "Shared kit"


def test_forks_and_template_names() -> None:
    idx = index(
        record("lib", defines=[("npm:@acme/lib", "package.json", "")]),
        record("lib-fork", defines=[("npm:@acme/lib", "package.json", "")], fork=True),
        # The org's maintained fork of a library, under the org's name: its home.
        record("cli", defines=[("go:github.com/acme/cli", "go.mod", "")], fork=True),
        # A fork still declaring upstream's name is upstream's package, not the org's.
        record("azure", defines=[("go:github.com/azure/sdk", "go.mod", "")], fork=True),
        # A copy (not a fork) of another owner's Go module is still that owner's.
        record("prom", defines=[("go:github.com/prometheus/prometheus", "go.mod", "")]),
        # A name several originals define is a template's.
        record("app1", defines=[("npm:cdk-app", "package.json", "")]),
        record("app2", defines=[("npm:cdk-app", "package.json", "")]),
        record(
            "svc",
            uses=[
                ("npm:@acme/lib", "package.json"),
                ("go:github.com/acme/cli", "go.mod"),
                ("go:github.com/azure/sdk", "go.mod"),
                ("npm:cdk-app", "package.json"),
                ("go:github.com/prometheus/prometheus", "go.mod"),
            ],
        ),
    )
    found = {p.name: p.home for p in org_packages(idx)}
    assert found == {"npm:@acme/lib": "acme/lib", "go:github.com/acme/cli": "acme/cli"}


def test_find_packages_by_full_bare_suffix_or_part_of_a_name() -> None:
    packages = [
        OrgPackage("go:github.com/acme/go-hclog", "acme/go-hclog", "go.mod", "", ()),
        OrgPackage("go:github.com/acme/vault/api/v2", "acme/vault", "api/go.mod", "", ()),
        OrgPackage("go:github.com/acme/consul/api", "acme/consul", "api/go.mod", "", ()),
        OrgPackage("npm:@acme/ui", "acme/web", "packages/ui/package.json", "", ()),
    ]
    assert [p.home for p in find_packages(packages, "hclog")] == ["acme/go-hclog"]
    assert [p.home for p in find_packages(packages, "github.com/acme/vault/api")] == ["acme/vault"]
    assert [p.home for p in find_packages(packages, "npm:@acme/ui")] == ["acme/web"]
    assert len(find_packages(packages, "api")) == 2
    assert [p.home for p in find_packages(packages, "consul")] == ["acme/consul"]
    assert find_packages(packages, "nothing") == [] and find_packages(packages, " ") == []
    both = [*packages, OrgPackage("python:@acme/ui", "acme/py", "pyproject.toml", "", ())]
    assert [p.home for p in find_packages(both, "npm:@acme/ui")] == ["acme/web"]
    assert "@acme/ui (npm), @acme/ui (Python)" in render_choices(
        find_packages(both, "@acme/ui"), "x"
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("go:github.com/acme/kit", "github.com/acme/kit"),
        ("npm:@acme/ui", "@acme/ui"),
        ("python:acme-log", "acme_log"),
        ("cargo:acme-core", "acme_core"),
        ("maven:com.acme:billing", "com.acme"),
        ("ruby:acme", "acme"),
    ],
)
def test_import_name(name: str, expected: str) -> None:
    assert import_name(name) == expected


def test_usage_files_keep_the_orgs_code_that_imports_it() -> None:
    hits = (
        CodeHit("acme/svc", "main_test.go", ("hclog.New",)),
        CodeHit("acme/svc", "main.go", ('"github.com/acme/hclog"',)),
        CodeHit("acme/svc", "go.mod", ()),  # a manifest
        CodeHit("acme/svc", "go.sum", ()),  # a lockfile
        CodeHit("acme/svc", "CHANGELOG.md", ()),  # docs
        CodeHit("acme/svc", "vendor/x/y.go", ()),  # vendored
        CodeHit("acme/hclog", "logger.go", ()),  # the package's own repo
        CodeHit("other/svc", "main.go", ()),  # another owner
    )
    client = FakeGitHub([], {}, {}, hits=hits)
    package = OrgPackage("go:github.com/acme/hclog", "acme/hclog", "go.mod", "", ())
    files = usage_files(client, "acme", package)  # type: ignore[arg-type]
    assert [(f.repo, f.path) for f in files] == [
        ("acme/svc", "main.go"),
        ("acme/svc", "main_test.go"),
    ]
    assert client.queries == ['"github.com/acme/hclog" org:acme']


def test_build_index_rereads_only_what_changed() -> None:
    repos = [info("lib"), info("svc"), info("down"), info("old", archived=True)]
    files = {
        "acme/lib/go.mod": "module github.com/acme/lib\n",
        "acme/svc/go.mod": "module github.com/acme/svc\nrequire github.com/acme/lib v1.0.0\n",
    }
    trees = {"acme/lib": ("go.mod",), "acme/svc": ("go.mod", "vendor/x/go.mod")}
    client = FakeGitHub(repos, trees, files, broken=frozenset({"acme/down"}))
    first = build_index(client, "acme", now=lambda: NOW)  # type: ignore[arg-type]
    assert [r.repo for r in first.repos] == ["acme/lib", "acme/svc", "acme/down"]
    assert first.reread == 3 and first.unread == 0 and first.repos[2].failed
    assert [p.name for p in org_packages(first)] == ["go:github.com/acme/lib"]
    # Each repo's manifests are asked for together first (plain git fetches them at once).
    assert ("acme/svc", ("go.mod",)) in client.prefetched

    client.read.clear()
    client.repos = [info("lib"), info("svc", pushed="2026-10-02T00:00:00Z"), info("down")]
    second = build_index(client, "acme", previous=first)  # type: ignore[arg-type]
    assert sorted(client.read) == ["acme/down", "acme/svc"]  # pushed since, or failed last time
    assert second.reread == 2 and second.repos[0] is first.repos[0]
    with pytest.raises(CairnError, match="no repos"):
        build_index(FakeGitHub([], {}, {}), "acme")  # type: ignore[arg-type]


def test_a_low_api_budget_leaves_repos_for_the_next_call() -> None:
    old = index(record("lib", defines=[("go:github.com/acme/lib", "go.mod", "")]))
    repos = [info("lib"), info("a"), info("b")]
    trees = {f"acme/{n}": ("go.mod", "x/go.mod") for n in ("lib", "a", "b")}
    files = {
        f"acme/{n}/{f}": "module m\n" for n in ("lib", "a", "b") for f in ("go.mod", "x/go.mod")
    }
    # At the reserve: a worker may start a tree, but stops before any manifest.
    client = FakeGitHub(repos, trees, files, left=RESERVE)
    got = build_index(client, "acme", previous=old)  # type: ignore[arg-type]
    assert client.left is not None and client.left >= RESERVE - len(repos)
    assert got.repos[0] == old.repos[0]  # lib was due (pushed since) but kept, not lost
    assert got.unread == 3 and needs_build(got, NOW)
    assert "repos aren't read yet" in render_packages(got, [])
    # Already under the reserve: nothing is listed or read, the last index is kept as it was.
    spent = FakeGitHub(repos, trees, files, left=RESERVE - 1)
    assert build_index(spent, "acme", previous=got) is got  # type: ignore[arg-type]
    assert spent.read == [] and spent.left == RESERVE - 1


def test_a_failed_reread_keeps_what_was_known() -> None:
    old = index(record("lib", defines=[("go:github.com/acme/lib", "go.mod", "")]))
    client = FakeGitHub([info("lib")], {}, {}, broken=frozenset({"acme/lib"}))
    got = build_index(client, "acme", previous=old)  # type: ignore[arg-type]
    assert got.repos[0].defines == old.repos[0].defines and got.repos[0].failed
    client.error = "GitHub rejected the token: log in again with `gh auth login`"
    with pytest.raises(CairnError, match="rejected the token"):
        build_index(client, "acme", previous=old)  # type: ignore[arg-type]


def test_an_index_from_an_older_cairn_is_read_again() -> None:
    old = index(record("lib", pushed="2026-10-01T00:00:00Z", branch="main")).model_copy(
        update={"version": 0}
    )
    client = FakeGitHub([info("lib")], {}, {})
    build_index(client, "acme", previous=old)  # type: ignore[arg-type]
    assert client.read == ["acme/lib"]


def test_examples_unsafe_paths_and_private_packages_define_nothing() -> None:
    paths = ["go.mod", "examples/demo/go.mod", "internal/testdata/go.mod", "x\n- fake/go.mod"]
    assert package_manifests(paths) == ["go.mod"]
    private = '{"name": "config", "private": true, "dependencies": {"@acme/ui": "1"}}'
    got = repo_packages(info("svc"), [("package.json", private)])
    assert got.defines == () and [u.name for u in got.uses] == ["npm:@acme/ui"]


def test_needs_build() -> None:
    fresh = index(record("a"))
    assert not needs_build(fresh, NOW + timedelta(hours=23))
    assert needs_build(fresh, NOW + timedelta(days=2))
    assert needs_build(fresh.model_copy(update={"built": "2026-10-17T00:00:00"}), NOW)
    broken = index(*[record(f"r{i}", failed=i < 2) for i in range(10)])
    assert needs_build(broken, NOW)  # over a tenth unreadable: try them again


def test_render_packages_lists_and_filters() -> None:
    packages = [
        OrgPackage(
            "go:github.com/acme/retry", "acme/retry", "go.mod", "Retrying HTTP", (("a", ()),) * 3
        ),
        OrgPackage("npm:@acme/ui", "acme/web", "packages/ui/package.json", "", (("b", ()),)),
    ]
    idx = index(record("a"), record("b"))
    text = render_packages(idx, packages, limit=1)
    assert "the 2 libraries its 2 active repos use" in text
    assert "- github.com/acme/retry (Go) · 3 repos · in acme/retry — Retrying HTTP" in text
    assert "… 1 more" in text
    found = render_packages(idx, packages, query="HTTP retry")
    assert "1 match 'HTTP retry'" in found and "@acme/ui" not in found
    assert "None match" in render_packages(idx, packages, query="kafka")
    assert "- @acme/ui (npm) · 1 repos · in acme/web/packages/ui" in render_packages(idx, packages)


def test_render_package_with_users_and_code() -> None:
    users = (("acme/vault", ("go.mod", "api/go.mod")), ("acme/svc", ("go.mod",)))
    package = OrgPackage("go:github.com/acme/hclog", "acme/hclog", "go.mod", "Logs", users)
    idx = index(record("a", failed=True))
    from cairn.org.packages import UsageFile

    text = render_package(idx, package, [UsageFile("acme/svc", "main.go", "hclog.New()")])
    assert text.startswith("github.com/acme/hclog (Go): defined in acme/hclog/go.mod. Logs")
    assert "Used by 2 active repos (latest push first): vault (., api), svc" in text
    assert "- acme/svc/main.go: hclog.New()" in text
    assert "1 repos couldn't be read fully" in text
    assert "(No code search: rate limited)" in render_package(idx, package, "rate limited")
    assert "found no file importing it" in render_package(idx, package, [])
    homeless = OrgPackage("npm:@acme/gone", "", "", "", users)
    assert "defined by no single active repo" in render_package(idx, homeless, [])


def test_render_choices() -> None:
    packages = [OrgPackage("go:x/a/api", "", "", "", ()), OrgPackage("go:x/b/api", "", "", "", ())]
    assert "could be any of these" in render_choices(packages, "api")
    assert "No package of the org is called 'zzz'" in render_choices([], "zzz")


def test_index_cache_round_trip(tmp_path: Path) -> None:
    idx = index(record("lib", defines=[("go:github.com/acme/lib", "go.mod", "Lib")]))
    path = tmp_path / "orgs" / "acme.packages.json"
    save_index(path, idx)
    assert load_index(path) == idx
    path.write_text("{broken", encoding="utf-8")
    assert load_index(path) is None


def test_packages_tool_caches_and_shows_one_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".cairn").mkdir()
    (tmp_path / ".cairn" / "config.yaml").write_text("orgs:\n  - org: acme\n", encoding="utf-8")
    built: list[PackageIndex | None] = []

    def fake_build(client: object, org: str, host: str, *, previous: object) -> PackageIndex:
        built.append(previous)  # type: ignore[arg-type]
        return index(
            record("hclog", defines=[("go:github.com/acme/hclog", "go.mod", "Logs")]),
            record("svc", uses=[("go:github.com/acme/hclog", "go.mod")]),
        )

    def no_search(client: object, org: str, package: object) -> object:
        raise CairnError("code search is rate limited")

    monkeypatch.setattr(tools, "client_for", lambda source: object())
    monkeypatch.setattr(tools, "build_index", fake_build)
    monkeypatch.setattr(tools, "usage_files", no_search)
    monkeypatch.setattr(tools, "datetime", type("D", (), {"now": staticmethod(lambda tz: NOW)}))
    listed = tools.packages_text(tmp_path)
    assert "github.com/acme/hclog (Go) · 1 repos" in listed and built == [None]
    assert tools.packages_text(tmp_path) == listed and len(built) == 1  # from the cache
    one = tools.packages_text(tmp_path, "hclog")
    assert "defined in acme/hclog/go.mod" in one and "code search is rate limited" in one
    assert "No package of the org is called" in tools.packages_text(tmp_path, "kafka")
    tools.packages_text(tmp_path, refresh=True)
    assert len(built) == 2 and built[1] is not None  # a refresh starts from the last index
    assert (tmp_path / ".cairn" / "cache" / "orgs" / "github.com" / "acme.packages.json").is_file()


def test_a_gitlab_groups_packages_reach_into_subgroups() -> None:
    from cairn.org.profile import under_org

    idx = index(
        record("platform/kit", description="Shared kit"),  # no manifest defines the module
        record("platform/log", defines=[("npm:@acme/log", "package.json", "")]),
        record(
            "svc",
            uses=[
                ("go:gitlab.com/acme/platform/kit/retry", "go.mod"),
                ("go:gitlab.com/acme/platform/kit", "go.mod"),
                ("npm:@acme/log", "package.json"),
                ("go:gitlab.com/other/kit", "go.mod"),  # another group's
            ],
        ),
    ).model_copy(update={"org": "acme/platform", "host": "gitlab.com"})
    found = {p.name: p for p in org_packages(idx)}
    assert found["go:gitlab.com/acme/platform/kit/retry"].home == "acme/platform/kit"
    assert found["go:gitlab.com/acme/platform/kit/retry"].description == ""  # a part of kit
    assert found["npm:@acme/log"].home == "acme/platform/log"  # npm scopes name the top group
    assert found["go:gitlab.com/acme/platform/kit"].description == "Shared kit"  # its root
    assert "go:gitlab.com/other/kit" not in found
    assert under_org("npm:@acme/x", "acme/platform", "gitlab.com")
    assert under_org("go:gitlab.com/acme/platform/x", "acme/platform", "gitlab.com")
    assert not under_org("go:gitlab.com/acme/x", "acme/platform", "gitlab.com")


def test_usage_files_in_a_subgroup_org() -> None:
    hits = (
        CodeHit("acme/platform/svc", "main.go", ()),
        CodeHit("acme/other/svc", "main.go", ()),  # the top group, outside the subgroup
    )
    client = FakeGitHub([], {}, {}, hits=hits)
    package = OrgPackage("go:gitlab.com/acme/platform/kit", "acme/platform/kit", "go.mod", "", ())
    files = usage_files(client, "acme/platform", package)  # type: ignore[arg-type]
    assert [(f.repo, f.path) for f in files] == [("acme/platform/svc", "main.go")]
