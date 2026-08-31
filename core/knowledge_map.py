"""The map consulted BEFORE retrieval, so the corpus is never loaded to answer.

SR-007 is "a mapping system INSTEAD of dumping huge volumes of tokens, files and
code into context", and A-006 is the acceptance it exists for: exact source
spans from a large project WITHOUT loading the repository. Those two only meet
if the navigation structure and the evidence are DIFFERENT THINGS -- the map
says where to look, the span is what may be cited.

THE SCHEMA EXCLUDES A CONTENT FIELD AND SAYS WHY, and the reason is a prediction
about this file: "if the map could carry content, the first implementation under
memory pressure would populate it, and the map would become the token dump
SR-007 exists to replace." So `MapNode` has no content, and `to_dict` is
validated against `additionalProperties: false` rather than trusted -- a field
added here in a hurry fails the contract instead of quietly becoming a cache of
the repository.

A SUMMARY IS NAVIGATION METADATA AND IS NEVER CITABLE. This is the line the
whole design rests on, and the shortcut that erases it is obvious and available:
the map already holds a one-line summary of every node, so returning summaries
would answer most questions cheaply. That is a RAG pipeline with a different
name, which is precisely what SR-052 -- "BAG instead of RAG, no guessing" --
forbids. `retrieve` reads the locator and returns byte spans; nothing in this
module can put a summary into evidence.

STALENESS IS DETECTED BY HASH, NOT BY AGE. A node whose content hash no longer
matches its locator is stale and must not be served as current. Using
`valid_until` alone would mean a file edited one second after the rebuild reads
as fresh for the rest of the window, and `INV-COORD-4` already says the wall
clock does not decide these questions -- `valid_until` schedules the next
rebuild, the hash decides what is true now.

AND A MISS IS `UNKNOWN`, NEVER "NO SUCH THING EXISTS". `INV-EVID-3` makes
UNKNOWN first class, and the distinction is not pedantic here: `coverage_ratio`
is nullable, null means UNMEASURED, and an unmeasured map is treated as
incomplete. A retrieval that finds nothing in a map covering an unknown fraction
of its corpus has learned nothing about the corpus -- reporting that as absence
is the same error as `INV-HW-2`'s declared throughput.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .evidence import SourceSpan

SCHEMA_VERSION = 1
KINDS = ("directory", "file", "symbol", "section", "entity", "document")
RELATIONS = ("contains", "imports", "references", "defines", "supersedes", "tests")
STRATEGIES = ("incremental_on_change", "periodic_rebuild", "on_demand")

# INV-EVID-3. Returned as a value, never as an empty list, so a caller cannot
# treat "found nothing" and "there is nothing" as the same result by accident.
UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class MapNode:
    """One navigable place in the corpus. Deliberately without content.

    `locator` IS WHAT MAKES AN ENTRY ACTIONABLE: retrieval follows it to fetch
    the exact span, which is why the map itself never has to carry the text.
    """

    node_id: str
    kind: str
    locator: str
    summary: str
    content_hash: str
    parent_id: str | None = None
    edges: tuple = ()
    stale: bool = False

    def to_dict(self) -> dict:
        d = {"node_id": self.node_id, "kind": self.kind,
             "locator": self.locator, "summary": self.summary,
             "content_hash": self.content_hash, "parent_id": self.parent_id,
             "edges": [{"to": t, "relation": r} for t, r in self.edges],
             "stale": self.stale}
        return d


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _one_line(text: str, kind: str, name: str) -> str:
    """A summary that says what a node is FOR, taken from the source itself.

    NOT MODEL-WRITTEN, and that is a design choice rather than a limitation.
    DF-BAG-RETRIEVE is `model_access = false`; a model-written summary would put
    model output into the navigation layer, and every subsequent decision about
    what to read would rest on it. A docstring's first line is written by whoever
    wrote the code and is already the artifact's own claim about itself.
    """
    doc = (text or "").strip()
    if doc:
        first = doc.splitlines()[0].strip()
        if first:
            return first[:200]
    return f"{kind} {name}"


class KnowledgeMap:
    """Locators, hashes and one-line summaries. No content, by contract."""

    def __init__(self, root: Path | str, *, root_ref: str = "",
                 map_id: str = "map-1",
                 strategy: str = "incremental_on_change") -> None:
        if strategy not in STRATEGIES:
            raise ValueError(f"unknown freshness strategy {strategy!r}")
        self.root = Path(root)
        self.root_ref = root_ref or str(self.root)
        self.map_id = map_id
        self.strategy = strategy
        self.nodes: dict[str, MapNode] = {}
        # NULL UNTIL MEASURED. Not 1.0, not 0.0 -- an unmeasured coverage is
        # UNMEASURED, and the retrieval path treats it as incomplete.
        self.coverage_ratio: float | None = None
        self._considered = 0

    # ------------------------------------------------------------------ build

    def build(self, subdir: str = "", *,
              suffixes: Iterable[str] = (".py", ".md", ".toml", ".json"),
              symbols: bool = True) -> "KnowledgeMap":
        base = self.root / subdir if subdir else self.root
        files = [f for f in sorted(base.rglob("*"))
                 if f.is_file() and f.suffix in tuple(suffixes)
                 and ".git" not in f.parts]
        self._considered = len(files)
        covered = 0
        for f in files:
            try:
                raw = f.read_bytes()
            except OSError:
                # COUNTED AS CONSIDERED AND NOT AS COVERED. A file that could
                # not be read is a hole in the map, and quietly skipping it
                # would report coverage the map does not have.
                continue
            rel = f.relative_to(self.root).as_posix()
            parent = self._directory(f.parent)
            self.nodes[rel] = MapNode(
                node_id=rel, kind="file", locator=rel,
                summary=_one_line(self._file_doc(f, raw), "file", f.name),
                content_hash=_hash(raw), parent_id=parent)
            covered += 1
            if symbols and f.suffix == ".py":
                self._symbols(rel, raw)
        self.coverage_ratio = (covered / self._considered) if self._considered else None
        return self

    def _directory(self, d: Path) -> str | None:
        if d == self.root or self.root not in d.parents and d != self.root:
            if d == self.root:
                return None
        try:
            rel = d.relative_to(self.root).as_posix()
        except ValueError:
            return None
        if rel in ("", "."):
            return None
        if rel not in self.nodes:
            self.nodes[rel] = MapNode(
                node_id=rel, kind="directory", locator=rel,
                summary=f"directory {d.name}",
                # A DIRECTORY'S HASH IS OF ITS LISTING, not of its contents.
                # Hashing the whole subtree would make every parent stale on any
                # descendant edit, which is true and useless: the point of the
                # flag is to say WHICH node to re-read.
                content_hash=_hash(",".join(
                    sorted(p.name for p in d.iterdir())).encode()),
                parent_id=self._directory(d.parent) if d.parent != d else None)
        return rel

    def _file_doc(self, f: Path, raw: bytes) -> str:
        if f.suffix == ".py":
            try:
                return ast.get_docstring(ast.parse(raw.decode("utf-8", "replace"))) or ""
            except SyntaxError:
                return ""
        text = raw.decode("utf-8", "replace")
        for line in text.splitlines():
            line = line.strip().lstrip("#").strip()
            if line:
                return line
        return ""

    def _symbols(self, rel: str, raw: bytes) -> None:
        try:
            tree = ast.parse(raw.decode("utf-8", "replace"))
        except SyntaxError:
            return
        text = raw.decode("utf-8", "replace")
        lines = text.splitlines(keepends=True)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef)):
                continue
            start = node.lineno - 1
            end = getattr(node, "end_lineno", node.lineno)
            body = "".join(lines[start:end]).encode()
            nid = f"{rel}::{node.name}"
            self.nodes[nid] = MapNode(
                node_id=nid, kind="symbol",
                # THE LOCATOR CARRIES THE LINE RANGE, so retrieval reads exactly
                # this symbol rather than searching the file for its name --
                # which would match every call site as readily as the definition.
                locator=f"{rel}#L{node.lineno}-{end}",
                summary=_one_line(ast.get_docstring(node) or "",
                                  type(node).__name__, node.name),
                content_hash=_hash(body), parent_id=rel,
                edges=((rel, "defines"),))

    # -------------------------------------------------------------- freshness

    def refresh(self) -> list:
        """Re-hash every locator. Returns the nodes that went stale.

        HASH, NOT AGE. `valid_until` schedules the next rebuild; it does not
        decide what is true now. A file edited one second after a rebuild would
        read as fresh for the rest of the window under a time-based rule.
        """
        gone = []
        for nid, n in list(self.nodes.items()):
            current = self._hash_of(n)
            if current != n.content_hash:
                self.nodes[nid] = MapNode(
                    node_id=n.node_id, kind=n.kind, locator=n.locator,
                    summary=n.summary, content_hash=n.content_hash,
                    parent_id=n.parent_id, edges=n.edges, stale=True)
                gone.append(self.nodes[nid])
        return gone

    def _hash_of(self, n: MapNode) -> str | None:
        path, lo, hi = self._resolve(n.locator)
        f = self.root / path
        if not f.exists():
            return None
        if n.kind == "directory":
            return _hash(",".join(sorted(p.name for p in f.iterdir())).encode())
        raw = f.read_bytes()
        if lo is None:
            return _hash(raw)
        return _hash(b"".join(raw.splitlines(keepends=True)[lo - 1:hi]))

    @staticmethod
    def _resolve(locator: str) -> tuple:
        m = re.match(r"^(.*?)#L(\d+)-(\d+)$", locator)
        if m:
            return m.group(1), int(m.group(2)), int(m.group(3))
        return locator, None, None

    # -------------------------------------------------------------- retrieval

    def retrieve(self, query: str, *, budget: int = 5) -> Any:
        """DF-BAG-RETRIEVE. Returns `spans[]` or `UNKNOWN`. Never a summary.

        THE SUMMARY RANKS AND THE LOCATOR ANSWERS. Matching against summaries is
        what makes the map worth having -- it is how a query reaches the right
        file without reading the corpus -- but the value returned is read from
        the locator and hashed at read time. A summary that reached the caller
        as evidence would be a summary-of-a-summary standing in for a retrieval,
        which `INV-EVID-2` refuses in as many words.

        A STALE NODE IS NOT SERVED. Its recorded hash no longer matches what is
        on disk, so anything read through it would be cited against a hash that
        is already wrong.
        """
        terms = [t for t in re.split(r"\W+", query.lower()) if len(t) > 2]
        if not terms:
            return UNKNOWN

        scored = []
        for n in self.nodes.values():
            if n.stale or n.kind == "directory":
                continue
            hay = f"{n.node_id} {n.summary}".lower()
            hits = sum(1 for t in terms if t in hay)
            if hits:
                scored.append((hits, n))
        scored.sort(key=lambda p: (-p[0], p[1].node_id))

        spans = []
        for _, n in scored[:budget]:
            span = self.span_for(n)
            if span is not None:
                spans.append(span)

        if not spans:
            # UNKNOWN, NOT `[]`. An empty list invites the caller to say the
            # thing does not exist. With `coverage_ratio` unmeasured the map
            # cannot even support that claim about its own corpus.
            return UNKNOWN
        return spans

    def span_for(self, n: MapNode) -> SourceSpan | None:
        """Read the node's bytes and return a citable span, or None.

        RE-HASHED AT READ TIME. The map's recorded hash says what was there when
        it was built; this says what is there now, and a citation must be
        reproducible from the source rather than from the index.
        """
        path, lo, hi = self._resolve(n.locator)
        f = self.root / path
        if not f.exists():
            return None
        raw = f.read_bytes()
        if lo is None:
            start, end, chunk = 0, len(raw), raw
        else:
            lines = raw.splitlines(keepends=True)
            start = sum(len(x) for x in lines[:lo - 1])
            chunk = b"".join(lines[lo - 1:hi])
            end = start + len(chunk)
        if _hash(chunk) != n.content_hash:
            # The node is stale and `refresh()` has not run. Refusing here means
            # a map that is merely out of date cannot produce a wrong citation.
            return None
        return SourceSpan(path=path, start=start, end=end,
                          sha256=_hash(chunk),
                          text=chunk.decode("utf-8", "replace"))

    # ------------------------------------------------------------------ serde

    def to_dict(self, *, built_at_hlc: str = "", valid_until: str = "") -> dict:
        return {
            "map_id": self.map_id,
            "schema_version": SCHEMA_VERSION,
            "root_ref": self.root_ref,
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "built_at_hlc": built_at_hlc,
            "freshness": {"strategy": self.strategy,
                          "valid_until": valid_until,
                          "coverage_ratio": self.coverage_ratio},
            # FIXED TRUE, AS THE SCHEMA FIXES THEM. A map whose retrieval
            # returns prose is a RAG pipeline with a different name.
            "retrieval_contract": {"returns_spans": True,
                                   "span_reproducible": True},
        }

    def approx_tokens(self) -> int:
        """What consulting this map costs, against what dumping the corpus would.

        AN ESTIMATE AND LABELLED ONE -- it is a character count over four, not a
        tokeniser. It exists so the comparison SR-007 is about can be made at
        all, not to be quoted as a measurement.
        """
        return len(json.dumps([n.to_dict() for n in self.nodes.values()])) // 4
