"""Run a benchmark suite across conditions and write a report (spec §11 E2)."""

import json
import re
import tempfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import cairn
from cairn.bench.conditions import Prepared, make_workspace, set_up
from cairn.bench.grading import Grade, grade
from cairn.bench.report import load_records, render_markdown
from cairn.bench.runner import Runner, RunResult
from cairn.bench.solo import drift_note, prepare_org, solo_workspace
from cairn.bench.sources import fetch_sources
from cairn.bench.suite import Suite, Task, load_suite
from cairn.config import OrgSource
from cairn.errors import CairnError
from cairn.store.atomic import atomic_write_text

__all__ = ["BenchStopped", "RunRecord", "regrade_log", "render_markdown", "run_bench"]

# The run's own workspace (a temp dir, gone once the run ends) as an answer spells it: the
# shared one, or (--scope repo) the one a task's repo had to itself. It starts a word, so a
# path written just before it (`a/x.go,C:\...`) isn't swallowed with it.
_RUN_WS = re.compile(
    r"(?<![\w.:\\/-])(?:[A-Za-z]:)?[\\/][^\s`'\"()|,]*?cairn-bench-[^\\/\s]+[\\/]ws(?=[\\/])"
)
_SOLO_PREFIX = "cairn-bench-solo-"
# Warms an org's caches in a folder and returns what each task's answer (pinned in the
# workspace) lost on the org.
OrgSetup = Callable[[Path, OrgSource, Sequence[Task], Path], Mapping[str, Sequence[str]]]


@dataclass(frozen=True)
class RunRecord:
    condition: str
    task_id: str
    run: int
    grade: Grade
    result: RunResult


def run_bench(
    suite_dir: Path,
    *,
    conditions: Sequence[str],
    runs: int,
    task_ids: Sequence[str] | None,
    runner: Runner,
    out_dir: Path,
    now: str,
    meta: Mapping[str, object] | None = None,
    resume: Path | None = None,
    scope: str = "workspace",
    org_setup: OrgSetup = prepare_org,
) -> tuple[RunRecord, ...]:
    """Each finished run is appended to `<now>.jsonl` at once, so an interrupted (paid)
    benchmark keeps what it already measured; `<now>.json` and `.md` are written at the end.

    A usage limit stops the run (BenchStopped) without recording the failed attempt. `resume`
    continues an earlier log: cells with a good run are kept, missing or failed ones run again.

    `scope` "repo": each session starts with only its task's repo on disk, and reaches the
    others through the suite's org, as a session opened in one repo does (bench/solo.py).
    """
    suite = load_suite(suite_dir)
    if scope == "repo" and suite.org is None:
        raise CairnError(
            f"suite {suite.name} names no org (org: in suite.yaml), and --scope repo reaches "
            "the other repos through it"
        )
    org = suite.org if scope == "repo" else None
    tasks = [t for t in suite.tasks if not task_ids or t.id in task_ids]
    header: dict[str, object] = {
        "cairn_version": cairn.__version__,
        "suite": suite.name,
        "scope": scope,
        **({"org": org.model_dump(mode="json")} if org is not None else {}),
        "conditions": list(conditions),
        "runs": runs,
        "tasks": [t.id for t in tasks],
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **(meta or {}),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    source = fetch_sources(suite_dir, suite)  # an OSS suite's repos, fetched once
    log = resume or out_dir / f"{now}.jsonl"
    stem = log.with_suffix("")
    settings = {
        "suite": suite.name,
        "scope": scope,
        "model": header.get("model"),
        "harness": header.get("harness", "claude"),
        "runs": runs,
        "conditions": list(conditions),
    }
    if resume is not None:
        _check_same_settings(resume, settings)
    done = {
        (r.condition, r.task_id, r.run): r
        for r in (load_records(resume) if resume else [])
        if not usage_limit(r.result)  # a genuine agent error is a result: it stands
    }
    records: list[RunRecord] = []
    cells = [(task, index) for task in tasks for index in range(runs)]
    todo = [c for c in conditions if any((c, t.id, i) not in done for t, i in cells)]
    # One workspace for the whole benchmark, set up for each condition in turn: the agent only
    # has read tools, so no run changes what the next one sees, and a large suite (minutes to
    # copy into git repos) is copied once. The MCP server of condition E may still hold files
    # for a moment on Windows.
    with (
        tempfile.TemporaryDirectory(prefix="cairn-bench-", ignore_cleanup_errors=True) as tmp,
        ExitStack() as solo_dirs,
    ):
        ws = make_workspace(suite, suite_dir, Path(tmp), source) if todo else Path(tmp)
        repo_ids = {p.name for p in ws.iterdir() if (p / ".git").exists()}
        if org is not None and todo:
            note = drift_note(org_setup(Path(tmp) / _ORG_CACHE, org, tasks, ws))
            if note:
                header["org_drift"] = note
        # Every invocation leaves a header line, so a log says which settings and tools made it.
        with log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"_header": header}) + "\n")
        sessions = _Sessions(suite, suite_dir, ws, Path(tmp), org, solo_dirs)
        for condition in conditions:
            if condition not in todo:
                records += [done[(condition, task.id, index)] for task, index in cells]
                continue
            sessions.start(condition)
            for task, index in cells:
                if (condition, task.id, index) in done:
                    records.append(done[(condition, task.id, index)])
                    continue
                cwd, prepared, hidden = sessions.session(task)
                result = runner.run(task.prompt, cwd, prepared.ws, prepared.mcp_config, hidden)
                if usage_limit(result):
                    raise BenchStopped(
                        f"stopped: {result.result_text.strip()[:200]}. Measured runs are in "
                        f"{log}; continue later with `--resume {log}`."
                    )
                text = _RUN_WS.sub(lambda _: ws.as_posix(), result.result_text)
                graded = grade(task, text, ws, repo_ids, org)
                record = RunRecord(condition, task.id, index, graded, result)
                records.append(record)
                with log.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(asdict(record)) + "\n")
    out = tuple(records)
    report = {"meta": header, "records": [asdict(r) for r in out]}
    atomic_write_text(stem.with_suffix(".json"), json.dumps(report, indent=2))
    atomic_write_text(stem.with_suffix(".md"), render_markdown(out, meta=header))
    return out


