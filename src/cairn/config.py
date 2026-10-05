"""User configuration (.cairn/config.yaml). Every field has a safe default."""

from pydantic import Field

from cairn.model.graph import Frozen


class CairnConfig(Frozen):
    card_budget: int = Field(default=800, ge=200, le=4000)
    index_threshold: int = Field(default=50, ge=5)
    max_depth: int = Field(default=4, ge=1, le=10)
    max_file_bytes: int = Field(default=1_000_000, ge=10_000)
    ignore_dirs: tuple[str, ...] = ()
    stop_tables: tuple[str, ...] = ()
    stop_aliases: tuple[str, ...] = ()
    stale_file_threshold: int = Field(default=50, ge=1)
