from pathlib import Path

from cairn.emit import write_outputs
from cairn.paths import cards_dir, index_file, workspace_file
from cairn.scan import scan_workspace
from tests.helpers import make_repo, write


def test_writes_all_outputs_and_prunes_stale_cards(tmp_path: Path) -> None:
    make_repo(tmp_path, "alpha", {"README.md": "# alpha\n\nAlpha service.\n"})
    make_repo(tmp_path, "beta")
    write(tmp_path, ".cairn/cards/gone.md", "old")
    written = write_outputs(tmp_path, scan_workspace(tmp_path))
    assert workspace_file(tmp_path).is_file()
    assert sorted(p.name for p in cards_dir(tmp_path).glob("*.md")) == ["alpha.md", "beta.md"]
    assert "- alpha: Alpha service" in index_file(tmp_path).read_text(encoding="utf-8")
    assert index_file(tmp_path) in written
