"""Time cairn's scan on a synthetic workspace (spec §22 budgets: cold < 30 s, warm < 2 s).

    uv run python bench/perf_scan.py --repos 200 --files 250 --out /tmp/cairn-perf

The workspace is generated once (git repos with Python services that expose routes, read env
vars and name a sibling) and reused on later runs. Timings depend on the machine and OS:
process start-up dominates a warm refresh on Windows. Nothing here runs in CI.
"""

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

from cairn.emit import write_outputs
from cairn.scan import scan_workspace

_FILLER = "x = 1\n" * 40


def generate(root: Path, repos: int, files: int) -> None:
    for r in range(repos):
        repo = root / f"svc-{r:03d}"
        if (repo / ".git").exists():
            continue
        folders = max(1, files // 25)
        for i in range(files):
            folder = repo / "src" / f"mod{i % folders}"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"file{i}.py").write_text(
                "import os\nfrom fastapi import APIRouter\nrouter = APIRouter()\n"
                f"@router.get('/svc{r}/items/{i}')\ndef handler_{i}():\n"
                f"    return os.environ.get('SVC_{r}_URL')\n" + _FILLER,
                encoding="utf-8",
            )
        sibling = f"svc-{(r + 1) % repos:03d}"
        (repo / "README.md").write_text(f"# svc-{r:03d}\nTalks to {sibling}.\n", encoding="utf-8")
        (repo / "pyproject.toml").write_text(
            f'[project]\nname = "svc-{r:03d}"\ndependencies = ["fastapi", "{sibling}"]\n',
            encoding="utf-8",
        )
        for args in (
            ["init", "-q"],
            ["add", "-A"],
            [
                "-c",
                "user.email=perf@example.com",
                "-c",
                "user.name=perf",
                "commit",
                "-q",
                "-m",
                "x",
            ],
        ):
            subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def measure(root: Path) -> tuple[float, float]:
    shutil.rmtree(root / ".cairn", ignore_errors=True)
    start = time.perf_counter()
    write_outputs(root, scan_workspace(root))
    cold = time.perf_counter() - start
    start = time.perf_counter()
    write_outputs(root, scan_workspace(root))
    return cold, time.perf_counter() - start


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Time cairn's scan on a synthetic workspace.")
    parser.add_argument("--repos", type=int, default=200)
    parser.add_argument("--files", type=int, default=250, help="Python files per repo")
    parser.add_argument("--out", type=Path, required=True, help="where the workspace lives")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    generate(args.out, args.repos, args.files)
    cold, warm = measure(args.out.resolve())
    print(
        f"{args.repos} repos x {args.files} files: cold scan {cold:.1f}s, warm refresh {warm:.2f}s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
