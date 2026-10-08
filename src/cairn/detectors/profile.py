"""Profile detector: tech stack, run commands, and a top-level layout map."""

import re
from pathlib import Path

from cairn.detectors.aws import deploy_stack
from cairn.detectors.base import DetectorContext, DetectorResult
from cairn.detectors.manifests import (
    dig,
    load_json,
    load_toml,
    normalize_py,
    npm_dependencies,
    parse_go_mod,
    python_requirement_names,
)
from cairn.discover.files import DEFAULT_IGNORE_DIRS, is_link
from cairn.model.graph import Command, LayoutEntry

_PLAIN_PATH = re.compile(r"[A-Za-z0-9._/@+\-]+")

_JS_STACK = (
    ("next", "nextjs"),
    ("react", "react"),
    ("vue", "vue"),
    ("svelte", "svelte"),
    ("express", "express"),
    ("@nestjs/core", "nestjs"),
    ("drizzle-orm", "drizzle"),
    ("prisma", "prisma"),
    ("@prisma/client", "prisma"),
    ("@neondatabase/serverless", "neon"),
    ("@supabase/supabase-js", "supabase"),
    ("stripe", "stripe"),
)
_PY_STACK = (
    ("fastapi", "fastapi"),
    ("django", "django"),
    ("flask", "flask"),
    ("sqlalchemy", "sqlalchemy"),
)
_GO_STACK = (
    ("github.com/gin-gonic/gin", "gin"),
    ("github.com/labstack/echo", "echo"),
    ("github.com/gofiber/fiber", "fiber"),
)
_SCRIPTS = ("dev", "start", "build", "test", "lint")
_LOCKFILES = (
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("bun.lockb", "bun"),
    ("bun.lock", "bun"),
)
MAX_LAYOUT = 12
LAYOUT_PURPOSES = {
    "app": "routes/pages",
    "pages": "routes/pages",
    "src": "source",
    "lib": "library code",
    "components": "UI components",
    "db": "database",
    "migrations": "DB migrations",
    "api": "API",
    "tests": "tests",
    "test": "tests",
    "__tests__": "tests",
    "e2e": "e2e tests",
    "docs": "docs",
    "scripts": "scripts",
    "public": "static assets",
    "cmd": "entrypoints",
    "internal": "internal packages",
    "pkg": "packages",
    "prisma": "Prisma schema",
    "supabase": "Supabase config",
    "hooks": "hooks",
    "styles": "styles",
    "config": "config",
}

Probe = tuple[list[str], list[Command]]


class ProfileDetector:
    id = "profile"

    def run(self, ctx: DetectorContext) -> DetectorResult:
        stack: list[str] = []
        commands: list[Command] = []
        multi = len(ctx.repo.app_roots) > 1
        for root in ctx.repo.app_roots:
            for probe in (_node, _python, _go, _rust, _java):
                found_stack, found_cmds = probe(ctx, root)
                stack += found_stack
                scoped = (_scoped(ctx, root, c, multi) for c in found_cmds)
                commands += [c for c in scoped if c is not None]
        stack += deploy_stack(ctx)
        return DetectorResult(
            stack=tuple(dict.fromkeys(stack)),
            commands=_first_by_name(commands),
            layout=_layout(ctx),
        )


def _first_by_name(commands: list[Command]) -> tuple[Command, ...]:
    seen: dict[str, Command] = {}
    for command in commands:
        seen.setdefault(command.name, command)
    return tuple(seen.values())


def _node(ctx: DetectorContext, root: Path) -> Probe:
    pkg = load_json(root / "package.json", ctx.config.max_file_bytes)
    if pkg is None:
        return [], []
    deps = set(npm_dependencies(pkg))
    language = (
        "typescript" if "typescript" in deps or (root / "tsconfig.json").is_file() else "javascript"
    )
    stack = [language, *(label for dep, label in _JS_STACK if dep in deps)]
    runner = next(
        (
            pm
            for lock, pm in _LOCKFILES
            if (root / lock).is_file() or (ctx.repo.root / lock).is_file()
        ),
        "npm",
    )
    raw_scripts = pkg.get("scripts")
    scripts = raw_scripts if isinstance(raw_scripts, dict) else {}
    return stack, [Command(name=s, run=f"{runner} run {s}") for s in _SCRIPTS if s in scripts]


def _python(ctx: DetectorContext, root: Path) -> Probe:
    pyproject = load_toml(root / "pyproject.toml", ctx.config.max_file_bytes)
    requirements = ctx.read(root / "requirements.txt")
    if pyproject is None and requirements is None and not (root / "setup.py").is_file():
        return [], []
    names = {normalize_py(n) for n in python_requirement_names(pyproject, requirements)}
    stack = ["python", *(label for dep, label in _PY_STACK if dep in names)]
    has_tests = (
        "pytest" in names
        or (root / "tests").is_dir()
        or dig(pyproject, "tool", "pytest") is not None
    )
    return stack, [Command(name="test", run="pytest")] if has_tests else []


def _go(ctx: DetectorContext, root: Path) -> Probe:
    text = ctx.read(root / "go.mod")
    if not text:
        return [], []
    _, requires = parse_go_mod(text)
    stack = [
        "go",
        *(label for prefix, label in _GO_STACK if any(r.startswith(prefix) for r in requires)),
    ]
    return stack, [
        Command(name="test", run="go test ./..."),
        Command(name="build", run="go build ./..."),
    ]


def _rust(ctx: DetectorContext, root: Path) -> Probe:
    if not (root / "Cargo.toml").is_file():
        return [], []
    return ["rust"], [
        Command(name="test", run="cargo test"),
        Command(name="build", run="cargo build"),
    ]


def _java(ctx: DetectorContext, root: Path) -> Probe:
    if (root / "pom.xml").is_file():
        return ["java"], [Command(name="test", run="mvn test")]
    if (root / "build.gradle").is_file():
        return ["java"], [Command(name="test", run="./gradlew test")]
    return [], []


def _scoped(ctx: DetectorContext, root: Path, command: Command, multi: bool) -> Command | None:
    """`cd <app> && <cmd>`; None when the folder name isn't plain, since a card's commands are
    meant to be pasted into a shell (sh, cmd, or PowerShell, which quote differently)."""
    rel = root.relative_to(ctx.repo.root).as_posix()
    if rel == ".":
        return command
    if not _PLAIN_PATH.fullmatch(rel):
        return None
    name = f"{rel}:{command.name}" if multi else command.name
    return Command(name=name, run=f"cd {rel} && {command.run}")


def _layout(ctx: DetectorContext) -> tuple[LayoutEntry, ...]:
    primary = ctx.repo.app_roots[0] if ctx.repo.app_roots else ctx.repo.root
    prefix = primary.relative_to(ctx.repo.root).as_posix()
    ignore = DEFAULT_IGNORE_DIRS | frozenset(ctx.config.ignore_dirs)
    try:
        children = sorted(
            (
                p
                for p in primary.iterdir()
                if p.is_dir()
                and not is_link(p)
                and not p.name.startswith(".")
                and p.name not in ignore
            ),
            key=lambda p: p.name,  # string order: identical on every OS (spec §20.2)
        )
    except OSError:
        return ()
    return tuple(
        LayoutEntry(
            path=f"{child.name if prefix == '.' else f'{prefix}/{child.name}'}/",
            purpose=LAYOUT_PURPOSES.get(child.name.lower()),
        )
        for child in children[:MAX_LAYOUT]
    )
