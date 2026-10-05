"""Human- and harness-authored inputs. These are never overwritten by a scan."""

from typing import Literal

from pydantic import ConfigDict, Field

from cairn.model.graph import EdgeType, Frozen


class ManualEdge(Frozen):
    source: str = Field(alias="from")
    target: str = Field(alias="to")
    type: EdgeType = EdgeType.MANUAL
    note: str | None = None


class RemovedEdge(Frozen):
    source: str = Field(alias="from")
    target: str = Field(alias="to")
    type: EdgeType | None = None


class Relations(Frozen):
    aliases: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    edges: tuple[ManualEdge, ...] = ()
    remove_edges: tuple[RemovedEdge, ...] = ()
    ignore_repos: tuple[str, ...] = ()
    notes: dict[str, str] = Field(default_factory=dict)


class Authored(Frozen):
    model_config = ConfigDict(coerce_numbers_to_str=True)

    summary: str | None = None
    summary_sha: str | None = None
    aliases: tuple[str, ...] = ()
    edge_whys: dict[str, str] = Field(default_factory=dict)
    edge_reviews: dict[str, Literal["confirmed", "rejected"]] = Field(default_factory=dict)
