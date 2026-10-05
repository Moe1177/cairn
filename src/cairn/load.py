"""Load user-editable YAML inputs into validated models with friendly errors."""

from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from cairn.config import CairnConfig
from cairn.errors import CairnInputError
from cairn.model.overrides import Authored, Relations
from cairn.paths import authored_dir, config_file, relations_file

M = TypeVar("M", bound=BaseModel)


def load_config(ws_root: Path) -> CairnConfig:
    return _load_yaml_model(config_file(ws_root), CairnConfig)


def load_relations(ws_root: Path) -> Relations:
    return _load_yaml_model(relations_file(ws_root), Relations)


def load_authored(ws_root: Path) -> dict[str, Authored]:
    directory = authored_dir(ws_root)
    if not directory.is_dir():
        return {}
    return {
        path.stem: _load_yaml_model(path, Authored) for path in sorted(directory.glob("*.yaml"))
    }


def _load_yaml_model(path: Path, model: type[M]) -> M:
    if not path.is_file():
        return model()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise CairnInputError(str(path), f"invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise CairnInputError(str(path), "expected a mapping at the top level")
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise CairnInputError(str(path), _describe(exc)) from exc


def _describe(exc: ValidationError) -> str:
    errors = exc.errors()
    first = errors[0]
    location = ".".join(str(part) for part in first["loc"]) or "(root)"
    extra = f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""
    return f"{location}: {first['msg']}{extra}"
