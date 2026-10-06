"""Benchmark suite definitions (bench/suites/<name>/suite.yaml)."""

import re
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import StringConstraints, ValidationError, model_validator

from cairn.errors import CairnInputError
from cairn.model.graph import Frozen


class Task(Frozen):
    id: str
    category: Literal["orientation", "localization", "impact", "control"]
    repo: str  # the agent's working directory inside the workspace
    prompt: str
    expect_files: tuple[str, ...] = ()  # workspace paths: repo/path
    expect_keywords: tuple[str, ...] = ()


class Source(Frozen):
    """A real repo pinned at one commit (an OSS suite's workspace is fetched, not vendored)."""

    name: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")]
    url: Annotated[str, StringConstraints(pattern=r"^(?:https://|file:///)[^\s]{1,500}$")]
    sha: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


class Suite(Frozen):
    name: str
    workspace: str
    related_repos_doc: str
    tasks: tuple[Task, ...]
    sources: tuple[Source, ...] = ()

    @model_validator(mode="after")
    def _portable_unique_sources(self) -> "Suite":
        names = [s.name.lower() for s in self.sources]
        if len(set(names)) != len(names):
            raise ValueError("source names must be unique (case-insensitively)")
        reserved = [n for n in names if _WINDOWS_RESERVED.fullmatch(n.split(".", 1)[0])]
        if reserved:
            raise ValueError(f"source names reserved on Windows: {', '.join(reserved)}")
        return self


_WINDOWS_RESERVED = re.compile(r"con|prn|aux|nul|com[0-9]|lpt[0-9]")


def load_suite(suite_dir: Path) -> Suite:
    path = suite_dir / "suite.yaml"
    try:
        return Suite.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise CairnInputError(str(path), f"invalid benchmark suite: {exc}") from exc
