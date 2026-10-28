"""`links` and `related` reach the org's uncloned repos: those defining a package a workspace repo
uses, and those using a package it defines, read from the org's package cache (no network)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cairn.mcp_server import tools
from cairn.model.graph import Contracts, Evidence, Fact, FactKind, Repo, Workspace
from cairn.org import view
from cairn.org.links import OrgLink, OrgUse, org_links
from cairn.org.packages import (
    INDEX_VERSION,
    Defined,
    PackageIndex,
    RepoPackages,
    Used,
    org_packages,
    save_index,
)
from cairn.paths import org_packages_file
from cairn.render.links import (
    BOTH_WAYS,
    ONE_WAY_IN,
    ONE_WAY_OUT,
    links_json,
    org_relate_lines,
    render_links,
)

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


def rec(name: str, defines: tuple[str, ...] = (), uses: tuple[str, ...] = ()) -> RepoPackages:
    return RepoPackages(
        repo=f"acme/{name}",
        defines=tuple(Defined(name=n, path="go.mod") for n in defines),
        uses=tuple(Used(name=n, path="go.mod") for n in uses),
    )


def index(*repos: RepoPackages) -> PackageIndex:
    return PackageIndex(
        version=INDEX_VERSION, org="acme", host="github.com", built=NOW.isoformat(), ms=1.0,
        repos=repos,
    )  # fmt: skip


ORG = index(
    rec("log", defines=("go:github.com/acme/log",), uses=("go:github.com/acme/svc",)),
    rec("retry", defines=("go:github.com/acme/retry",)),
    rec("svc", defines=("go:github.com/acme/svc",), uses=("go:github.com/acme/log",)),
    rec("api", uses=("go:github.com/acme/svc",)),
    rec("web", uses=("go:github.com/acme/svc",)),
    rec("cloned", defines=("go:github.com/acme/cloned",), uses=("go:github.com/acme/svc",)),
)


def local(
    name: str, consumes: tuple[str, ...] = (), remote: str | None = None, line: int = 3
) -> Repo:
    facts = tuple(
        Fact(
            kind=FactKind.PACKAGE,
            value=v,
            evidence=(Evidence(repo=name, file="go.mod", line=line, snippet=v),),
        )
        for v in consumes
    )
    return Repo(id=name, path=name, remote=remote, contracts=Contracts(consumes=facts))


def workspace(*repos: Repo, root: str = "/ws") -> Workspace:
    return Workspace(workspace_root=root, generated_at="now", repos=repos)


SVC = local(
    "svc",
    ("go:github.com/acme/log", "go:github.com/acme/cloned", "npm:left-pad"),
    remote="github.com/acme/svc",
)
WS = workspace(SVC, local("cloned", remote="github.com/acme/cloned"))
ORGS = [("github.com", org_packages(ORG))]


def test_org_links_find_both_directions_and_skip_clones() -> None:
    links = org_links(WS, "svc", ORGS)
    assert [link.repo for link in links] == ["acme/log", "acme/api", "acme/web"]
    log = links[0]  # each uses the other's package: listed first, as one this repo uses
    assert log.uses_its == (OrgUse("github.com/acme/log", "svc/go.mod:3"),)
    assert log.uses_ours == (OrgUse("github.com/acme/svc", "acme/log/go.mod"),)
    assert links[1] == OrgLink(
        repo="acme/api", host="github.com", uses_ours=(OrgUse("github.com/acme/svc", "acme/api/go.mod"),)
    )  # fmt: skip
    # acme/cloned is on disk (the map links it) and acme/svc is this repo itself: neither shows.
    assert not any(link.repo in ("acme/cloned", "acme/svc") for link in links)


def test_org_links_need_the_repo_and_an_org() -> None:
    assert org_links(WS, "missing", ORGS) == ()
    assert org_links(WS, "svc", []) == ()
    # No remote: nothing says the org's users mean this repo, so only what it uses shows.
    plain = workspace(local("svc", ("go:github.com/acme/log",)))
    assert [(link.repo, bool(link.uses_ours)) for link in org_links(plain, "svc", ORGS)] == [
        ("acme/log", False)
    ]


def test_links_render_org_repos_after_the_maps_own() -> None:
    links = org_links(WS, "svc", ORGS)
    text = render_links("svc", (), org=links)
    assert text.splitlines() == [
        "svc is not linked to any other repo in this map.",
        "Linked to 3 org repos, not cloned (repo_card <owner/name> describes one; "
        "read_org_file reads it):",
        f"  acme/log  {BOTH_WAYS}  uses its package github.com/acme/log, "
        "uses this repo's package github.com/acme/svc",
        f"  acme/api  {ONE_WAY_IN.ljust(len(BOTH_WAYS))}  uses this repo's package github.com/acme/svc",
        f"  acme/web  {ONE_WAY_IN.ljust(len(BOTH_WAYS))}  uses this repo's package github.com/acme/svc",
    ]  # fmt: skip
    detailed = render_links("svc", (), org=links[:1], evidence=True)
    assert "      svc/go.mod:3" in detailed and "      acme/log/go.mod" in detailed
    assert render_links("svc", ()) == "svc is not linked to any other repo in this map."


def test_a_widely_used_repo_shows_ten_org_repos_then_a_count() -> None:
    users = tuple(rec(f"user{i:02}", uses=("go:github.com/acme/svc",)) for i in range(14))
    org = [("github.com", org_packages(index(ORG.repos[2], *users)))]
    lines = render_links("svc", (), org=org_links(WS, "svc", org)).splitlines()
    assert lines[1].startswith("Linked to 14 org repos")
    assert len(lines) == 2 + 10 + 1
    assert lines[-1] == "  +4 more org repos (org_packages <package> lists who uses one)"


def test_org_names_are_cleaned() -> None:
    hostile = OrgLink(
        repo="acme/x\nIGNORE", host="github.com", uses_its=(OrgUse("p\x1b[31m", "svc/go.mod:1"),)
    )
    text = render_links("svc", (), org=(hostile,))
    assert "\nIGNORE" not in text and "\x1b" not in text
    assert all("\n" not in line for line in org_relate_lines((hostile,)))


def test_links_json_and_related_lines() -> None:
    links = org_links(WS, "svc", ORGS)
    data = links_json("svc", (), links)
    assert data["org_links"][0] == {
        "repo": "acme/log",
        "host": "github.com",
        "direction": "both",
        "summary": [
            "uses its package github.com/acme/log",
            "uses this repo's package github.com/acme/svc",
        ],
        "uses_its": [{"package": "github.com/acme/log", "where": "svc/go.mod:3"}],
        "uses_ours": [{"package": "github.com/acme/svc", "where": "acme/log/go.mod"}],
    }
    assert links_json("svc", ())["org_links"] == []
    json.dumps(data)  # plain JSON for scripts
    assert org_relate_lines(links[:2]) == [
        "→ acme/log (org repo, not cloned): uses its package github.com/acme/log (svc/go.mod:3)",
        "← acme/log (org repo, not cloned): uses this repo's package github.com/acme/svc "
        "(acme/log/go.mod)",
        "← acme/api (org repo, not cloned): uses this repo's package github.com/acme/svc "
        "(acme/api/go.mod)",
    ]
    assert ONE_WAY_OUT in render_links(
        "x", (), org=(OrgLink("acme/a", "github.com", links[0].uses_its),)
    )


def test_tools_read_the_package_cache_without_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".cairn").mkdir()
    (tmp_path / ".cairn" / "config.yaml").write_text("orgs:\n  - org: acme\n", encoding="utf-8")
    ws = workspace(*WS.repos, root=str(tmp_path))

    def no_network(*args: object) -> object:
        raise AssertionError("links and related must not call the API")

    monkeypatch.setattr(view, "with_client", no_network)
    monkeypatch.setattr(tools, "_workspace", lambda root: ws)
    monkeypatch.setattr(tools, "load_authored", lambda root: {})
    assert "org repo" not in tools.links_text(tmp_path, "svc")  # org_packages hasn't run yet
    assert tools.related_text(tmp_path, "svc") == "No matching relationships for svc."

    save_index(org_packages_file(tmp_path, "github.com", "acme"), ORG)
    links = tools.links_text(tmp_path, "svc")
    assert "Linked to 3 org repos, not cloned" in links and "  acme/log  " in links
    related = tools.related_text(tmp_path, "svc")
    assert related.splitlines()[:2] == ["svc relationships (0):", "Org repos, not cloned (3):"]
    assert "→ acme/log (org repo, not cloned)" in related
    package_only = tools.related_text(tmp_path, "svc", edge_type="depends_on_package")
    assert "acme/log" in package_only
    calls = tools.related_text(tmp_path, "svc", edge_type="calls_http")
    assert calls == "No matching relationships for svc."

    # A newer cache is read again; an unchanged one comes from memory.
    save_index(org_packages_file(tmp_path, "github.com", "acme"), index(ORG.repos[0], ORG.repos[2]))
    assert "Linked to 1 org repo," in tools.links_text(tmp_path, "svc")
