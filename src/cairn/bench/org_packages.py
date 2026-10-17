"""The org-packages benchmark: told what to build, does an agent reach for the org's own library?

Each suite's `packages.yaml` names a GitHub org and lists tasks a developer there might start,
each with the org's own packages that serve it (checked by reading each package's repo). An
agent (a headless `claude -p`, the cheapest model) names the org libraries it would use, best
first, twice: from the task alone (what it remembers of the org) and after reading the list
`org_packages` returns (kept beside the key as `org_packages.md`, so a run can be repeated and
checked). Its answers are kept too (`agent_picks.yaml`), never edited by hand.

A public org's libraries are in the model's training data, so "alone" is a ceiling no private
org gets: there, an agent alone knows none of them.
"""

import json
import re
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import ValidationError, field_validator

from cairn.bench.prior_art import TERMS_MODEL
from cairn.errors import CairnError
from cairn.model.graph import Frozen
from cairn.org.packages import build_index, org_packages, plain_name, render_packages
from cairn.remote.github import GitHub

PACKAGES_FILE = "packages.yaml"
LIST_FILE = "org_packages.md"
PICKS_FILE = "agent_picks.yaml"
PICKS = 3
PROMPT_ALONE = (
    "You're writing code in a repo of the {org} GitHub org. Task: {task}\n"
    "Which of {org}'s own libraries (packages that {org}'s repos publish and share) would you "
    "use for it? Name up to 3, best first, as import paths or package names, one per line, "
    "nothing else. If you know none, write: none"
)
PROMPT_LIST = "{org}'s own packages, as cairn's org_packages tool lists them:\n\n{list}\n\n" + (
    PROMPT_ALONE
)
LOCATORS: dict[str, str] = {
    "alone": PROMPT_ALONE,
    "org-packages": PROMPT_LIST,
    # The same, with the org renamed in the task and the list: a private org's packages, which
    # no model has read about. Its picks are renamed back before scoring.
    "alone-masked": PROMPT_ALONE,
    "org-packages-masked": PROMPT_LIST,
}
MASK = "veltrix"  # an org name no model knows packages of


class PackageTask(Frozen):
    id: str
    task: str  # what a developer at the org wants to build
    answers: tuple[str, ...]  # ecosystem:name of org packages that serve it: any one counts
    note: str = ""

    @field_validator("answers")
    @classmethod
    def _named(cls, answers: tuple[str, ...]) -> tuple[str, ...]:
        if not answers or any(":" not in a for a in answers):
            raise ValueError("every task needs answers written ecosystem:name")
        return answers


class PackageSet(Frozen):
    host: str = "github.com"
    org: str
    split: Literal["dev", "held"]
    tasks: tuple[PackageTask, ...]


class AgentPicks(Frozen):
    model: str
    generated: str = ""
    picks: dict[str, dict[str, tuple[str, ...]]]  # locator -> task id -> names, best first


@dataclass(frozen=True)
class PickOutcome:
    task: str
    split: str
    locator: str
    picks: tuple[str, ...]
    rank: int | None  # 1-based place of the first right pick
    listed: bool  # an answer is in the list the agent read


def load_package_set(suite_dir: Path) -> PackageSet:
    path = suite_dir / PACKAGES_FILE
    try:
        return PackageSet.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise CairnError(f"invalid packages key {path}: {exc}") from exc


def write_list(suite_dir: Path, client: GitHub, pset: PackageSet) -> str:
    """Read the org's packages over the API and keep the list an agent saw beside the key."""
    index = build_index(client, pset.org, pset.host)
    text = render_packages(index, org_packages(index))
    (suite_dir / LIST_FILE).write_text(text + "\n", encoding="utf-8", newline="\n")
    return text


def read_list(suite_dir: Path) -> str:
    try:
        return (suite_dir / LIST_FILE).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise CairnError(f"no {suite_dir / LIST_FILE}: make it first with --make-list") from exc


def load_picks(suite_dir: Path) -> dict[str, dict[str, tuple[str, ...]]]:
    path = suite_dir / PICKS_FILE
    if not path.is_file():
        return {}
    try:
        return AgentPicks.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))).picks
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise CairnError(f"invalid agent picks {path}: {exc}") from exc


def prompt_for(locator: str, pset: PackageSet, task: PackageTask, listing: str) -> str:
    text = (
        LOCATORS[locator]
        .replace("{list}", listing)
        .replace("{org}", pset.org)
        .replace("{task}", task.task)
    )
    return _masked(text, pset.org, MASK) if locator.endswith("-masked") else text


def _masked(text: str, name: str, mask: str) -> str:
    return re.sub(re.escape(name), mask, text, flags=re.IGNORECASE)


