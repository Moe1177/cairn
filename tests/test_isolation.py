"""No test may touch the developer's real harness configs (~/.cursor, ~/.codex, ~/.claude...)."""

from pathlib import Path

from cairn.integrations.homes import claude_home, codex_home, cursor_home, gemini_home


def test_every_harness_home_is_redirected_during_tests() -> None:
    real = Path.home()
    defaults = {real / ".claude", real / ".codex", real / ".cursor", real / ".gemini"}
    for home in (claude_home(), codex_home(), cursor_home(), gemini_home()):
        assert home not in defaults, f"a test would write the real {home}"
