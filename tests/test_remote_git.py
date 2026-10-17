"""Plain git orgs: repo URLs in the config, and the client that reads them through git itself
(real repos on disk, served over file://, which only these tests allow)."""

import shutil
import subprocess
from pathlib import Path

import pytest

from cairn.config import OrgSource
from cairn.errors import CairnError
from cairn.org import access
from cairn.org.access import client_for, org_repo
from cairn.org.catalog import CatalogRepo, render_org_card
from cairn.org.packages import build_index, org_packages
from cairn.remote.gitrepos import HEADS_TTL, GitRepos, _parse_head, _reason
from cairn.remote.giturl import repo_url

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@e.com", "-c", "commit.gpgsign=false"]
        + list(args),
        cwd=cwd,
        check=True,
        capture_output=True,
    )
    return done.stdout.decode()


def _origin(root: Path, name: str, files: dict[str, bytes | str]) -> str:
    """A repo with one commit of `files` that serves partial clones; its file:// URL."""
    where = root / "origin" / name
    where.mkdir(parents=True)
    _git(where, "init", "-q", "-b", "main")
    _git(where, "config", "uploadpack.allowFilter", "true")
    _git(where, "config", "uploadpack.allowAnySHA1InWant", "true")
    _commit(where, files)
    return where.as_uri()


def _commit(where: Path, files: dict[str, bytes | str]) -> None:
    for path, body in files.items():
        target = where / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            target.write_bytes(body)
        else:
            target.write_text(body, encoding="utf-8", newline="\n")
    _git(where, "add", "-A")
    _git(where, "commit", "-q", "-m", "files")


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _client(tmp_path: Path, repos: dict[str, str], clock: Clock | None = None) -> GitRepos:
    return GitRepos(
        "acme",
        "git.acme.io",
        repos,
        cache=tmp_path / "cache",
        protocols=("file",),
        clock=clock or Clock(),
    )


def _missing(clone: Path) -> set[str]:
    """Blobs the clone doesn't have yet (git lists them with a "?" and fetches nothing)."""
    out = _git(clone, "rev-list", "--objects", "--missing=print", "--all")
    return {line[1:] for line in out.splitlines() if line.startswith("?")}


FILES: dict[str, bytes | str] = {
    "README.md": "﻿# api\nThe orders API.\n",
    "package.json": '{"name": "@acme/api", "dependencies": {"@acme/kit": "1"}}',
    "src/main.go": "package main\n",
    "logo.png": b"\x89PNG\r\n\x1a\n\x00\x00binary",
    "big.txt": "x" * 5000,
}


def test_a_listed_repo_is_cloned_without_its_files_then_read(tmp_path: Path) -> None:
    url = _origin(tmp_path, "acme/api", FILES)
    client = _client(tmp_path, {"acme/api": url})
    (info,) = client.list_repos("acme")
    assert info.name == "acme/api" and info.default_branch == "main" and len(info.pushed) == 40
    paths, cut = client.tree("acme/api", "main")
    assert sorted(paths) == sorted(FILES) and not cut
    clone = client._clone_dir("acme/api")
    assert clone.parent == tmp_path / "cache" / "git" / "git.acme.io"
    assert clone.name.startswith("api-") and clone != client._clone_dir("acme/platform/api")
    assert len(_missing(clone)) == len(FILES)  # the tree came, the files didn't
    client.prefetch("acme/api", ["README.md", "package.json", "no/such/file"])
    assert len(_missing(clone)) == len(FILES) - 2  # both, in one fetch
    again = _client(tmp_path, {"acme/api": url})  # a new process, the clone on disk
    calls: list[list[str]] = []
    real = again._git

    def spy(args: list[str], **kw: object) -> bytes:
        calls.append(list(args))
        return real(args, **kw)  # type: ignore[arg-type]

    again._git = spy  # type: ignore[method-assign]
    again.prefetch("acme/api", ["README.md", "package.json"])
    assert calls and not [args for args in calls if "fetch" in args]  # both there already
    assert client.read_file("acme/api", "README.md") == "# api\nThe orders API.\n"  # BOM gone
    assert client.read_file("acme/api", "/src/main.go") == "package main\n"  # fetched on its own
    assert client.read_file("acme/api", "logo.png") is None  # binary
    assert client.read_file("acme/api", "big.txt", max_bytes=1000) is None  # too long
    assert client.read_file("acme/api", "src") is None  # a folder isn't a file
    assert client.read_file("acme/api", "nope.md") is None
    assert client.file_exists("acme/api", "src/main.go")
    assert not client.file_exists("acme/api", "src")
    assert client.remaining() is None


