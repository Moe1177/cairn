from cairn.emit import write_outputs
from cairn.paths import logs_dir
from cairn.scan import scan_workspace
from cairn.scan_log import render_log


def test_log_lists_cache_use_and_errors(materialize) -> None:
    ws = materialize("mini-eats").resolve()
    write_outputs(ws, scan_workspace(ws))
    result = scan_workspace(ws)
    text = render_log(result)
    assert "repos: 4 (4 from cache, 0 re-read)" in text and "re-read: none" in text
    write_outputs(ws, result)
    assert (logs_dir(ws) / "last-scan.log").read_text(encoding="utf-8") == text
