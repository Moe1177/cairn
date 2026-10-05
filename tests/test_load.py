from pathlib import Path

import pytest

from cairn.errors import CairnInputError
from cairn.load import load_authored, load_config, load_relations
from cairn.model.graph import EdgeType
from cairn.paths import authored_dir, config_file, relations_file


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_missing_files_give_defaults(tmp_path: Path) -> None:
    assert load_config(tmp_path).card_budget == 800
    assert load_relations(tmp_path).edges == ()
    assert load_authored(tmp_path) == {}


def test_config_overrides_defaults(tmp_path: Path) -> None:
    _write(config_file(tmp_path), "card_budget: 600\nstop_tables: [payments]\n")
    config = load_config(tmp_path)
    assert config.card_budget == 600
    assert config.stop_tables == ("payments",)


def test_invalid_yaml_reports_path(tmp_path: Path) -> None:
    _write(config_file(tmp_path), "card_budget: [unclosed\n")
    with pytest.raises(CairnInputError) as info:
        load_config(tmp_path)
    assert "config.yaml" in str(info.value)
    assert "invalid YAML" in str(info.value)


def test_wrong_type_reports_key(tmp_path: Path) -> None:
    _write(config_file(tmp_path), "card_budget: lots\n")
    with pytest.raises(CairnInputError) as info:
        load_config(tmp_path)
    assert "card_budget" in str(info.value)


def test_unknown_key_rejected(tmp_path: Path) -> None:
    _write(config_file(tmp_path), "card_budjet: 600\n")
    with pytest.raises(CairnInputError):
        load_config(tmp_path)


def test_top_level_must_be_mapping(tmp_path: Path) -> None:
    _write(relations_file(tmp_path), "- just\n- a list\n")
    with pytest.raises(CairnInputError) as info:
        load_relations(tmp_path)
    assert "mapping" in str(info.value)


def test_relations_parse_from_to_aliases(tmp_path: Path) -> None:
    _write(
        relations_file(tmp_path),
        "aliases:\n  admin: [owner portal]\n"
        "edges:\n  - {from: admin, to: app, note: use the API}\n"
        "remove_edges:\n  - {from: a, to: b, type: mentions}\n"
        "ignore_repos: [notes]\n"
        "notes:\n  app: deploys on Vercel\n",
    )
    rel = load_relations(tmp_path)
    assert rel.aliases == {"admin": ("owner portal",)}
    assert rel.edges[0].source == "admin"
    assert rel.edges[0].type is EdgeType.MANUAL
    assert rel.remove_edges[0].type is EdgeType.MENTIONS
    assert rel.ignore_repos == ("notes",)
    assert rel.notes == {"app": "deploys on Vercel"}


def test_authored_files_keyed_by_stem(tmp_path: Path) -> None:
    _write(authored_dir(tmp_path) / "admin.yaml", "summary: Owner portal\nsummary_sha: 1234567\n")
    _write(authored_dir(tmp_path) / "app.yaml", "edge_reviews:\n  'app->admin:mentions': rejected\n")
    authored = load_authored(tmp_path)
    assert authored["admin"].summary == "Owner portal"
    assert authored["admin"].summary_sha == "1234567"
    assert authored["app"].edge_reviews == {"app->admin:mentions": "rejected"}


def test_authored_invalid_review_value(tmp_path: Path) -> None:
    _write(authored_dir(tmp_path) / "app.yaml", "edge_reviews:\n  'a->b:mentions': maybe\n")
    with pytest.raises(CairnInputError):
        load_authored(tmp_path)
