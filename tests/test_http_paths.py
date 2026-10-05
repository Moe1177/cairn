"""Phase 2d Task 1: route templates and env-var names."""

import time

import pytest

from cairn.detectors.http_paths import (
    env_names,
    is_generic,
    normalize_route,
    template_env_names,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/trips/:id", "/trips/{}"),
        ("/trips/{trip_id}", "/trips/{}"),
        ("/trips/[id]", "/trips/{}"),
        ("/docs/[...slug]", "/docs/{}"),
        ("/trips/<int:trip_id>/", "/trips/{}"),
        ("/trips/${id}/fare", "/trips/{}/fare"),
        ("/Trips//Fare/", "/trips/fare"),
        ("/trips?status=open#top", "/trips"),
        ("/(marketing)/pricing", "/pricing"),
        ("/api/v1/orders/{orderId}/items/{itemId}", "/api/v1/orders/{}/items/{}"),
        ("/", "/"),
        ("trips/1", None),
        ("", None),
        ("/" + "a" * 400, None),
        ("/trips/ ", "/trips"),
    ],
)
def test_normalize_route(raw: str, expected: str | None) -> None:
    assert normalize_route(raw) == expected


@pytest.mark.parametrize(
    ("template", "generic"),
    [
        ("/health", True),
        ("/healthz", True),
        ("/readyz", True),
        ("/metrics", True),
        ("/api", True),
        ("/", True),
        ("/{}", True),
        ("/{}/{}", True),
        ("/trips/{}", False),
        ("/api/orders", False),
    ],
)
def test_generic_routes(template: str, generic: bool) -> None:
    assert is_generic(template) is generic


def test_env_names_from_code() -> None:
    text = "\n".join(
        [
            "const a = process.env.TRIPS_SVC_URL;",
            "const b = import.meta.env.VITE_MAPS_KEY",
            "x = os.environ['BILLING_URL'] + os.environ.get(\"RIDES_TOPIC\")",
            "y = os.getenv('PAYMENTS_HOST')",
            'u := os.Getenv("GEO_SVC_ADDR")',
            'let k = env::var("DISPATCH_QUEUE").unwrap();',
            "not_env = SOMETHING_ELSE",
        ]
    )
    assert [name for _, name in env_names(text)] == [
        "TRIPS_SVC_URL",
        "VITE_MAPS_KEY",
        "BILLING_URL",
        "RIDES_TOPIC",
        "PAYMENTS_HOST",
        "GEO_SVC_ADDR",
        "DISPATCH_QUEUE",
    ]


def test_template_names_never_include_values() -> None:
    text = "# comment\nTRIPS_SVC_URL=http://trips:8000\nSTRIPE_KEY=sk_live_x\nexport FOO_BAR = 1\nbad line\n"
    names = [name for _, name in template_env_names(text)]
    assert names == ["TRIPS_SVC_URL", "STRIPE_KEY", "FOO_BAR"]
    assert not any("http" in n or "sk_" in n for n in names)


def test_primitives_are_linear() -> None:
    text = ("process.env." + "A" * 50 + " ") * 20_000
    start = time.perf_counter()
    env_names(text)
    template_env_names("A=" * 500_000)
    normalize_route("/" + "{" * 1_000_000)
    assert time.perf_counter() - start < 1
