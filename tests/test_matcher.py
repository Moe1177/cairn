from cairn.match.matcher import RepoFacts, match_edges, merge_edges
from cairn.match.scoring import db_confidence, noisy_or, specificity
from cairn.model.graph import Confidence, Contracts, Edge, EdgeType, Evidence, Fact, FactKind


def _ev(repo: str, line: int = 1) -> Evidence:
    return Evidence(repo=repo, file="f", line=line, snippet="s")


def _fact(kind: FactKind, value: str, repo: str) -> Fact:
    return Fact(kind=kind, value=value, evidence=(_ev(repo),))


def _repo(repo_id: str, exposes=(), consumes=(), path: str | None = None) -> RepoFacts:
    return RepoFacts(
        id=repo_id,
        path=path or repo_id,
        contracts=Contracts(
            exposes=tuple(_fact(k, v, repo_id) for k, v in exposes),
            consumes=tuple(_fact(k, v, repo_id) for k, v in consumes),
        ),
    )


T = FactKind.DB_TABLE


def test_scoring_functions() -> None:
    assert specificity(1) == 0.0 and specificity(2) == 1.0 and specificity(5) == 0.25
    assert noisy_or([1.0, 1.0]) == 0.84
    assert db_confidence(0.84) is Confidence.EXTRACTED
    assert db_confidence(0.6) is Confidence.INFERRED
    assert db_confidence(0.12) is Confidence.AMBIGUOUS
    assert db_confidence(0.0) is None


def test_package_edge() -> None:
    ui = _repo("shared-ui", exposes=[(FactKind.PACKAGE, "npm:@eats/ui")])
    app = _repo(
        "eats", consumes=[(FactKind.PACKAGE, "npm:@eats/ui"), (FactKind.PACKAGE, "npm:react")]
    )
    (edge,) = match_edges([app, ui])
    assert (edge.source, edge.target, edge.type) == (
        "eats",
        "shared-ui",
        EdgeType.DEPENDS_ON_PACKAGE,
    )
    assert edge.confidence is Confidence.EXTRACTED and edge.signals == ("package:npm:@eats/ui",)


def test_db_edge_points_from_consumer_to_creator() -> None:
    eats = _repo("eats", exposes=[(T, "cook_profiles"), (T, "listings"), (T, "users")])
    admin = _repo("admin", consumes=[(T, "cook_profiles"), (T, "listings"), (T, "users")])
    (edge,) = match_edges([eats, admin])
    assert (edge.source, edge.target) == ("admin", "eats")
    assert edge.type is EdgeType.SHARES_DB and edge.confidence is Confidence.EXTRACTED
    assert edge.signals == ("db_table:cook_profiles", "db_table:listings")


def test_stoplisted_tables_alone_make_no_edge() -> None:
    a = _repo("a", exposes=[(T, "users")])
    b = _repo("b", consumes=[(T, "users")])
    assert match_edges([a, b]) == ()


def test_widely_shared_table_is_ambiguous() -> None:
    repos = [_repo(n, consumes=[(T, "orders")]) for n in ("a", "b", "c", "d", "e", "f")]
    edges = match_edges(repos)
    assert edges and all(e.confidence is Confidence.AMBIGUOUS for e in edges)


def test_project_ref_path_and_mention_edges() -> None:
    a = _repo(
        "a",
        consumes=[
            (FactKind.DB_PROJECT_REF, "supabase:x"),
            (FactKind.PATH_REF, "b/src"),
            (FactKind.DOC_MENTION, "b"),
        ],
    )
    b = _repo("b", consumes=[(FactKind.DB_PROJECT_REF, "supabase:x")])
    types = {(e.source, e.target, e.type, e.confidence) for e in match_edges([a, b])}
    assert types == {
        ("a", "b", EdgeType.SHARES_DB, Confidence.EXTRACTED),
        ("a", "b", EdgeType.PATH_REF, Confidence.EXTRACTED),
        ("a", "b", EdgeType.MENTIONS, Confidence.INFERRED),
    }


def test_path_ref_matches_longest_repo_prefix() -> None:
    outer = _repo("group", path="group")
    inner = _repo("svc", path="group/svc")
    user = _repo("app", consumes=[(FactKind.PATH_REF, "group/svc/lib")])
    (edge,) = match_edges([outer, inner, user])
    assert edge.target == "svc"


