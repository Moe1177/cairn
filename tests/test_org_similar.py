"""find_similar and the org tools: an org's prior art over the API (a fake client answers)."""

import threading
from pathlib import Path

import pytest

from cairn.config import CairnConfig, OrgSource
from cairn.errors import CairnError
from cairn.mcp_server import tools
from cairn.org import access
from cairn.org.access import client_for, org_repo, pick_org
from cairn.org.similar import (
    MAX_TERMS,
    SimilarResult,
    clean_terms,
    find_similar,
    render_similar,
    weight,
)
from cairn.remote.github import CodeHit, SearchPage


class FakeGitHub:
    def __init__(self, results: dict[str, list[str]], waited: float = 0.0) -> None:
        self.results = results  # search words -> "owner/repo:path" hits, best first
        self.waited = waited
        self.queries: list[str] = []
        self.threads: set[str] = set()
        self.files: dict[str, str] = {}
        self._lock = threading.Lock()

    def search_code(self, query: str, *, per_page: int = 10) -> SearchPage:
        with self._lock:
            self.queries.append(query)
            self.threads.add(threading.current_thread().name)
        words = query.rsplit(" org:", 1)[0]
        hits = tuple(
            CodeHit(spec.split(":", 1)[0], spec.split(":", 1)[1], (f"match for {words}",))
            for spec in self.results.get(words, [])[:per_page]
        )
        return SearchPage(hits, len(hits), ms=5.0, waited=self.waited)

    def read_file(self, repo: str, path: str, *, max_bytes: int = 200_000) -> str | None:
        return self.files.get(f"{repo}/{path}")

    def tree(self, repo: str, ref: str) -> tuple[tuple[str, ...], bool]:
        prefix = f"{repo}/"
        return tuple(k[len(prefix) :] for k in self.files if k.startswith(prefix)), False


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/limiter.py", 1.0),
        ("node_modules/express-rate-limit/index.js", 0.0),
        ("layer/python/botocore/signers.py", 0.0),
        (".venv/Lib/site-packages/aws_cdk/x.py", 0.0),
        ("cdk.out/asset.15d7b5a2d60a/botocore/x.py", 0.0),
        ("web/app.min.js", 0.0),
        ("tests/test_limiter.py", 0.4),
        ("src/limiter.test.ts", 0.4),
        ("config/limits.yaml", 0.3),
        ("README.md", 0.25),
        ("notebooks/demo.ipynb", 0.25),
    ],
)
def test_weight_by_kind_of_file(path: str, expected: float) -> None:
    assert weight(path) == expected


def test_clean_terms_keeps_searches_inside_the_org() -> None:
    terms = ["RateLimiter repo:other/x", "  RateLimiter  ", "org:evil", "path:src TokenBucket"]
    assert clean_terms(terms, "task") == ("RateLimiter", "path:src TokenBucket")
    assert clean_terms(["(repo:other/x)", "a,repo:b/c", "user:x-y z"], "t") == ("( )", "a,", "z")


def test_clean_terms_caps_and_falls_back_to_the_task() -> None:
    many = [f"Term{i}" for i in range(10)]
    assert len(clean_terms(many, "task")) == MAX_TERMS
    fallback = clean_terms([], "Verify Stripe webhook signatures")
    assert len(fallback) == 1 and "stripe" in fallback[0].lower()
    assert clean_terms(["   "], "") == ()


def test_find_similar_fuses_ranks_and_drops_vendored_copies() -> None:
    client = FakeGitHub(
        {
            "RateLimiter": [
                "acme/vendor-app:node_modules/limiter/index.js",
                "acme/docs:limits.md",
                "acme/gateway:src/limiter.py",
            ],
            "X-RateLimit-Remaining": ["acme/gateway:src/limiter.py", "acme/edge:rate.ts"],
        }
    )
    terms = ["RateLimiter", "X-RateLimit-Remaining"]
    result = find_similar(client, "acme", "throttle clients", terms)  # type: ignore[arg-type]
    paths = [f"{h.repo}/{h.path}" for h in result.hits]
    assert paths[0] == "acme/gateway/src/limiter.py"  # both searches found it
    assert result.hits[0].matched == ("RateLimiter", "X-RateLimit-Remaining")
    assert "acme/vendor-app/node_modules/limiter/index.js" not in paths
    assert paths.index("acme/edge/rate.ts") < paths.index("acme/docs/limits.md")  # code over docs
    assert result.searches == 2 and sorted(client.queries) == [
        "RateLimiter org:acme",
        "X-RateLimit-Remaining org:acme",
    ]


