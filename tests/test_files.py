from pathlib import Path

from cairn.discover.files import iter_files, read_text
from tests.helpers import write


def _names(root: Path, **kwargs) -> list[str]:
    return [p.relative_to(root).as_posix() for p in iter_files(root, **kwargs)]


def test_skips_ignored_dirs_and_nested_repos(tmp_path: Path) -> None:
    write(tmp_path, "src/a.ts", "x")
    write(tmp_path, "node_modules/pkg/index.js", "x")
    write(tmp_path, ".next/server.js", "x")
    write(tmp_path, "nested/.git/HEAD", "ref")
    write(tmp_path, "nested/b.ts", "x")
    assert _names(tmp_path) == ["src/a.ts"]


def test_respects_root_gitignore(tmp_path: Path) -> None:
    write(tmp_path, ".gitignore", "generated/\n*.log\n")
    write(tmp_path, "generated/out.ts", "x")
    write(tmp_path, "debug.log", "x")
    write(tmp_path, "keep.ts", "x")
    assert _names(tmp_path) == [".gitignore", "keep.ts"]


def test_skips_forbidden_but_keeps_env_templates(tmp_path: Path) -> None:
    write(tmp_path, ".env.local", "SECRET=1")
    write(tmp_path, ".env.example", "SECRET=")
    assert _names(tmp_path) == [".env.example"]


def test_skips_oversized_files(tmp_path: Path) -> None:
    write(tmp_path, "big.sql", "x" * 2000)
    write(tmp_path, "small.sql", "x")
    assert _names(tmp_path, max_bytes=1000) == ["small.sql"]


def test_match_filters_by_name(tmp_path: Path) -> None:
    write(tmp_path, "a.sql", "x")
    write(tmp_path, "b.ts", "x")
    assert _names(tmp_path, match=lambda n: n.endswith(".sql")) == ["a.sql"]


def test_stat_failure_is_skipped(tmp_path: Path, monkeypatch) -> None:
    write(tmp_path, "ok.ts", "x")
    write(tmp_path, "bad.ts", "x")
    real_stat = Path.stat

    def flaky_stat(self: Path, *args, **kwargs):
        if self.name == "bad.ts":
            raise OSError("permission denied")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", flaky_stat)
    assert _names(tmp_path) == ["ok.ts"]


def test_read_text_handles_binary_bom_and_bad_bytes(tmp_path: Path) -> None:
    binary = tmp_path / "img.png"
    binary.write_bytes(b"\x89PNG\x00\x00data")
    bom = tmp_path / "bom.md"
    bom.write_bytes("﻿hello".encode())
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"ok \xff\xfe end")
    assert read_text(binary) is None
    assert read_text(bom) == "hello"
    assert read_text(bad) == "ok �� end"


def test_read_text_refuses_missing_forbidden_and_oversized(tmp_path: Path) -> None:
    env = write(tmp_path, ".env", "SECRET=1")
    big = write(tmp_path, "big.txt", "x" * 50)
    assert read_text(tmp_path / "missing.txt") is None
    assert read_text(env) is None
    assert read_text(big, max_bytes=10) is None
