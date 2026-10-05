"""Benchmark suite definitions (bench/suites/<name>/suite.yaml)."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import ValidationError

from cairn.errors import CairnInputError
from cairn.model.graph import Frozen


class Task(Frozen):
    id: str
    category: Literal["orientation", "localization", "impact", "control"]
    repo: str  # the agent's working directory inside the workspace
    prompt: str
    expect_files: tuple[str, ...] = ()  # workspace paths: repo/path
    expect_keywords: tuple[str, ...] = ()


class Suite(Frozen):
    name: str
    workspace: str
    related_repos_doc: str
    tasks: tuple[Task, ...]


def load_suite(suite_dir: Path) -> Suite:
    path = suite_dir / "suite.yaml"
    try:
        return Suite.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise CairnInputError(str(path), f"invalid benchmark suite: {exc}") from exc