def test_searches_run_at_once_on_reused_threads() -> None:
    client = FakeGitHub({}, waited=3.0)
    first = find_similar(client, "acme", "t", ["a", "b", "c"])  # type: ignore[arg-type]
    find_similar(client, "acme", "t", ["a", "b", "c"])  # type: ignore[arg-type]
    assert first.waited == 3.0  # side by side: the longest wait, not the sum
    assert all(name.startswith("cairn-search") for name in client.threads)
    assert len(client.threads) <= MAX_TERMS  # the pool's threads (and connections) live on


def test_render_lists_hits_with_why_and_masks_secrets() -> None:
    client = FakeGitHub({"TokenBucket": ["acme/gateway:src/bucket.py", "other/fork:x.py"]})
    result = find_similar(client, "acme", "t", ["TokenBucket"])  # type: ignore[arg-type]
    text = render_similar(result)
    assert "Prior art in acme for `TokenBucket`: 1 files (1 searches" in text
    assert "- gateway/src/bucket.py  (matched TokenBucket)" in text
    assert "other/fork" not in text  # another owner's code never comes back
    assert "read_org_file" in text
    secret = SimilarResult("acme", ("x",), (), 10.0, 61.0, 1)
    assert "61s of it waiting for the host's rate limit" in render_similar(secret)
    assert "Nothing found" in render_similar(secret)


def test_fragments_are_redacted() -> None:
    class Leaky(FakeGitHub):
        def search_code(self, query: str, *, per_page: int = 10) -> SearchPage:
            hit = CodeHit("acme/app", "a.py", ('key = "AKIAIOSFODNN7EXAMPLE"',))
            return SearchPage((hit,), 1, 1.0)

    result = find_similar(Leaky({}), "acme", "t", ["key"])  # type: ignore[arg-type]
    assert "AKIAIOSFODNN7EXAMPLE" not in render_similar(result)


def test_pick_org() -> None:
    acme, beta = OrgSource(org="acme"), OrgSource(org="beta", host="git.beta.com")
    assert pick_org([acme]) == acme
    assert pick_org([acme, beta], "BETA") == beta
    with pytest.raises(CairnError, match="'other' isn't a configured org"):
        pick_org([acme], "other")  # a name in a call is no way to reach other private code
    with pytest.raises(CairnError, match="no org configured"):
        pick_org([])
    with pytest.raises(CairnError, match="several orgs are configured"):
        pick_org([acme, beta])
    with pytest.raises(CairnError, match="isn't a configured org"):
        pick_org([acme], "a b")


def test_client_for_is_one_per_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(access, "_CLIENTS", {})
    asked: list[str] = []
    monkeypatch.setattr(access, "github_token", lambda host: asked.append(host) or "tok")
    one = client_for(OrgSource(org="acme"))
    assert client_for(OrgSource(org="beta")) is one
    assert client_for(OrgSource(org="x", host="git.acme.com")) is not one
    assert asked == ["github.com", "git.acme.com"]


@pytest.mark.parametrize(
    "orgs",
    [[{"org": "a b"}], [{"org": "acme", "host": "https://github.com"}], [{"org": "-x"}]],
)
def test_config_orgs_are_checked(orgs: list[dict]) -> None:
    with pytest.raises(ValueError):
        CairnConfig.model_validate({"orgs": orgs})


def org_workspace(tmp_path: Path, config: str = "orgs:\n  - org: acme\n") -> Path:
    (tmp_path / ".cairn").mkdir()
    (tmp_path / ".cairn" / "config.yaml").write_text(config, encoding="utf-8")
    return tmp_path