def test_a_new_commit_is_fetched_once_its_tip_is_seen(tmp_path: Path) -> None:
    url = _origin(tmp_path, "acme/api", {"README.md": "one"})
    clock = Clock()
    client = _client(tmp_path, {"acme/api": url}, clock)
    first = client.list_repos("acme")[0].pushed
    assert client.tree("acme/api", "main")[0] == ("README.md",)
    _commit(tmp_path / "origin" / "acme" / "api", {"go.mod": "module git.acme.io/acme/api\n"})
    assert client.list_repos("acme")[0].pushed == first  # the tip is kept a while
    clock.now += HEADS_TTL + 1
    second = client.list_repos("acme")[0].pushed
    assert second != first
    assert sorted(client.tree("acme/api", "main")[0]) == ["README.md", "go.mod"]
    assert client.read_file("acme/api", "go.mod") == "module git.acme.io/acme/api\n"
    # A new process finds the clone on disk and only fetches what's new.
    again = _client(tmp_path, {"acme/api": url})
    assert sorted(again.tree("acme/api", "main")[0]) == ["README.md", "go.mod"]


def test_empty_and_unreachable_repos(tmp_path: Path) -> None:
    url = _origin(tmp_path, "acme/api", {"README.md": "one"})
    empty = tmp_path / "origin" / "acme" / "empty"
    empty.mkdir(parents=True)
    _git(empty, "init", "-q", "-b", "main")
    gone = (tmp_path / "origin" / "acme" / "gone").as_uri()
    client = _client(tmp_path, {"acme/api": url, "acme/empty": empty.as_uri(), "acme/gone": gone})
    api, nothing, missing = client.list_repos("acme")
    assert (nothing.default_branch, nothing.pushed) == ("", "")
    assert (missing.default_branch, missing.pushed) == ("", "")
    assert client.tree("acme/empty", "") == ((), False)
    with pytest.raises(CairnError, match="git couldn't reach acme/gone"):
        client.tree("acme/gone", "")
    assert api.default_branch == "main"
    alone = _client(tmp_path, {"acme/gone": gone})
    with pytest.raises(CairnError, match="log in once with git itself"):
        alone.list_repos("acme")  # nothing on the page answered: say why


def test_only_listed_repos_and_allowed_transports(tmp_path: Path) -> None:
    url = _origin(tmp_path, "acme/api", {"README.md": "one"})
    client = _client(tmp_path, {"acme/api": url})
    with pytest.raises(CairnError, match="isn't one of the repos acme lists"):
        client.read_file("acme/secret", "README.md")
    assert client.list_repos("other") == ()
    assert client.list_repos("acme", page=2) == ()
    with pytest.raises(CairnError, match="no code search"):
        client.search_code("RateLimiter org:acme")
    strict = GitRepos("acme", "git.acme.io", {"acme/api": url}, cache=tmp_path / "strict")
    with pytest.raises(CairnError, match="transport 'file' not allowed"):
        strict.list_repos("acme")  # file:// isn't https or ssh: git refuses it