def test_merge_symmetric_edges_across_directions() -> None:
    e1 = Edge(
        source="a",
        target="b",
        type=EdgeType.SHARES_DB,
        confidence=Confidence.INFERRED,
        score=0.6,
        signals=("db_table:x",),
        evidence=(_ev("a"),),
    )
    e2 = Edge(
        source="b",
        target="a",
        type=EdgeType.SHARES_DB,
        confidence=Confidence.EXTRACTED,
        score=1.0,
        signals=("db_project_ref:p",),
        evidence=(_ev("b"),),
    )
    (merged,) = merge_edges([e1, e2])
    assert merged.confidence is Confidence.EXTRACTED and merged.score == 1.0
    assert merged.signals == ("db_table:x", "db_project_ref:p")


def test_results_are_deterministic() -> None:
    repos = [
        _repo("b", exposes=[(T, "t1"), (T, "t2")]),
        _repo("a", consumes=[(T, "t1"), (T, "t2")]),
    ]
    assert match_edges(repos) == match_edges(list(reversed(repos)))


def test_tables_both_repos_create_are_never_extracted() -> None:
    # Final review I4: two unrelated apps that each create common tables.
    a = _repo("resume-app", exposes=[(T, "profiles"), (T, "products")])
    b = _repo("shop-app", exposes=[(T, "profiles"), (T, "products")])
    (edge,) = match_edges([a, b])
    assert edge.confidence is Confidence.AMBIGUOUS


def test_single_owned_table_caps_at_inferred() -> None:
    owner = _repo("orders-svc", exposes=[(T, "orders"), (T, "order_items")])
    user = _repo("payments", consumes=[(T, "orders")], exposes=[(T, "order_items")])
    (edge,) = match_edges([owner, user])
    assert edge.confidence is Confidence.INFERRED


def test_query_only_overlap_is_ambiguous() -> None:
    a = _repo("a", consumes=[(T, "invoices"), (T, "ledgers")])
    b = _repo("b", consumes=[(T, "invoices"), (T, "ledgers")])
    (edge,) = match_edges([a, b])
    assert edge.confidence is Confidence.AMBIGUOUS


def _e(
    src: str, tgt: str, type_: EdgeType, conf: Confidence, signals: tuple[str, ...] = ()
) -> Edge:
    return Edge(source=src, target=tgt, type=type_, confidence=conf, score=0.5, signals=signals)


def test_corroboration_upgrades_one_tier() -> None:
    from cairn.match.matcher import corroborate

    edges = corroborate(
        [
            _e("a", "b", EdgeType.SHARES_DB, Confidence.AMBIGUOUS, ("db_table:x",)),
            _e("b", "a", EdgeType.MENTIONS, Confidence.INFERRED),
            _e("c", "d", EdgeType.SHARES_DB, Confidence.INFERRED, ("db_table:y",)),
            _e("c", "d", EdgeType.DEPENDS_ON_PACKAGE, Confidence.EXTRACTED),
            _e("e", "f", EdgeType.SHARES_DB, Confidence.INFERRED, ("db_table:z",)),
            _e("e", "f", EdgeType.MENTIONS, Confidence.INFERRED),
        ]
    )
    db = {(e.source, e.target): e for e in edges if e.type is EdgeType.SHARES_DB}
    assert db[("a", "b")].confidence is Confidence.INFERRED
    assert "corroborated:mentions" in db[("a", "b")].signals
    assert db[("c", "d")].confidence is Confidence.EXTRACTED
    assert db[("e", "f")].confidence is Confidence.INFERRED


def test_db_edges_never_corroborate_themselves() -> None:
    # Review Focus 1
    from cairn.match.matcher import corroborate

    (edge,) = corroborate(
        [
            _e(
                "a",
                "b",
                EdgeType.SHARES_DB,
                Confidence.AMBIGUOUS,
                ("db_table:x", "db_project_ref:supabase-local:app"),
            )
        ]
    )
    assert edge.confidence is Confidence.AMBIGUOUS


def test_local_supabase_ids_only_make_ambiguous_edges() -> None:
    a = _repo("a", consumes=[(FactKind.DB_PROJECT_REF, "supabase-local:app")])
    b = _repo("b", consumes=[(FactKind.DB_PROJECT_REF, "supabase-local:app")])
    (edge,) = match_edges([a, b])
    assert edge.confidence is Confidence.AMBIGUOUS and edge.score == 0.3


