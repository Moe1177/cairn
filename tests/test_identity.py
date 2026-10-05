from pathlib import Path

from cairn.detectors.base import DetectorResult, combine_results, find_line, merge_facts
from cairn.detectors.identity import IdentityDetector, clean_aliases, first_paragraph
from cairn.detectors.manifests import parse_go_mod, pep508_name, requirements_names
from cairn.model.graph import Evidence, Fact, FactKind
from tests.helpers import ctx_for, make_repo


def test_aliases_from_manifests(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "shared-ui", {"package.json": '{"name": "@eats/ui"}'})
    result = IdentityDetector().run(ctx_for(tmp_path, repo))
    assert result.aliases == ("shared-ui", "@eats/ui", "ui")


def test_generic_manifest_names_are_not_aliases(tmp_path: Path) -> None:
    # Review Focus 1: the real shopapp app is named "my-app".
    repo = make_repo(tmp_path, "shopapp", {"my-app/package.json": '{"name": "my-app"}'})
    ctx = ctx_for(tmp_path, repo, app_roots=[repo / "my-app"])
    assert IdentityDetector().run(ctx).aliases == ("shopapp",)


def test_python_go_and_cargo_names(tmp_path: Path) -> None:
    py = make_repo(tmp_path, "common", {"pyproject.toml": '[project]\nname = "Shopverse_Common"\n'})
    go = make_repo(tmp_path, "payments", {"go.mod": "module github.com/acme/payments\n"})
    rs = make_repo(tmp_path, "ledger", {"Cargo.toml": '[package]\nname = "ledger-core"\n'})
    assert IdentityDetector().run(ctx_for(tmp_path, py)).aliases == ("common", "shopverse-common")
    assert IdentityDetector().run(ctx_for(tmp_path, go)).aliases == (
        "payments",
        "github.com/acme/payments",
    )
    assert IdentityDetector().run(ctx_for(tmp_path, rs)).aliases == ("ledger", "ledger-core")


def test_clean_aliases_keeps_id_and_dedupes() -> None:
    assert clean_aliases(["Admin", "admin", "app", "x"], "resumeapp") == ("resumeapp", "admin")
    assert clean_aliases(["portal"], "r", frozenset({"portal"})) == ("r",)


def test_readme_excerpt_skips_headings_and_badges(tmp_path: Path) -> None:
    readme = (
        "# eats\n\n[![ci](https://x/badge.svg)](https://x)\n\n"
        "Home-cooked meal [marketplace](https://eats.example) connecting\nlocal cooks.\n\nMore text.\n"
    )
    repo = make_repo(tmp_path, "eats", {"README.md": readme})
    result = IdentityDetector().run(ctx_for(tmp_path, repo))
    assert result.readme_excerpt == "Home-cooked meal marketplace connecting local cooks."


def test_readme_missing_gives_none(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "bare")
    assert IdentityDetector().run(ctx_for(tmp_path, repo)).readme_excerpt is None


def test_first_paragraph_caps_length() -> None:
    text = first_paragraph("word " * 200)
    assert text is not None and len(text) == 300 and text.endswith("…")


def test_manifest_helpers() -> None:
    assert pep508_name("Requests[socks]>=2.0; python_version>'3'") == "Requests"
    assert requirements_names("# c\n-r base.txt\nfastapi==0.110\n\nuvicorn\n") == (
        "fastapi",
        "uvicorn",
    )
    module, requires = parse_go_mod(
        "module github.com/acme/payments\n\nrequire github.com/acme/money v0.1.0\n"
        "require (\n\tgithub.com/gin-gonic/gin v1.9.0 // indirect\n)\n"
    )
    assert module == "github.com/acme/payments"
    assert requires == ("github.com/acme/money", "github.com/gin-gonic/gin")


def test_merge_and_combine_helpers() -> None:
    ev = [Evidence(repo="r", file="f", line=i, snippet="") for i in range(1, 6)]
    facts = [Fact(kind=FactKind.DB_TABLE, value="orders", evidence=(e,)) for e in ev]
    merged = merge_facts(facts)
    assert len(merged) == 1 and len(merged[0].evidence) == 3
    combined = combine_results(
        [
            DetectorResult(aliases=("a",), readme_excerpt=None),
            DetectorResult(aliases=("a", "b"), readme_excerpt="x"),
        ]
    )
    assert combined.aliases == ("a", "b") and combined.readme_excerpt == "x"
    assert find_line("one\ntwo\n", "two") == (2, "two")
    assert find_line("one\n", "zzz") == (1, "one")


def test_readme_excerpt_skips_boilerplate_and_junk() -> None:
    # Found while dogfooding: every create-next-app README looked identical.
    nextjs = (
        "This is a [Next.js](https://nextjs.org) project bootstrapped with "
        "[`create-next-app`](https://github.com/vercel/next.js).\n\n## Getting Started\n"
    )
    assert first_paragraph(nextjs) is None
    assert (
        first_paragraph("This project was generated with [Angular CLI](https://x) version 17.\n")
        is None
    )
    assert first_paragraph("**1**\n\nPractice notes for data science interviews.\n") == (
        "Practice notes for data science interviews."
    )
    assert first_paragraph("> Cairns are stacked-stone trail markers.\n") == (
        "Cairns are stacked-stone trail markers."
    )


def test_scaffold_readme_yields_no_excerpt_at_all() -> None:
    scaffold = (
        "This is a [Next.js](https://nextjs.org) project bootstrapped with `create-next-app`.\n\n"
        "First, run the development server:\n\n```bash\nnpm run dev\n```\n"
    )
    assert first_paragraph(scaffold) is None