def parse_picks(text: str) -> tuple[str, ...]:
    """A model's answer, one name per line, list marks and quotes dropped; "none" is none."""
    found = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("-*•0123456789.) ").strip().strip("`'\"").strip()
        if line and line.lower() != "none" and len(line) <= 200 and " " not in line:
            found.append(line)
    return tuple(dict.fromkeys(found))[:PICKS]


def ask_model(prompt: str, model: str = TERMS_MODEL) -> tuple[str, ...]:
    from cairn.bench.runner import ClaudeRunner  # the benchmark's isolated runner

    with tempfile.TemporaryDirectory(prefix="cairn-picks-") as tmp:
        result = ClaudeRunner(model=model, timeout=180).run(prompt, Path(tmp), Path(tmp), None)
    if result.is_error:
        raise CairnError(f"claude couldn't answer: {result.result_text.strip()[:200]}")
    return parse_picks(result.result_text)


def write_picks(
    suite_dir: Path,
    pset: PackageSet,
    locators: Sequence[str],
    ask: Callable[[str], tuple[str, ...]] | None = None,
    *,
    model: str = TERMS_MODEL,
    today: str = "",
) -> dict[str, dict[str, tuple[str, ...]]]:
    """Ask for the picks of every task and locator that has none yet, and keep them."""
    asker = ask or (lambda prompt: ask_model(prompt, model))
    picks = load_picks(suite_dir)
    listing = read_list(suite_dir) if "org-packages" in locators else ""
    for locator in locators:
        mine = picks.setdefault(locator, {})
        for task in pset.tasks:
            if task.id not in mine:
                mine[task.id] = asker(prompt_for(locator, pset, task, listing))
    doc = AgentPicks(model=model, generated=today, picks=picks)
    header = (
        "# The org libraries an agent named for each task in packages.yaml, best first: written\n"
        "# by a model (cairn bench-packages --make-picks), never edited by hand.\n"
    )
    body = yaml.safe_dump(doc.model_dump(), sort_keys=False, width=100, allow_unicode=True)
    (suite_dir / PICKS_FILE).write_text(header + body, encoding="utf-8", newline="\n")
    return picks


def matches(pick: str, answer: str) -> bool:
    """Whether a name the agent wrote means the package: in full, without its ecosystem or Go
    major version, as its last path parts (`go-hclog`, `hashicorp/go-hclog`), or as a package
    inside it (`terraform-exec/tfexec`)."""
    wanted, said = _plain(answer), _plain(pick)
    return bool(said) and (
        said == wanted or wanted.endswith("/" + said) or said.startswith(wanted + "/")
    )


def _plain(name: str) -> str:
    return plain_name(name.strip().strip("`'\""))  # one notion of a name, shared with the tool


def score(
    pset: PackageSet,
    picks: Mapping[str, Mapping[str, tuple[str, ...]]],
    listing: str,
) -> list[PickOutcome]:
    outcomes = []
    shown = {
        _plain(line[2:].split(" (", 1)[0]) for line in listing.splitlines() if line[:2] == "- "
    }
    for locator, by_task in picks.items():
        for task in pset.tasks:
            said = tuple(by_task.get(task.id, ()))
            if locator.endswith("-masked"):
                said = tuple(_masked(p, MASK, pset.org) for p in said)
            rank = next(
                (i + 1 for i, p in enumerate(said) if any(matches(p, a) for a in task.answers)),
                None,
            )
            outcomes.append(
                PickOutcome(
                    task=task.id,
                    split=pset.split,
                    locator=locator,
                    picks=said,
                    rank=rank,
                    listed=any(_plain(a) in shown for a in task.answers),
                )
            )
    return outcomes


def report(outcomes: Iterable[PickOutcome], list_chars: Mapping[str, int]) -> str:
    rows = list(outcomes)
    lines = [
        "| split | agent | n | hit@1 | hit@3 | MRR | answer in the list |",
        "|---|---|---|---|---|---|---|",
    ]
    for split in sorted({o.split for o in rows}, key=["dev", "held"].index):
        for locator in dict.fromkeys(o.locator for o in rows):
            group = [o for o in rows if o.split == split and o.locator == locator]
            if not group:
                continue
            n = len(group)
            hit1 = sum(o.rank == 1 for o in group) / n
            hit3 = sum(o.rank is not None for o in group) / n
            mrr = sum(1 / o.rank for o in group if o.rank) / n
            listed = sum(o.listed for o in group) / n
            lines.append(
                f"| {split} | {locator} | {n} | {hit1:.2f} | {hit3:.2f} | {mrr:.2f} | {listed:.2f} |"
            )
    if list_chars:
        sizes = ", ".join(f"{split} {chars:,} chars" for split, chars in list_chars.items())
        lines += ["", f"The list the agent read: {sizes} (about 4 characters a token)."]
    return "\n".join(lines) + "\n"


def outcomes_json(outcomes: Iterable[PickOutcome]) -> str:
    return json.dumps([o.__dict__ for o in outcomes], indent=1)