def test_duplicate_package_owners_are_ambiguous() -> None:
    kit = _repo("ui-kit", exposes=[(FactKind.PACKAGE, "npm:@acme/ui-kit")])
    fork = _repo("ui-kit-fork", exposes=[(FactKind.PACKAGE, "npm:@acme/ui-kit")])
    site = _repo("site", consumes=[(FactKind.PACKAGE, "npm:@acme/ui-kit")])
    edges = {(e.target, e.confidence) for e in match_edges([kit, fork, site])}
    assert edges == {("ui-kit", Confidence.AMBIGUOUS), ("ui-kit-fork", Confidence.AMBIGUOUS)}


def test_disjoint_db_providers_cannot_share_tables() -> None:
    p = FactKind.DB_PROVIDER
    neon = _repo(
        "shopapp", exposes=[(T, "stripe_webhook_events"), (T, "orders")], consumes=[(p, "neon")]
    )
    supa = _repo(
        "resumeapp",
        exposes=[(T, "stripe_webhook_events"), (T, "orders")],
        consumes=[(p, "supabase")],
    )
    both = _repo(
        "hybrid",
        exposes=[(T, "stripe_webhook_events"), (T, "orders")],
        consumes=[(p, "neon"), (p, "supabase")],
    )
    pairs = {frozenset((e.source, e.target)) for e in match_edges([neon, supa, both])}
    assert frozenset(("shopapp", "resumeapp")) not in pairs
    assert frozenset(("shopapp", "hybrid")) in pairs
    assert frozenset(("resumeapp", "hybrid")) in pairs


def test_unknown_provider_keeps_table_edges() -> None:
    a = _repo(
        "a", exposes=[(T, "invoices"), (T, "ledgers")], consumes=[(FactKind.DB_PROVIDER, "neon")]
    )
    b = _repo("b", consumes=[(T, "invoices"), (T, "ledgers")])
    assert len(match_edges([a, b])) == 1


def test_different_linked_supabase_projects_are_never_linked() -> None:
    # Phase 2a review I1
    r = FactKind.DB_PROJECT_REF
    api = _repo(
        "api",
        exposes=[(T, "orders"), (T, "order_items")],
        consumes=[(r, "supabase:aaaaaaaaaaaaaaaaaaaa"), (r, "supabase-local:app")],
    )
    web = _repo(
        "web",
        consumes=[
            (T, "orders"),
            (T, "order_items"),
            (r, "supabase:bbbbbbbbbbbbbbbbbbbb"),
            (r, "supabase-local:app"),
        ],
    )
    assert match_edges([api, web]) == ()


def test_provider_veto_spares_consumer_to_owner_evidence() -> None:
    # Phase 2a review I5: a supabase-auth-only worker still queries the owner's tables.
    p = FactKind.DB_PROVIDER
    app = _repo("app", exposes=[(T, "orders"), (T, "refunds")], consumes=[(p, "neon")])
    worker = _repo("worker", consumes=[(T, "orders"), (T, "refunds"), (p, "supabase")])
    (edge,) = match_edges([app, worker])
    assert edge.confidence is Confidence.EXTRACTED


def test_unique_owner_links_show_even_when_the_table_is_widely_queried() -> None:
    # Benchmark finding: three repos touch `orders`; only orders-svc creates it. The
    # owner->consumer links must reach cards (inferred), not hide as ambiguous.
    owner = _repo("orders-svc", exposes=[(T, "orders"), (T, "refunds")])
    admin = _repo("admin", consumes=[(T, "orders")])
    payments = _repo("payments-svc", consumes=[(T, "orders")], exposes=[(T, "ledger")])
    tiers = {(e.source, e.target): e.confidence for e in match_edges([owner, admin, payments])}
    assert tiers[("admin", "orders-svc")] is Confidence.INFERRED
    assert tiers[("payments-svc", "orders-svc")] is Confidence.INFERRED
    # Two consumers of the same table are still only a guess.
    consumers = {("admin", "payments-svc"), ("payments-svc", "admin")}
    assert all(tiers[k] is Confidence.AMBIGUOUS for k in consumers if k in tiers)


def test_owner_floor_needs_a_single_creator_in_the_workspace() -> None:
    a = _repo("shop-a", exposes=[(T, "orders")])
    b = _repo("shop-b", exposes=[(T, "orders")])
    c = _repo("report", consumes=[(T, "orders")])
    assert all(e.confidence is Confidence.AMBIGUOUS for e in match_edges([a, b, c]))
