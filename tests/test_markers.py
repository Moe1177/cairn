from cairn.render.markers import END, START, remove_block, upsert_block


def test_append_to_existing_content_and_remove_restores_it() -> None:
    original = "# My notes\n\nKeep this.\n"
    updated = upsert_block(original, "line 1\nline 2")
    assert updated == f"# My notes\n\nKeep this.\n\n{START}\nline 1\nline 2\n{END}\n"
    assert remove_block(updated) == original


def test_upsert_is_idempotent_and_replaces_in_place() -> None:
    once = upsert_block("top\n", "v1")
    twice = upsert_block(upsert_block(once, "v2"), "v2")
    assert twice.count(START) == 1
    assert "v2" in twice and "v1" not in twice
    assert twice.startswith("top\n")


def test_crlf_files_stay_crlf() -> None:
    # Review Focus 4
    original = "# Notes\r\n\r\nUser text.\r\n"
    updated = upsert_block(original, "a\nb")
    assert updated.startswith(original)
    assert "\n" not in updated.replace("\r\n", "")
    assert remove_block(updated) == original


def test_empty_file_and_duplicates() -> None:
    assert upsert_block("", "x") == f"{START}\nx\n{END}\n"
    assert remove_block(f"{START}\nx\n{END}\n") == ""
    doubled = f"a\n{START}\nold\n{END}\nb\n{START}\nold2\n{END}\n"
    assert upsert_block(doubled, "new").count(START) == 1


def test_incomplete_block_is_refused_not_destroyed() -> None:
    # Final review I2: an orphan START let upsert/remove delete user text.
    import pytest

    from cairn.errors import CairnError

    broken = f"{START}\nold index\nIMPORTANT USER NOTES\n"
    with pytest.raises(CairnError):
        upsert_block(broken, "new")
    with pytest.raises(CairnError):
        remove_block(broken)
    with pytest.raises(CairnError):
        upsert_block(f"{END}\nx\n{START}\n", "new")


def test_custom_markers_for_toml() -> None:
    from cairn.render.markers import TOML_END, TOML_START

    out = upsert_block('model = "x"\n', "[mcp_servers.cairn]", start=TOML_START, end=TOML_END)
    assert out == 'model = "x"\n\n# cairn:start\n[mcp_servers.cairn]\n# cairn:end\n'
    assert remove_block(out, start=TOML_START, end=TOML_END) == 'model = "x"\n'
