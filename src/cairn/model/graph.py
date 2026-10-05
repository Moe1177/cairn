"""Core graph models. All models are immutable; build new instances instead of mutating."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_EVIDENCE = 3


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class FactKind(StrEnum):
    PACKAGE = "package"
    HTTP_ROUTE = "http_route"
    DB_TABLE = "db_table"
    DB_PROJECT_REF = "db_project_ref"
    ENV_VAR_NAME = "env_var_name"
    COMPOSE_SERVICE = "compose_service"
    GRPC_SERVICE = "grpc_service"
    TOPIC = "topic"
    PATH_REF = "path_ref"
    DOC_MENTION = "doc_mention"
    CLI = "cli"


class EdgeType(StrEnum):
    DEPENDS_ON_PACKAGE = "depends_on_package"
    CALLS_HTTP = "calls_http"
    SHARES_DB = "shares_db"
    COMPOSE_LINK = "compose_link"
    GRPC = "grpc"
    PUBSUB = "pubsub"
    PATH_REF = "path_ref"
    MENTIONS = "mentions"
    SHARES_ENV = "shares_env"
    MANUAL = "manual"


SYMMETRIC_TYPES = frozenset({EdgeType.SHARES_DB, EdgeType.SHARES_ENV})


class Confidence(StrEnum):
    EXTRACTED = "extracted"
    INFERRED = "inferred"
    AMBIGUOUS = "ambiguous"

    @property
    def rank(self) -> int:
        return {"extracted": 3, "inferred": 2, "ambiguous": 1}[self.value]


class Evidence(Frozen):
    repo: str
    file: str
    line: int = Field(ge=1)
    snippet: str = Field(max_length=200)


class Fact(Frozen):
    kind: FactKind
    value: str = Field(min_length=1)
    evidence: tuple[Evidence, ...] = ()


class Contracts(Frozen):
    exposes: tuple[Fact, ...] = ()
    consumes: tuple[Fact, ...] = ()


class Command(Frozen):
    name: str
    run: str


class LayoutEntry(Frozen):
    path: str
    purpose: str | None = None


class DetectorError(Frozen):
    detector: str
    message: str


class Repo(Frozen):
    id: str
    path: str
    app_roots: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    remote: str | None = None
    stack: tuple[str, ...] = ()
    head_sha: str | None = None
    dirty: bool | None = None
    commands: tuple[Command, ...] = ()
    layout: tuple[LayoutEntry, ...] = ()
    readme_excerpt: str | None = None
    contracts: Contracts = Field(default_factory=Contracts)
    detector_errors: tuple[DetectorError, ...] = ()


class Edge(Frozen):
    source: str
    target: str
    type: EdgeType
    confidence: Confidence
    score: float = Field(ge=0.0, le=1.0)
    signals: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    why: str | None = None
    note: str | None = None

    @property
    def key(self) -> str:
        return f"{self.source}->{self.target}:{self.type.value}"


class Workspace(Frozen):
    schema_version: Literal[1] = 1
    workspace_root: str
    generated_at: str
    repos: tuple[Repo, ...] = ()
    edges: tuple[Edge, ...] = ()

    def repo(self, repo_id: str) -> Repo | None:
        return next((r for r in self.repos if r.id == repo_id), None)

    def edges_for(self, repo_id: str) -> tuple[Edge, ...]:
        return tuple(e for e in self.edges if repo_id in (e.source, e.target))