def test_the_transport_limit_beats_the_users_git_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = _origin(tmp_path, "acme/api", {"README.md": "one"})
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")  # as if in ~/.gitconfig
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "protocol.file.allow")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "always")
    strict = GitRepos("acme", "git.acme.io", {"acme/api": url}, cache=tmp_path / "strict")
    with pytest.raises(CairnError, match="transport 'file' not allowed"):
        strict.list_repos("acme")


def test_one_unreachable_repo_past_the_first_page_fails_nothing(tmp_path: Path) -> None:
    url = _origin(tmp_path, "acme/api", {"README.md": "one"})
    gone = (tmp_path / "origin" / "acme" / "gone").as_uri()
    client = _client(tmp_path, {"acme/api": url, "acme/gone": gone})
    (missing,) = client.list_repos("acme", page=2, per_page=1)  # only the unreachable one
    assert (missing.name, missing.default_branch) == ("acme/gone", "")
    with pytest.raises(CairnError, match="git couldn't reach acme/gone"):
        client.tree("acme/gone", "")


def test_a_head_naming_a_missing_branch_is_no_empty_repo(tmp_path: Path) -> None:
    url = _origin(tmp_path, "acme/api", {"README.md": "one"})
    _git(tmp_path / "origin" / "acme" / "api", "symbolic-ref", "HEAD", "refs/heads/master")
    fine = _origin(tmp_path, "acme/fine", {"README.md": "two"})
    client = _client(tmp_path, {"acme/api": url, "acme/fine": fine})
    broken, _ = client.list_repos("acme")
    assert broken.default_branch == ""
    with pytest.raises(CairnError, match="HEAD names no branch it has"):
        client.tree("acme/api", "")


def test_prefetch_never_fails_a_read(tmp_path: Path) -> None:
    url = _origin(tmp_path, "acme/api", {"README.md": "one"})
    clock = Clock()
    client = _client(tmp_path, {"acme/api": url}, clock)
    client.tree("acme/api", "main")
    (tmp_path / "origin").rename(tmp_path / "moved")
    clock.now += HEADS_TTL + 1  # its tip must be asked for again, and can't be
    client.prefetch("acme/api", ["README.md"])  # best effort: no error
    with pytest.raises(CairnError, match="git couldn't reach"):
        client.read_file("acme/api", "README.md")  # the read says why


def test_an_unreachable_repo_keeps_what_the_index_knew(tmp_path: Path) -> None:
    kit = _origin(tmp_path, "acme/kit", {"package.json": '{"name": "@acme/kit"}'})
    api = _origin(tmp_path, "acme/api", {"package.json": '{"dependencies": {"@acme/kit": "1"}}'})
    clock = Clock()
    client = _client(tmp_path, {"acme/kit": kit, "acme/api": api}, clock)
    first = build_index(client, "acme", "git.acme.io")
    (tmp_path / "origin" / "acme" / "kit").rename(tmp_path / "moved")
    clock.now += HEADS_TTL + 1
    second = build_index(client, "acme", "git.acme.io", previous=first)
    (record,) = [r for r in second.repos if r.repo == "acme/kit"]
    assert record.failed and record.defines == first.repos[0].defines  # kept, marked failed


def test_a_killed_fetchs_lock_is_cleared(tmp_path: Path) -> None:
    import os

    url = _origin(tmp_path, "acme/api", {"README.md": "one"})
    clock = Clock()
    client = _client(tmp_path, {"acme/api": url}, clock)
    client.tree("acme/api", "main")
    lock = client._clone_dir("acme/api") / "shallow.lock"
    lock.write_text("")
    os.utime(lock, (1, 1))  # long ago
    _commit(tmp_path / "origin" / "acme" / "api", {"go.mod": "module m\n"})
    clock.now += HEADS_TTL + 1
    assert sorted(client.tree("acme/api", "main")[0]) == ["README.md", "go.mod"]
    assert not lock.exists()


