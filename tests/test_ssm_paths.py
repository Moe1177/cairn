"""Spec §25.1: an SSM parameter nothing creates links to the repo its path names."""

from cairn.match.matcher import RepoFacts
from cairn.match.services import resource_edges
from cairn.match.ssm_paths import path_owner, repo_names
from cairn.model.graph import Confidence, Contracts, Fact, FactKind


def _repo(
    repo_id: str,
    exposes: tuple[str, ...] = (),
    consumes: tuple[str, ...] = (),
    aliases: tuple[str, ...] = (),
) -> RepoFacts:
    def facts(values: tuple[str, ...]) -> tuple[Fact, ...]:
        return tuple(Fact(kind=FactKind.CLOUD_RESOURCE, value=v) for v in values)

    return RepoFacts(
        id=repo_id,
        path=repo_id,
        aliases=aliases,
        contracts=Contracts(exposes=facts(exposes), consumes=facts(consumes)),
    )


def _links(repos: list[RepoFacts]) -> set[tuple[str, str, Confidence]]:
    return {(e.source, e.target, e.confidence) for e in resource_edges(repos)}


def test_a_path_segment_naming_a_repos_stack_links_to_that_repo() -> None:
    repos = [
        _repo("lambda-admin", exposes=("stack:amplify-admin",)),
        _repo("assistants", consumes=("ssm:/amplify/amplify-admin/critical_errors_queue",)),
    ]
    assert _links(repos) == {("assistants", "lambda-admin", Confidence.INFERRED)}


def test_repo_ids_and_aliases_name_owners_too() -> None:
    names = repo_names([_repo("orders-service"), _repo("pay", aliases=("payments",))])
    assert path_owner("ssm:/shop/orders-service/table", "web", names) == "orders-service"
    assert path_owner("ssm:/shop/payments/api-url", "web", names) == "pay"


def test_the_app_prefix_the_parameter_name_and_short_paths_name_nothing() -> None:
    names = repo_names([_repo("shop"), _repo("orders")])
    assert path_owner("ssm:/shop/config/timeout", "web", names) is None  # app prefix
    assert path_owner("ssm:/shop/config/orders", "web", names) is None  # the name itself
    assert path_owner("ssm:/orders/url", "web", names) is None  # too short to have an owner


def test_shared_words_ambiguous_names_and_self_never_link() -> None:
    repos = [
        _repo("orders-api", aliases=("orders",)),
        _repo("orders-worker", aliases=("orders",)),
        _repo("billing"),
    ]
    names = repo_names(repos)
    assert path_owner("ssm:/shop/orders/table", "web", names) is None  # two repos are "orders"
    assert path_owner("ssm:/shop/orders-db/table", "web", names) is None  # a word, not a name
    assert path_owner("ssm:/shop/billing/rate", "billing", names) is None  # its own


def test_a_created_parameter_links_to_its_creator_not_the_named_repo() -> None:
    repos = [
        _repo("platform", exposes=("ssm:/shop/orders/table",)),
        _repo("orders"),
        _repo("web", consumes=("ssm:/shop/orders/table",)),
    ]
    assert _links(repos) == {("web", "platform", Confidence.INFERRED)}


def test_two_names_for_different_repos_in_one_path_name_nothing() -> None:
    names = repo_names([_repo("orders"), _repo("billing")])
    assert path_owner("ssm:/shop/orders/billing/url", "web", names) is None
