"""The block flow diagram that every enumerated case is a path through.

There is one graph, not one diagram per case.  Its blocks and streams are the
union of everything that appears in any case, each guarded by the same kind of
predicate the logic cuts and operating variables use.  Given a full or partial
selection, a block or stream is in one of three states:

    ACTIVE      present in every case still consistent with the selection
    POSSIBLE    present in some of them, so the choice is still open
    ELIMINATED  present in none of them

Two states would collapse the last one into "not chosen yet", which is exactly
the distinction the logic cuts exist to make.

A predicate is a conjunction of memberships, or a disjunction of such
conjunctions written as {"any_of": [...]}. The disjunction is needed by units
that serve more than one branch: demineralised make-up water feeds a steam
cycle or an NOx electrolyser, and a conjunction cannot say "either".

`check_connectivity` is the diagram's correctness test: in every enumerated case
the active subgraph must carry the fuel from the tank to the power outlet, no
unit may be orphaned, and no active stream may touch an inactive unit.  The last
check was missing until the 2026-09-11 review: the connectivity pass filtered
such streams out before looking, so 315 of them were silently dropped instead of
reported.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence

from .superstructure import Selection, Superstructure

SOURCE = "TANK"
SINK = "POWER"

Conjunction = Mapping[str, tuple[str, ...]]
#: Disjunctive normal form: the predicate holds when any conjunction holds.
Predicate = tuple[Conjunction, ...]


class State(str, Enum):
    ACTIVE = "active"
    POSSIBLE = "possible"
    ELIMINATED = "eliminated"


def _as_code_map(raw: Mapping[str, Sequence[str]] | None) -> Conjunction:
    if raw is None:
        return {}
    return {node: tuple(codes) for node, codes in raw.items()}


def as_predicate(raw: Mapping | None) -> Predicate:
    """Normalise a JSON predicate to disjunctive normal form."""
    if not raw:
        return ({},)
    if "any_of" in raw:
        if len(raw) != 1:
            raise ValueError("an any_of predicate cannot carry other keys beside it")
        branches = tuple(_as_code_map(branch) for branch in raw["any_of"])
        if not branches:
            raise ValueError("an any_of predicate needs at least one branch")
        return branches
    return (_as_code_map(raw),)


def _conjunction_holds(conjunction: Conjunction, selection: Selection) -> bool:
    """An absent node makes the conjunction false."""
    return all(selection.get(node) in codes for node, codes in conjunction.items())


def holds(predicate: Predicate, selection: Selection) -> bool:
    return any(_conjunction_holds(c, selection) for c in predicate)


# Kept for callers that still pass a single conjunction.
def _holds(predicate: Conjunction, selection: Selection) -> bool:
    return _conjunction_holds(predicate, selection)


@dataclass(frozen=True)
class Block:
    id: str
    x: int
    y: int
    label: str
    label_ko: str
    #: Why this unit is in the diagram at all, answered where a reviewer asks.
    rationale: str
    active_when: Predicate
    dynamic_label: Mapping[str, Mapping[str, str]]
    #: "unit", or "boundary" for a supply or discharge that is not equipment.
    kind: str = "unit"

    def is_active(self, selection: Selection) -> bool:
        return holds(self.active_when, selection)

    def label_for(self, selection: Selection) -> str:
        """A unit whose duty changes with the feed says so on the diagram."""
        for node, by_code in self.dynamic_label.items():
            code = selection.get(node)
            if code in by_code:
                return by_code[code]
        return self.label


@dataclass(frozen=True)
class Stream:
    source: str
    target: str
    type: str
    active_when: Predicate
    #: A stable number that survives reordering and retirement (E001...).
    sid: str = ""
    #: What the stream carries, where the colour alone would mislead.
    label: str = ""

    @property
    def id(self) -> str:
        return f"{self.source}>{self.target}:{self.type}"

    def is_active(self, selection: Selection) -> bool:
        return holds(self.active_when, selection)


@dataclass(frozen=True)
class Flowsheet:
    name: str
    schema_version: str
    canvas: Mapping[str, int]
    stream_types: Mapping[str, Mapping[str, str]]
    blocks: tuple[Block, ...]
    streams: tuple[Stream, ...]

    def block(self, block_id: str) -> Block:
        for block in self.blocks:
            if block.id == block_id:
                return block
        raise KeyError(block_id)

    def active_blocks(self, selection: Selection) -> tuple[str, ...]:
        return tuple(block.id for block in self.blocks if block.is_active(selection))

    def active_streams(self, selection: Selection) -> tuple[Stream, ...]:
        return tuple(stream for stream in self.streams if stream.is_active(selection))

    def states(self, selections: Sequence[Selection]) -> tuple[Mapping[str, State], Mapping[str, State]]:
        """Classify every block and stream against the cases still in play.

        `selections` is the set of enumerated cases consistent with what the
        reader has pinned so far - all of them when nothing is pinned, exactly
        one when the selection is complete.
        """
        if not selections:
            eliminated_blocks = {block.id: State.ELIMINATED for block in self.blocks}
            eliminated_streams = {stream.id: State.ELIMINATED for stream in self.streams}
            return eliminated_blocks, eliminated_streams

        total = len(selections)

        def classify(hits: int) -> State:
            if hits == 0:
                return State.ELIMINATED
            return State.ACTIVE if hits == total else State.POSSIBLE

        blocks = {
            block.id: classify(sum(block.is_active(s) for s in selections)) for block in self.blocks
        }
        streams = {
            stream.id: classify(sum(stream.is_active(s) for s in selections)) for stream in self.streams
        }
        return blocks, streams

    def check_connectivity(self, selection: Selection) -> tuple[str, ...]:
        """Faults in one case's active subgraph.

        Three kinds: an active stream touching an inactive unit, an active unit
        with no active stream, and a power outlet the fuel cannot reach.
        """
        active = set(self.active_blocks(selection))
        streams = self.active_streams(selection)

        faults: list[str] = []
        for stream in streams:
            for end in (stream.source, stream.target):
                if end not in active:
                    faults.append(f"stream {stream.sid or stream.id} is active but {end} is not")

        live = [s for s in streams if s.source in active and s.target in active]
        touched = {end for stream in live for end in (stream.source, stream.target)}
        for block_id in sorted(active - touched):
            faults.append(f"{block_id} is active but connects to nothing")

        adjacency: dict[str, list[str]] = {block_id: [] for block_id in active}
        for stream in live:
            adjacency[stream.source].append(stream.target)

        seen = {SOURCE} if SOURCE in active else set()
        queue = deque(seen)
        while queue:
            for neighbour in adjacency[queue.popleft()]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    queue.append(neighbour)
        if SINK in active and SINK not in seen:
            faults.append(f"{SINK} is not reachable from {SOURCE}")
        return tuple(faults)


def load_flowsheet(path: str | Path, superstructure: Superstructure) -> Flowsheet:
    """Load the diagram, checking it against the decision space it illustrates.

    A predicate naming an option that does not exist would silently never fire,
    leaving a block permanently dark for no stated reason, so it is an error.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    known = superstructure.axes()

    def validate(where: str, predicate: Predicate) -> None:
        for conjunction in predicate:
            for node_id, codes in conjunction.items():
                if node_id not in known:
                    raise ValueError(f"{where} references unknown node '{node_id}'")
                unknown = set(codes) - known[node_id]
                if unknown:
                    raise ValueError(f"{where} references unknown {node_id} options: {sorted(unknown)}")

    blocks: list[Block] = []
    for item in raw["blocks"]:
        dynamic = {node: dict(by_code) for node, by_code in item.get("dynamic_label", {}).items()}
        block = Block(
            id=item["id"],
            x=int(item["x"]),
            y=int(item["y"]),
            label=item["label"],
            label_ko=item["label_ko"],
            rationale=item.get("rationale", ""),
            active_when=as_predicate(item.get("active_when")),
            dynamic_label=dynamic,
            kind=item.get("kind", "unit"),
        )
        validate(f"block {block.id}", block.active_when)
        for node, by_code in dynamic.items():
            validate(f"block {block.id} dynamic label", ({node: tuple(by_code)},))
        blocks.append(block)

    ids = {block.id for block in blocks}
    if len(ids) != len(blocks):
        raise ValueError("duplicate block id in the flowsheet")
    for required in (SOURCE, SINK):
        if required not in ids:
            raise ValueError(f"the flowsheet has no '{required}' block")

    streams: list[Stream] = []
    for item in raw["streams"]:
        stream = Stream(
            source=item["from"],
            target=item["to"],
            type=item["type"],
            active_when=as_predicate(item.get("active_when")),
            sid=item.get("sid", ""),
            label=item.get("label", ""),
        )
        for end in (stream.source, stream.target):
            if end not in ids:
                raise ValueError(f"stream {stream.id} references unknown block '{end}'")
        if stream.type not in raw["stream_types"]:
            raise ValueError(f"stream {stream.id} has unknown type '{stream.type}'")
        validate(f"stream {stream.id}", stream.active_when)
        streams.append(stream)

    sids = [s.sid for s in streams if s.sid]
    if len(sids) != len(set(sids)):
        raise ValueError("duplicate stream sid in the flowsheet")

    return Flowsheet(
        name=raw["flowsheet_name"],
        schema_version=raw["schema_version"],
        canvas=raw["canvas"],
        stream_types=raw["stream_types"],
        blocks=tuple(blocks),
        streams=tuple(streams),
    )