def test_the_package_index_reads_plain_git_repos(tmp_path: Path) -> None:
    kit = _origin(
        tmp_path, "acme/kit", {"package.json": '{"name": "@acme/kit", "description": "Kit"}'}
    )
    api = _origin(tmp_path, "acme/api", FILES)
    client = _client(tmp_path, {"acme/kit": kit, "acme/api": api})
    index = build_index(client, "acme", "git.acme.io")
    assert index.reread == 2 and index.unread == 0
    (package,) = [p for p in org_packages(index) if p.name == "npm:@acme/kit"]
    assert package.home == "acme/kit" and package.description == "Kit"
    assert [user for user, _ in package.users] == ["acme/api"]
    again = build_index(client, "acme", "git.acme.io", previous=index)
    assert again.reread == 0  # tips unchanged: nothing read again


def test_parse_head() -> None:
    sha = "a" * 40
    assert _parse_head(f"ref: refs/heads/trunk\tHEAD\n{sha}\tHEAD\n") == ("trunk", sha)
    assert _parse_head(f"{sha}\tHEAD\n") == ("HEAD", sha)  # the host didn't name the branch
    assert _parse_head("ref: refs/heads/main\tHEAD\n") == ("", "")  # empty repo
    assert _parse_head("") == ("", "")


@pytest.mark.parametrize(
    ("url", "found"),
    [
        ("https://git.acme.io/acme/api.git", ("git.acme.io", "acme/api")),
        ("https://Git.Acme.io:8443/acme/platform/api", ("git.acme.io", "acme/platform/api")),
        ("ssh://git@Git.acme.io:7999/acme/api.git", ("git.acme.io", "acme/api")),
        ("https://deploy@git.acme.io/acme/api", None),  # a login in an https URL
        ("https://ghp_SECRET@git.acme.io/acme/api", None),  # a token as the user
        ("https://user%3Apass@git.acme.io/acme/api", None),
        ("https://127.0.0.2\\@127.0.0.1:9/acme/api", None),  # parsers disagree on the host
        ("https://git.acme.io/acme/%2e%2e/api", None),
        ("HTTPS://git.acme.io/acme/api", None),  # git refuses the scheme so spelled
        ("ssh://-oProxyCommand=evil/acme/api", None),
        ("git@-oProxy:acme/api", None),
        ("https://git.acme.io:99999/acme/api", None),
        ("git@git.acme.io:acme/api.git", ("git.acme.io", "acme/api")),
        ("https://git.sr.ht/~sircmpwn/hare", ("git.sr.ht", "~sircmpwn/hare")),
        ("https://codeberg.org/forgejo/.profile.git", ("codeberg.org", "forgejo/.profile")),
        ("https://git.acme.io/acme/./api", None),
        ("https://git.acme.io/../acme/api", None),
        ("https://user:hunter2@git.acme.io/acme/api.git", None),  # a password in the URL
        ("http://git.acme.io/acme/api.git", None),
        ("file:///srv/git/acme/api.git", None),
        ("ext::sh -c touch% /tmp/pwned", None),
        ("-oProxyCommand=evil", None),
        ("/srv/git/acme/api.git", None),
        ("https://git.acme.io/acme/../secret", None),
        ("https://git.acme.io/acme/api?x=1", None),
        ("https://git.acme.io/", None),
    ],
)
def test_repo_url(url: str, found: tuple[str, str] | None) -> None:
    assert repo_url(url) == found