def test_similar_tool_uses_the_configured_org(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeGitHub({"RateLimiter": ["acme/gateway:src/limiter.py"]})
    monkeypatch.setattr(tools, "client_for", lambda source: client)
    ws = org_workspace(tmp_path)
    text = tools.similar_text(ws, "throttle", ["RateLimiter"])
    assert "gateway/src/limiter.py" in text and client.queries == ["RateLimiter org:acme"]
    assert "Say what you're building" in tools.similar_text(ws, " ", [" "])


def test_search_org_tool_says_where_the_code_uses_the_terms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeGitHub({"ApiKey1": ["acme/dl-api:infra/template.yaml"]})
    monkeypatch.setattr(tools, "client_for", lambda source: client)
    ws = org_workspace(tmp_path)
    text = tools.search_org_text(ws, ["ApiKey1"])
    assert text.startswith("Uses in acme of `ApiKey1`: 1 files")
    assert "- dl-api/infra/template.yaml  (matched ApiKey1)" in text
    assert "isn't proof of no others" in text and client.queries == ["ApiKey1 org:acme"]
    assert "Give the names to search for" in tools.search_org_text(ws, [" "])
    assert "the exact export, metric" in tools.search_org_text(ws, ["nothing-uses-this"])


def test_similar_tool_without_orgs_says_how_to_add_one(tmp_path: Path) -> None:
    with pytest.raises(CairnError, match="orgs:"):
        tools.similar_text(org_workspace(tmp_path, ""), "t", ["x"])


def test_org_file_tool_numbers_lines_and_caps_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeGitHub({})
    client.files["acme/gateway/src/limiter.py"] = "\n".join(f"line {i}" for i in range(500))
    monkeypatch.setattr(tools, "client_for", lambda source: client)
    ws = org_workspace(tmp_path)
    text = tools.org_file_text(ws, "gateway", "/src/limiter.py")
    assert text.startswith("acme/gateway/src/limiter.py (500 lines)")
    assert "    1  line 0" in text and "… 100 more lines" in text
    missing = tools.org_file_text(ws, "gateway", "gone.py")
    assert missing.startswith("No file gone.py in acme/gateway.") and "- src/" in missing


def test_cli_similar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from cairn.cli import app

    client = FakeGitHub({"TokenBucket": ["acme/gateway:src/bucket.py"]})
    monkeypatch.setattr(tools, "client_for", lambda source: client)
    ws = org_workspace(tmp_path)
    monkeypatch.setattr("cairn.integrations.registry.find_workspace", lambda here: ws)
    result = CliRunner().invoke(app, ["similar", "throttle", "--terms", "TokenBucket,"])
    assert result.exit_code == 0, result.output
    assert "gateway/src/bucket.py" in result.output and client.queries == ["TokenBucket org:acme"]


@pytest.mark.parametrize(
    "path", ["app/Http/Requests/StoreUserRequest.php", "src/requests/client.py", "python/lib/x.py"]
)
def test_folders_that_merely_sound_vendored_are_code(path: str) -> None:
    assert weight(path) == 1.0


def test_one_failed_search_leaves_the_others_hits() -> None:
    class Flaky(FakeGitHub):
        def search_code(self, query: str, *, per_page: int = 10) -> SearchPage:
            if query.startswith("Bad"):
                raise CairnError("GitHub answered 503: busy")
            return super().search_code(query, per_page=per_page)

    client = Flaky({"Good": ["acme/a:src/good.py"]})
    result = find_similar(client, "acme", "t", ["Good", "Bad"])  # type: ignore[arg-type]
    assert [h.path for h in result.hits] == ["src/good.py"]
    assert result.failed == ("Bad: GitHub answered 503: busy",)
    assert "(a search failed: Bad: GitHub answered 503: busy)" in render_similar(result)
    with pytest.raises(CairnError, match="503"):
        find_similar(client, "acme", "t", ["Bad", "Bad again"])  # type: ignore[arg-type]


def test_org_repo_keeps_reads_inside_the_org() -> None:
    acme = OrgSource(org="acme")
    assert org_repo(acme, "gateway") == "acme/gateway"
    assert org_repo(acme, " ACME/gateway ") == "acme/gateway"
    with pytest.raises(CairnError, match="isn't in acme"):
        org_repo(acme, "someone-else/private")


def test_org_file_tool_refuses_other_owners_and_masks_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeGitHub({})
    client.files["acme/app/settings.py"] = 'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\nok = 1'
    client.files["acme/app/min.js"] = "x" * 100_000
    monkeypatch.setattr(tools, "client_for", lambda source: client)
    ws = org_workspace(tmp_path)
    assert "AKIAIOSFODNN7EXAMPLE" not in tools.org_file_text(ws, "app", "settings.py")
    with pytest.raises(CairnError, match="isn't in acme"):
        tools.org_file_text(ws, "other/app", "settings.py")
    with pytest.raises(CairnError, match="isn't a configured org"):
        tools.org_file_text(ws, "app", "settings.py", org="other")
    long = tools.org_file_text(ws, "app", "min.js")
    assert len(long) < 1_000  # a minified line is cut, not passed whole


def test_a_rejected_token_drops_the_cached_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Rejected(FakeGitHub):
        def search_code(self, query: str, *, per_page: int = 10) -> SearchPage:
            raise CairnError("GitHub rejected the token: log in again with `gh auth login`")

    forgotten: list[str] = []
    monkeypatch.setattr(tools, "client_for", lambda source: Rejected({}))
    monkeypatch.setattr(tools, "forget_client", lambda source: forgotten.append(source.org))
    with pytest.raises(CairnError, match="rejected the token"):
        tools.similar_text(org_workspace(tmp_path), "t", ["x"])
    assert forgotten == ["acme"]
