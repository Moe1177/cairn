import tomllib

from cairn.integrations.content import (
    SKILL_BODY,
    cursor_rule_mdc,
    gemini_command_toml,
    pointer_text,
    skill_markdown,
)
from cairn.render.tokens import estimate_tokens


def test_pointer_lists_workspaces_and_stays_small() -> None:
    text = pointer_text(["F:/Code/Personal", "D:/work"])
    assert "F:/Code/Personal" in text and "D:/work" in text and ".cairn/INDEX.md" in text
    assert estimate_tokens(text) <= 140


def test_skill_formats_parse() -> None:
    md = skill_markdown()
    assert md.startswith("---\nname: cairn\ndescription: ")
    assert "cairn set-summary" in SKILL_BODY and "cairn annotate-edge" in SKILL_BODY
    parsed = tomllib.loads(gemini_command_toml())
    assert parsed["prompt"].strip().startswith("# cairn") and parsed["description"]
    rule = cursor_rule_mdc("F:/Code/Personal")
    assert "alwaysApply: true" in rule and "F:/Code/Personal" in rule
