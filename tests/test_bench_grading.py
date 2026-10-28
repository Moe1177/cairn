from pathlib import Path

from cairn.bench.grading import grade, mentioned_files
from cairn.bench.suite import Task

IDS = {"storefront", "orders-svc", "shared-types", "admin"}


def test_paths_normalise_from_cwd_absolute_and_repo_forms(tmp_path: Path) -> None:
    # Review Focus 4
    ws = tmp_path / "ws"
    text = (
        "Change `lib/cart.ts`, also orders-svc/app/main.py and "
        f"{(ws / 'shared-types' / 'src' / 'order.ts').as_posix()} plus {ws}\\admin\\lib\\db.ts."
    )
    found = mentioned_files(text, ws, "storefront", IDS)
    assert found == {
        "storefront/lib/cart.ts",
        "orders-svc/app/main.py",
        "shared-types/src/order.ts",
        "admin/lib/db.ts",
    }


def test_absolute_paths_outside_the_workspace_are_ignored(tmp_path: Path) -> None:
    text = r"See /usr/lib/node/index.js and C:\Windows\system32\x.dll"
    assert mentioned_files(text, tmp_path / "ws", "storefront", IDS) == set()


def test_grades_by_task_kind(tmp_path: Path) -> None:
    loc = Task(
        id="x",
        category="localization",
        repo="storefront",
        prompt="p",
        expect_files=("orders-svc/app/main.py", "shared-types/src/order.ts"),
    )
    good = grade(loc, "orders-svc/app/main.py and shared-types/src/order.ts", tmp_path, IDS)
    assert good.success and good.recall == 1.0
    assert not grade(loc, "orders-svc/app/main.py", tmp_path, IDS).success
    ori = Task(
        id="y",
        category="orientation",
        repo="admin",
        prompt="p",
        expect_keywords=("orders-svc", "admin"),
    )
    assert grade(ori, "Owned by ORDERS-SVC; admin reads it.", tmp_path, IDS).success


def test_paths_relative_to_the_workspace_parent(tmp_path: Path) -> None:
    # Benchmark finding: sonnet cited `ws/orders-svc/...` (relative to the temp run dir).
    ws = tmp_path / "run" / "ws"
    text = "Edit `ws/orders-svc/app/main.py` and run/ws/admin/lib/db.ts."
    assert mentioned_files(text, ws, "storefront", IDS) == {
        "orders-svc/app/main.py",
        "admin/lib/db.ts",
    }


def test_bare_paths_under_a_repo_heading_belong_to_that_repo(tmp_path: Path) -> None:
    # Benchmark finding: haiku grouped files under "**orders-svc:**" headings.
    text = (
        "Files that break:\n\n"
        "**orders-svc:**\n"
        "- `migrations/001_orders.sql` - schema\n"
        "- `app/main.py` - model\n\n"
        "### Database & Backend (admin)\n"
        "- lib/db.ts\n\n"
        "**Here, in this repo:**\n"
        "- lib/cart.ts\n"
    )
    assert mentioned_files(text, tmp_path, "storefront", IDS) == {
        "orders-svc/migrations/001_orders.sql",
        "orders-svc/app/main.py",
        "admin/lib/db.ts",
        "storefront/lib/cart.ts",
    }


def test_a_file_named_with_a_line_number_is_that_file(tmp_path: Path) -> None:
    """Codex answers with markdown links to file:line."""
    ws = tmp_path / "ws"
    cart = (ws / "storefront" / "lib" / "cart.ts").as_posix()
    text = (
        f"[lib/cart.ts]({cart}:7) computes it; see also orders-svc/app/main.py#L12-L20 and "
        f"{(ws / 'admin' / 'lib' / 'db.ts').as_posix()}:3:9."
    )
    found = mentioned_files(text, ws, "storefront", IDS)
    assert {"storefront/lib/cart.ts", "orders-svc/app/main.py", "admin/lib/db.ts"} <= found


