"""Messaging detector (spec §21.2): gRPC services implemented/called, and pub/sub topics.

A repo *exposes* a gRPC service it implements and a topic it publishes; it *consumes* a service
it constructs a client for and a topic it subscribes to. Topic names must look specific
(`trip.completed`, not `events`). Line-based and bounded.
"""

import re
from pathlib import Path, PurePosixPath

from cairn.detectors.base import DetectorContext, DetectorResult, merge_facts
from cairn.detectors.database import MAX_FACTS_PER_FILE
from cairn.model.graph import Fact, FactKind

_SUFFIXES = frozenset({".go", ".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".java", ".kt", ".cs"})
_LINE_MAX = 2000
_N = r"(\w{1,80})"
_T = r"""['"]([^'"\s]{3,120})['"]"""

_GRPC_SERVE = tuple(
    re.compile(p)
    for p in (
        rf"\bRegister{_N}Server\(",
        rf"\badd_{_N}Servicer_to_server\(",
        rf"\bclass\s+\w+\(\s*(?:\w+\.)*{_N}Servicer\s*\)",
        rf"\b{_N}Grpc\.\w{{1,80}}ImplBase\b",
        rf"\baddService\(\s*(?:\w+\.)*{_N}\.service\s*,",
        rf"\baddService\(\s*{_N}\s*,",
    )
)
_GRPC_CALL = tuple(
    re.compile(p)
    for p in (
        rf"\bNew{_N}Client\(",
        rf"\b{_N}Stub\(",
        rf"\bnew\s+{_N}Client\(",
        rf"\b{_N}Grpc\.new(?:Blocking|Future)?Stub\(",
    )
)
_PUBLISH = tuple(
    re.compile(p)
    for p in (
        rf"\.(?:send|produce|publish|Publish|send_and_wait|sendMessage)\(\s*{_T}",
        rf"\.(?:send|produce)\(\s*\{{[^}}\n]{{0,200}}?topic\s*:\s*{_T}",
    )
)
# subscribe(['a', 'b']) lists several quoted topics; the other forms name one.
_SUBSCRIBE_LIST = re.compile(
    r"""\.(?:subscribe|Subscribe|QueueSubscribe)\(\s*\[?\s*((?:['"][^'"\n]{0,120}['"]\s*,?\s*){1,20})"""
)
_SUBSCRIBE = tuple(
    re.compile(p)
    for p in (
        rf"\.subscribe\(\s*\{{[^}}\n]{{0,200}}?topics?\s*:\s*\[?\s*{_T}",
        rf"@KafkaListener\([^)\n]{{0,200}}?topics\s*=\s*\{{?\s*{_T}",
        rf"\bKafkaConsumer\(\s*{_T}",
    )
)
_QUOTED = re.compile(r"""['"]([^'"\s]{3,120})['"]""")
_VAGUE_TOPICS = frozenset({"events", "messages", "default", "topic", "queue", "updates", "jobs"})
_NOT_TOPICS = ("text/", "application/", "image/", "multipart/", "http:", "https:", "/")


class MessagingDetector:
    id = "messaging"

    def run(self, ctx: DetectorContext) -> DetectorResult:
        exposes: list[Fact] = []
        consumes: list[Fact] = []
        for path in ctx.files(lambda name: PurePosixPath(name.lower()).suffix in _SUFFIXES):
            text = ctx.read(path)
            if text:
                found_exposes, found_consumes = _scan(ctx, path, text)
                exposes += found_exposes
                consumes += found_consumes
        return DetectorResult(exposes=merge_facts(exposes), consumes=merge_facts(consumes))


def _scan(ctx: DetectorContext, path: Path, text: str) -> tuple[list[Fact], list[Fact]]:
    exposes: list[Fact] = []
    consumes: list[Fact] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if len(exposes) + len(consumes) >= MAX_FACTS_PER_FILE:
            break
        line = raw[:_LINE_MAX]
        served = [_service(m.group(1)) for p in _GRPC_SERVE for m in p.finditer(line)]
        called = [_service(m.group(1)) for p in _GRPC_CALL for m in p.finditer(line)]
        published = [m.group(1) for p in _PUBLISH for m in p.finditer(line)]
        subscribed = [
            t for m in _SUBSCRIBE_LIST.finditer(line) for t in _QUOTED.findall(m.group(1))
        ]
        subscribed += [m.group(1) for p in _SUBSCRIBE for m in p.finditer(line)]
        if not (served or called or published or subscribed):
            continue
        evidence = (ctx.evidence(path, line_no, line),)
        exposes += [Fact(kind=FactKind.GRPC_SERVICE, value=v, evidence=evidence) for v in served]
        consumes += [Fact(kind=FactKind.GRPC_SERVICE, value=v, evidence=evidence) for v in called]
        exposes += [
            Fact(kind=FactKind.TOPIC, value=t, evidence=evidence) for t in published if _topic(t)
        ]
        consumes += [
            Fact(kind=FactKind.TOPIC, value=t, evidence=evidence) for t in subscribed if _topic(t)
        ]
    return exposes, consumes


def _service(name: str) -> str:
    """grpc-tools names TS services `XServiceService`; every other generator says `XService`."""
    return name[: -len("Service")] if name.endswith("ServiceService") else name


def _topic(name: str) -> bool:
    lowered = name.lower()
    return (
        len(name) >= 5
        and any(ch in name for ch in ".-_/:")
        and lowered not in _VAGUE_TOPICS
        and not lowered.startswith(_NOT_TOPICS)
    )
