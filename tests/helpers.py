"""Small builders for test workspaces."""

from pathlib import Path


def write(root: Path, rel: str, text: str = "") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_repo(ws: Path, name: str, files: dict[str, str] | None = None) -> Path:
    root = ws / name
    (root / ".git").mkdir(parents=True)
    for rel, text in (files or {}).items():
        write(root, rel, text)
    return root
