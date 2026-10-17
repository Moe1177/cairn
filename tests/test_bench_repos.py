"""The org-repos benchmark: keys, the agent's search queries, and scoring (no model, no network)."""

from pathlib import Path

import yaml

from cairn.bench.org_repos import (
    QUERIES_FILE,
    RepoSet,
    evaluate,
    load_queries,
    parse_query,
    query_prompt,
    report,
    write_queries,
)
from cairn.org.catalog import CatalogRepo, OrgCatalog

KEY = {
    "org": "acme",
    "split": "dev",
    "queries": [
        {
            "id": "aws",
            "query": "the terraform provider for AWS",
            "answers": ["terraform-provider-aws"],
        },
        {
            "id": "ops",
            "query": "secrets operator for kubernetes",
            "answers": ["vault-secrets-operator"],
        },
    ],
}
CATALOG = OrgCatalog(
    org="acme",
    host="github.com",
    built="2026-10-17T12:00:00+00:00",
    ms=1.0,
    repos=(
        CatalogRepo(name="acme/terraform-provider-aws", description="AWS provider for Terraform"),
        CatalogRepo(name="acme/docs", description="Docs"),
    ),
)


class FakeClient:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search_repos(self, query: str, *, per_page: int = 10) -> tuple[tuple[str, ...], float]:
        self.queries.append(query)
        hits = ("acme/vault-secrets-operator", "other/vault-secrets-operator")
        return (hits if "secrets" in query else ()), 300.0


def test_parse_query_keeps_the_first_query_line() -> None:
    assert parse_query('"kubernetes secrets operator"\n') == "kubernetes secrets operator"
    assert parse_query("Query:\n`terraform aws org:acme`") == "terraform aws"
    assert parse_query("") == ""


def test_masked_prompts_hide_the_org(tmp_path: Path) -> None:
    rset = RepoSet.model_validate(KEY)
    assert "acme" in query_prompt(rset, rset.queries[0], masked=False)
    assert "acme" not in query_prompt(rset, rset.queries[0], masked=True).lower()
    asked: list[str] = []

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return "veltrix secrets" if "veltrix" in prompt else "secrets"

    queries = write_queries(tmp_path, rset, ask, today="2026-10-17")
    assert len(asked) == 4 and queries["github-search-masked"]["ops"] == "veltrix secrets"
    assert load_queries(tmp_path) == queries
    assert "never edited by hand" in (tmp_path / QUERIES_FILE).read_text(encoding="utf-8")
    write_queries(tmp_path, rset, ask)
    assert len(asked) == 4


def test_evaluate_and_report() -> None:
    rset = RepoSet.model_validate(KEY)
    client = FakeClient()
    queries = {
        "github-search": {"aws": "", "ops": "secrets"},
        "github-search-masked": {"ops": "veltrix secrets"},
    }
    outcomes = {(o.locator, o.query): o for o in evaluate(rset, CATALOG, queries, client=client)}  # type: ignore[arg-type]
    assert outcomes["cairn", "aws"].rank == 1 and outcomes["cairn", "ops"].rank is None
    assert outcomes["github-search", "ops"].found == ("vault-secrets-operator",)  # org's only
    assert outcomes["github-search", "aws"].found == ()  # nothing typed, nothing searched
    assert client.queries == ["secrets org:acme", "acme secrets org:acme"]  # mask undone
    text = report(outcomes.values())
    assert "| dev | cairn | 2 | 0.50 | 0.50 | 0.50 |" in text
    assert "| dev | github-search-masked | 2 | 0.50 | 0.50 | 0.50 | " in text
    yaml.safe_dump(KEY)  # the key is plain YAML
