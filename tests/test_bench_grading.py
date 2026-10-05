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