_ORG_CACHE = "org"  # where the org's caches are read once, before any session


@dataclass
class _Sessions:
    """Where each task's session runs under one condition: the shared workspace, or (with an
    org) a workspace of the task's repo alone, each set up for the condition when first used.

    A repo's own workspace sits in a temp folder of its own, so the session can be denied the
    run's folder (every repo, and the org's caches) and the other repos' folders whole; every
    session is denied the suite, which holds its answers (and a fetched suite's repos)."""

    suite: Suite
    suite_dir: Path
    ws: Path
    tmp: Path
    org: OrgSource | None
    solo_dirs: ExitStack
    condition: str = ""
    _solo: dict[str, tuple[Path, Path]] = field(default_factory=dict)
    _ready: dict[str, Prepared] = field(default_factory=dict)

    def start(self, condition: str) -> None:
        self.condition = condition
        self._ready = {}

    def session(self, task: Task) -> tuple[Path, Prepared, tuple[Path, ...]]:
        """The session's working directory, the workspace prepared around it, and the folders
        it must not read."""
        key = task.repo if self.org is not None else ""
        if key not in self._ready:
            ws, run_dir = self._workspace(task.repo)
            self._ready[key] = set_up(self.condition, self.suite, self.suite_dir, ws, run_dir)
        prepared = self._ready[key]
        if self.org is None:
            return prepared.ws / task.repo, prepared, (self.suite_dir,)
        others = tuple(root for repo, (_, root) in self._solo.items() if repo != task.repo)
        return prepared.ws / task.repo, prepared, (self.suite_dir, self.tmp, *others)

    def _workspace(self, repo: str) -> tuple[Path, Path]:
        if self.org is None:
            return self.ws, self.tmp
        if repo not in self._solo:
            root = Path(
                self.solo_dirs.enter_context(
                    tempfile.TemporaryDirectory(prefix=_SOLO_PREFIX, ignore_cleanup_errors=True)
                )
            )
            cache = self.tmp / _ORG_CACHE
            self._solo[repo] = solo_workspace(self.ws, repo, root, self.org, cache)
        return self._solo[repo]


def regrade_log(log: Path, suite_dir: Path, ws: Path) -> tuple[RunRecord, ...]:
    """Grade a run's log again with today's grading, against `ws` (the suite's repos, made
    again: the run's own copy is gone). Writes `<stem>.json` and `.md`; the log is untouched."""
    suite = load_suite(suite_dir)
    tasks = {t.id: t for t in suite.tasks}
    repo_ids = {p.name for p in ws.iterdir() if (p / ".git").exists()}
    headers = [
        json.loads(line)["_header"]
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.startswith('{"_header"')
    ]
    first = headers[0] if headers else {}
    org = None
    if first.get("scope") == "repo":  # read through the org the run used, not today's suite's
        org = OrgSource.model_validate(first["org"]) if "org" in first else suite.org
    records = []
    for record in load_records(log):
        task = tasks.get(record.task_id)
        if task is None:
            raise CairnError(f"{log} has task {record.task_id}, which {suite.name} doesn't")
        text = _RUN_WS.sub(lambda _: ws.as_posix(), record.result.result_text)
        records.append(
            RunRecord(
                record.condition,
                record.task_id,
                record.run,
                grade(task, text, ws, repo_ids, org),
                record.result,
            )
        )
    meta = {**(headers[0] if headers else {}), "regraded_with": cairn.__version__}
    out = tuple(records)
    stem = log.with_suffix("")
    report = {"meta": meta, "records": [asdict(r) for r in out]}
    atomic_write_text(stem.with_suffix(".json"), json.dumps(report, indent=2))
    atomic_write_text(stem.with_suffix(".md"), render_markdown(out, meta=meta))
    return out


def _check_same_settings(log: Path, settings: Mapping[str, object]) -> None:
    """Refuse to resume a log made with another model, suite, scope, run count or conditions."""
    for line in log.read_text(encoding="utf-8").splitlines():
        if not line.startswith('{"_header"'):
            continue
        earlier = {"scope": "workspace", **json.loads(line)["_header"]}  # logs from before scopes
        for key, value in settings.items():
            if key in earlier and earlier[key] != value:
                raise CairnError(
                    f"{log} was made with {key} {earlier[key]!r}, not {value!r}: resume it with "
                    f"the same --scope, --model, --runs and --conditions, or start a new run."
                )


class BenchStopped(CairnError):
    """A usage or rate limit: going on would only record failures."""


_LIMIT = re.compile(
    r"(?i)\b(?:session|usage|rate|weekly|\d+-hour)[ _]limit|hit your (?:\w+ )?limit"
)


def usage_limit(result: RunResult) -> bool:
    """An attempt stopped by a plan or rate limit (not a result)."""
    return result.is_error and _LIMIT.search(result.result_text) is not None