def _ws(tmp_path: Path, files: tuple[str, ...]) -> Path:
    ws = tmp_path / "ws"
    for rel in files:
        (ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / rel).write_text("x", encoding="utf-8")
    for repo in {f.split("/", 1)[0] for f in files}:
        (ws / repo / ".git").mkdir(exist_ok=True)
    return ws


def test_a_table_row_that_names_a_repo_holds_its_paths(tmp_path: Path) -> None:
    # Benchmark finding: a correct answer put repo and path in separate columns.
    ws = _ws(tmp_path, ("orders-svc/infra/template.yaml", "admin/infra/template.yaml"))
    text = (
        "| Repo | Path |\n|---|---|\n"
        "| `orders-svc` | `infra/template.yaml` |\n| **admin** | infra/template.yaml |\n"
    )
    assert mentioned_files(text, ws, "storefront", IDS) == {
        "orders-svc/infra/template.yaml",
        "admin/infra/template.yaml",
    }


def test_a_path_written_under_a_stated_folder_names_the_one_file_it_ends(tmp_path: Path) -> None:
    # Benchmark finding: "all under `admin/stubs/queue/`" and then `handlers/enqueue.ts`.
    ws = _ws(
        tmp_path,
        (
            "admin/stubs/queue/handlers/enqueue.ts",
            "admin/stubs/a/config.ts",
            "orders-svc/b/config.ts",
            "storefront/src/app.ts",
        ),
    )
    text = (
        "All under `admin/stubs/queue/`:\n- `handlers/enqueue.ts`\n- `b/config.ts` and src/app.ts"
    )
    assert mentioned_files(text, ws, "storefront", IDS) == {
        "admin/stubs/queue/handlers/enqueue.ts",
        "admin/stubs/queue",  # the stated folder itself
        "orders-svc/b/config.ts",  # the only file ending b/config.ts
        "storefront/src/app.ts",  # in the working repo: no search needed
    }


def test_an_ending_two_files_share_stays_in_the_working_repo(tmp_path: Path) -> None:
    ws = _ws(tmp_path, ("admin/lib/config.ts", "orders-svc/lib/config.ts"))
    assert mentioned_files("see lib/config.ts", ws, "storefront", IDS) == {
        "storefront/lib/config.ts"
    }


def test_a_path_on_a_line_that_names_a_repo_is_that_repo_s_file(tmp_path: Path) -> None:
    # Benchmark finding (--scope repo): "`openfaas/faas`: `gateway/metrics/metrics.go`", and
    # "in the `openfaas/faas-middleware` repo, at `oauth/config.go:91`", vendored copies aside.
    ws = _ws(
        tmp_path,
        (
            "orders-svc/app/main.py",
            "admin/app/main.py",
            "admin/lib/db.ts",
            "storefront/lib/db.ts",
            "storefront/vendor/orders-svc/app/main.py",
        ),
    )
    text = (
        "- in `orders-svc`: `app/main.py:12` builds the query\n"
        "- `lib/db.ts` reads it (in this repo, not admin)\n"
        "- the admin repo has its own app/main.py too\n"
    )
    assert mentioned_files(text, ws, "storefront", IDS) == {
        "orders-svc/app/main.py",
        "storefront/lib/db.ts",  # the working repo's file comes first
        "admin/app/main.py",
    }


def test_a_path_goes_to_the_repo_named_nearest_it(tmp_path: Path) -> None:
    # Review finding: the first repo a line named won, even when the answer meant another.
    ws = _ws(
        tmp_path,
        (
            "orders-svc/.github/workflows/build.yml",
            "admin/.github/workflows/build.yml",
            "shared-types/builder/builder.go",
            "admin/builder/builder.go",
        ),
    )
    text = (
        "Unlike orders-svc, admin publishes it in `.github/workflows/build.yml`.\n"
        "It is signed in `builder/builder.go` in the shared-types repo, not admin.\n"
    )
    assert mentioned_files(text, ws, "storefront", IDS) == {
        "admin/.github/workflows/build.yml",
        "shared-types/builder/builder.go",  # named right after it; admin is further away
    }
