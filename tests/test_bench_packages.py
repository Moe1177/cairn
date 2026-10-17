"""The org-packages benchmark: keys, the agent's picks, and scoring (no model, no network)."""

from pathlib import Path

import pytest
import yaml

from cairn.bench.org_packages import (
    LIST_FILE,
    PICKS_FILE,
    PackageSet,
    load_package_set,
    load_picks,
    matches,
    parse_picks,
    prompt_for,
    report,
    score,
    write_picks,
)
from cairn.errors import CairnError

KEY = {
    "org": "acme",
    "split": "dev",
    "tasks": [
        {"id": "logs", "task": "Add leveled logging.", "answers": ["go:github.com/acme/go-hclog"]},
        {"id": "ui", "task": "Build a settings page.", "answers": ["npm:@acme/ui"]},
    ],
}
LISTING = (
    "The own packages of acme (github.com): ...\n"
    "- github.com/acme/go-hclog (Go) · 9 repos · in acme/go-hclog — Logging\n"
)


def suite(tmp_path: Path) -> Path:
    (tmp_path / "packages.yaml").write_text(yaml.safe_dump(KEY), encoding="utf-8")
    (tmp_path / LIST_FILE).write_text(LISTING, encoding="utf-8")
    return tmp_path


def test_keys_need_answers_named_with_their_ecosystem(tmp_path: Path) -> None:
    assert load_package_set(suite(tmp_path)).tasks[0].id == "logs"
    bad = {**KEY, "tasks": [{"id": "x", "task": "y", "answers": ["go-hclog"]}]}
    (tmp_path / "packages.yaml").write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(CairnError, match="ecosystem:name"):
        load_package_set(tmp_path)


@pytest.mark.parametrize(
    ("pick", "answer", "expected"),
    [
        ("github.com/acme/go-hclog", "go:github.com/acme/go-hclog", True),
        ("go-hclog", "go:github.com/acme/go-hclog", True),
        ("acme/go-hclog", "go:github.com/acme/go-hclog", True),
        ("`github.com/acme/hcl`", "go:github.com/acme/hcl/v2", True),
        ("hclog", "go:github.com/acme/go-hclog", False),  # a part of a name isn't the name
        ("github.com/acme/exec/tfexec", "go:github.com/acme/exec", True),  # a package in it
        ("@acme/ui", "npm:@acme/ui", True),
        ("@acme/ui-kit", "npm:@acme/ui", False),
        ("", "npm:@acme/ui", False),
    ],
)
def test_matches(pick: str, answer: str, expected: bool) -> None:
    assert matches(pick, answer) is expected


def test_parse_picks_drops_marks_prose_and_none() -> None:
    text = "1. `github.com/acme/a`\n- b\nHere are some options\nnone\n* c\n* d\n"
    assert parse_picks(text) == ("github.com/acme/a", "b", "c")
    assert parse_picks("none") == ()


def test_prompts_name_the_org_and_task_and_the_list_only_when_read() -> None:
    pset = PackageSet.model_validate(KEY)
    alone = prompt_for("alone", pset, pset.tasks[0], LISTING)
    listed = prompt_for("org-packages", pset, pset.tasks[0], LISTING)
    assert "acme" in alone and "Add leveled logging." in alone and "go-hclog" not in alone
    assert listed.startswith("acme's own packages") and "go-hclog" in listed
    masked = prompt_for("org-packages-masked", pset, pset.tasks[0], LISTING)
    assert "acme" not in masked.lower() and "github.com/veltrix/go-hclog" in masked


def test_write_picks_asks_only_for_what_is_missing_and_keeps_it(tmp_path: Path) -> None:
    folder = suite(tmp_path)
    pset = load_package_set(folder)
    asked: list[str] = []

    def ask(prompt: str) -> tuple[str, ...]:
        asked.append(prompt)
        return ("go-hclog",) if "logging" in prompt else ()

    picks = write_picks(folder, pset, ["alone", "org-packages"], ask, today="2026-10-17")
    assert len(asked) == 4 and picks["alone"]["logs"] == ("go-hclog",)
    assert load_picks(folder) == picks
    assert "never edited by hand" in (folder / PICKS_FILE).read_text(encoding="utf-8")
    write_picks(folder, pset, ["alone", "org-packages"], ask)
    assert len(asked) == 4  # nothing new to ask


def test_score_and_report() -> None:
    pset = PackageSet.model_validate(KEY)
    picks = {
        "alone": {"logs": ("zap", "go-hclog"), "ui": ()},
        "org-packages": {"logs": ("github.com/acme/go-hclog",), "ui": ("@acme/ui",)},
        "org-packages-masked": {"logs": ("github.com/veltrix/go-hclog",), "ui": ()},
    }
    outcomes = {(o.locator, o.task): o for o in score(pset, picks, LISTING)}
    assert outcomes["alone", "logs"].rank == 2 and outcomes["alone", "ui"].rank is None
    assert outcomes["org-packages", "ui"].rank == 1
    assert outcomes["org-packages-masked", "logs"].rank == 1  # renamed back before scoring
    assert outcomes["alone", "logs"].listed and not outcomes["alone", "ui"].listed
    text = report(outcomes.values(), {"dev": len(LISTING)})
    assert "| dev | alone | 2 | 0.00 | 0.50 | 0.25 | 0.50 |" in text
    assert "| dev | org-packages | 2 | 1.00 | 1.00 | 1.00 | 0.50 |" in text
    assert "dev 1" in text and "chars" in text