def test_config_lists_a_plain_git_org() -> None:
    source = OrgSource(
        org="acme",
        repos=("https://git.acme.io/acme/api.git", "git@git.acme.io:acme/platform/web.git"),
    )
    assert (source.kind, source.host) == ("git", "git.acme.io")  # both from the URLs
    assert source.repo_urls() == {
        "acme/api": "https://git.acme.io/acme/api.git",
        "acme/platform/web": "git@git.acme.io:acme/platform/web.git",
    }
    hut = OrgSource(org="~sircmpwn", repos=("https://git.sr.ht/~sircmpwn/hare",))
    assert hut.kind == "git"


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"repos": ("https://u:hunter2@git.acme.io/acme/a",)}, "repo 1: give an https URL"),
        ({"repos": ("https://hunter2@git.acme.io/acme/a",)}, "repo 1: give an https URL"),
        ({"repos": ("https://git.acme.io/other/a",)}, "isn't a repo of git.acme.io/acme"),
        ({"repos": 5}, "tuple"),  # pydantic's own: no crash
        ({"host": "github.com", "repos": ("https://x.io/acme/a",)}, "isn't a repo of github.com"),
        ({"repos": ("https://git.acme.io/acme/a", "git@git.acme.io:acme/A.git")}, "listed twice"),
        ({"kind": "git"}, "lists its repos"),
        (
            {"host": "gitlab.com", "kind": "gitlab", "repos": ("https://gitlab.com/acme/a",)},
            "repos:",
        ),
    ],
)
def test_config_refuses_bad_repo_lists(fields: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message) as caught:
        OrgSource(org="acme", **fields)  # type: ignore[arg-type]
    assert "hunter2" not in caught.value.errors()[0]["msg"]  # never echoes a password


def test_client_for_a_plain_git_org(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(access, "_CLIENTS", {})
    one = OrgSource(org="acme", repos=("https://git.acme.io/acme/api.git",))
    two = OrgSource(org="acme/platform", repos=("https://git.acme.io/acme/platform/web.git",))
    client = client_for(one)
    assert isinstance(client, GitRepos)
    assert client_for(one) is client
    assert client_for(two) is not client  # each list is its own client
    edited = one.model_copy(update={"repos": (*one.repos, "https://git.acme.io/acme/web.git")})
    assert client_for(edited) is not client  # the list changed: a client that knows it
    assert org_repo(one, "platform/web") == "acme/platform/web"  # a path inside the org


def test_a_plain_git_card_promises_no_search() -> None:
    repo = CatalogRepo(name="acme/api", pushed="a" * 40)
    card = render_org_card(repo, searchable=False)
    assert "find_similar" not in card and "Last push" not in card  # a commit id isn't a time
    assert card.endswith("(repo acme/api, path README.md first).")
    dated = render_org_card(CatalogRepo(name="acme/api", pushed="2026-10-01T10:00:00Z"))
    assert "Last push: 2026-10-01" in dated and "find_similar searches" in dated


def test_a_busy_host_is_retried_then_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    busy = b"fatal: unable to access 'https://git.acme.io/acme/api.git/': The requested URL returned error: 429"
    answers = [busy, busy, b""]
    calls: list[list[str]] = []

    def run(args: list[str], **kw: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(args)
        failed = answers.pop(0)
        out = b"" if failed else f"ref: refs/heads/main\tHEAD\n{'b' * 40}\tHEAD\n".encode()
        return subprocess.CompletedProcess(args, 128 if failed else 0, out, failed)

    waits: list[float] = []
    client = GitRepos(
        "acme",
        "git.acme.io",
        {"acme/api": "https://git.acme.io/acme/api.git"},
        cache=tmp_path,
        sleep=waits.append,
    )
    monkeypatch.setattr(subprocess, "run", run)
    assert client.list_repos("acme")[0].pushed == "b" * 40  # the third try answered
    assert waits == [2.0, 4.0] and len(calls) == 3
    answers[:] = [busy] * 3
    client._heads.clear()
    with pytest.raises(CairnError, match="limiting requests") as caught:
        client.list_repos("acme")
    assert "log in" not in str(caught.value)


def test_gits_reason_is_its_fatal_line() -> None:
    stderr = "remote: Not found\nfatal: repository 'x' not found\nPlease make sure you have the\nand the repository exists.\n"
    assert _reason(stderr) == "fatal: repository 'x' not found"
    assert _reason("error: something\n") == "error: something"
    assert _reason("") == "no reason given"
