"""The cache tiers SR-054 names, built on the one that already exists.

FIVE TIERS ARE SPECIFIED AND ONE WAS BUILT. `core/taint.py`'s `TaintedCache` is
the fifth of them in spirit -- it stores a wrapper rather than a string, so a
value goes in tainted and cannot come out looking like clean local data. That
property is not optional at any tier, and it is why this module composes with it
rather than beside it: a second cache that stored bare strings would launder
trust on every hit, which is `A-025.8` exactly.

WHAT EACH TIER SAVES, because they are not degrees of one thing:

    FILE HASH     re-reading a file that has not changed. Keyed on content, not
                  on path or mtime -- a file copied or checked out gets a fresh
                  mtime and identical bytes, and keying on mtime would miss
                  every hit that matters while catching none that do.
    CHUNK         re-splitting a document that has not changed. Keyed on the
                  file hash plus the chunking parameters, because the same file
                  chunked differently is a different result.
    SUMMARY       re-summarising the same content for the same purpose. Keyed on
                  content AND purpose: a summary written for the compactor is
                  not the summary the miss recorder wanted.
    PROMPT PREFIX the provider-side discount. NOT stored here -- it is bytes on
                  the wire, and what this tier holds is the KEY that tells us
                  whether the prefix we are about to send is the one we sent
                  last time. Measured 2026-08-29: Groq does not cache at all,
                  and a repeated prefix cost full freight on fourteen attempts.
    EMBEDDING     specified, and DELIBERATELY NOT BUILT. Nothing in this system
                  produces an embedding: `MEMORY_ARCHITECTURE` rules out a vector
                  store, selection is FTS5 plus a bounded graph walk, and local
                  models are ruled out on this host. A cache for values nothing
                  computes would be a tier that could never register a hit, and
                  counting it as "built" would make the five look complete.

EVERY TIER IS CONTENT-ADDRESSED AND NONE IS TIME-ADDRESSED. A cache keyed on
when something was fetched has to guess how long the answer stays true; a cache
keyed on what the content IS cannot be stale, because different content is a
different key. `INV-COORD-4` says the wall clock never orders or supersedes, and
that reasoning does not stop at the memory layer.

HITS AND MISSES ARE COUNTED PER TIER. A cache nobody measures is a cache nobody
can tell is working, and the failure is silent in the expensive direction: a
tier that never hits costs exactly what having no cache costs, plus the code.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from .capability import LEVEL_RANK
from .taint import ALLOWED_LEVEL, EXTERNAL, Tainted, TaintedCache

FILE_HASH = "file_hash"
CHUNK = "chunk"
SUMMARY = "summary"
PROMPT_PREFIX = "prompt_prefix"
# Named so the gap is visible in the code rather than only in a document.
EMBEDDING_NOT_BUILT = "embedding"

TIERS = (FILE_HASH, CHUNK, SUMMARY, PROMPT_PREFIX)


def content_key(*parts: Any) -> str:
    """A key from what the content IS. Never from when it was seen.

    Parts are joined with a separator that cannot appear in a hex digest, so
    `("ab", "cd")` and `("abc", "d")` cannot collide -- the classic
    concatenation bug, and one that would silently serve one file's chunks for
    another.
    """
    h = hashlib.sha256()
    for p in parts:
        h.update(b"\x00")
        h.update(str(p).encode("utf-8"))
    return h.hexdigest()


REUSE = "REUSE"
REFETCH = "REFETCH"
REFUSE = "REFUSE"


@dataclass(frozen=True, slots=True)
class RequestingContext:
    """WHO is asking, in the only two terms the invariants are written in.

    `required_level` is the level of the state-changing capability this value
    will feed -- `INV-AUTH-3` caps external content at L1 for exactly those, and
    a read that drives nothing is L1 by construction. `planner` is separate and
    absolute: `INV-AUTH-6` says the planner context never contains external
    content at any level, so it is not a level comparison and cannot be folded
    into one.
    """

    required_level: str = "L1"
    planner: bool = False
    label: str = ""


@dataclass(frozen=True, slots=True)
class AdmitDecision:
    verdict: str
    reason: str

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "reason": self.reason}


def admit(entry: Tainted | None, context: RequestingContext) -> AdmitDecision:
    """DF-CACHE-ADMIT: REUSE | REFETCH | REFUSE.

    REFETCH IS NOT THE POLITE VERSION OF REFUSE, and the naive implementation
    makes it exactly that -- returning REFETCH for every entry it will not
    serve, because "go get it again" sounds like the recoverable answer. IT IS
    AN INFINITE LOOP HERE. Every key in this module is content-addressed: the
    key IS the hash of the content, so a refetch of the same key returns the
    same bytes, the same derivation and therefore the SAME trust class. An entry
    refused for its trust class will be refused identically after the refetch,
    and the caller that believed REFETCH was progress fetches forever.

    So REFETCH is reserved for the one case where fetching again genuinely
    changes the answer: PROVENANCE THAT IS ABSENT OR UNRECOGNISED. There the
    refetch is what establishes the trust class rather than what re-derives it.
    Everything else is REUSE or REFUSE.
    """
    if entry is None:
        return AdmitDecision(REFETCH, "no entry: nothing to reuse")

    tc = entry.trust_class
    if tc not in ALLOWED_LEVEL:
        # The event envelope's rule, applied here: absent or unrecognised
        # provenance is treated as external. A refetch is the one action that
        # can replace a guess with a known class, so this is the honest REFETCH.
        return AdmitDecision(
            REFETCH,
            f"trust class {tc!r} is unrecognised, so provenance is unknown; a "
            "refetch establishes it rather than re-deriving it")

    if context.planner and tc == EXTERNAL:
        # INV-AUTH-6 is absolute and is NOT a level comparison, so it is checked
        # before the level rule -- an external entry needed at L1 passes the
        # level test and must still never reach the planner.
        return AdmitDecision(
            REFUSE,
            "INV-AUTH-6: the planner context never contains retrieved_external. "
            "Refetching returns the same external content, so REFETCH here "
            "would loop; the extraction context is the route, not the cache")

    ceiling = ALLOWED_LEVEL[tc]
    if LEVEL_RANK.get(ceiling, 0) < LEVEL_RANK.get(context.required_level, 0):
        return AdmitDecision(
            REFUSE,
            f"trust class {tc!r} ceilings at {ceiling} and the caller needs "
            f"{context.required_level}. The key is content-addressed, so a "
            "refetch returns the same class and REFETCH would loop")

    return AdmitDecision(REUSE, f"{tc!r} admissible at {context.required_level}")


@dataclass
class TierStats:
    hits: int = 0
    misses: int = 0
    refused: int = 0

    @property
    def ratio(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total) if total else 0.0

    def to_dict(self) -> dict:
        return {"hits": self.hits, "misses": self.misses,
                "refused": self.refused, "ratio": round(self.ratio, 3)}


class TieredCache:
    """The four buildable tiers, each taint-preserving and content-addressed."""

    def __init__(self, *, bus: Any = None) -> None:
        self._bus = bus
        self._lock = threading.RLock()
        self._stores: dict = {t: TaintedCache() for t in TIERS}
        self.stats: dict = {t: TierStats() for t in TIERS}
        self._last_refusal: dict = {}

    # ------------------------------------------------------------------ core

    def get(self, tier: str, key: str,
            context: RequestingContext) -> Tainted | None:
        """A hit is not automatically a reuse. DF-CACHE-ADMIT decides.

        `context` IS REQUIRED AND HAS NO DEFAULT. A default would be a guess at
        what the caller may see, applied silently at every call site that did
        not think about it -- and the permissive guess is the one that gets
        written, because the strict one breaks callers. Making it explicit costs
        one argument and is the difference between a cache that enforces
        `INV-AUTH-6` and one that documents it.
        """
        self._require(tier)
        hit = self._stores[tier].get(key)
        decision = admit(hit, context)
        with self._lock:
            s = self.stats[tier]
            if decision.verdict == REUSE:
                s.hits += 1
            else:
                s.misses += 1
                if hit is not None:
                    # A refused hit is NOT a miss in the ordinary sense: the
                    # entry was there and policy declined it. Counting it only
                    # as a miss would read as a cold cache and send someone
                    # tuning key construction that is working correctly.
                    s.refused += 1
                    self._last_refusal[tier] = decision
        return hit if decision.verdict == REUSE else None

    def put(self, tier: str, key: str, value: Tainted) -> None:
        """Stores a `Tainted`, never a bare value.

        THE TYPE IS THE GUARD. `TaintedCache.put` raises on a bare string, so
        this cannot quietly become a cache that launders trust -- and it is
        raised rather than coerced, because a wrapper invented at the cache
        boundary would carry whatever trust class the caller guessed.
        """
        self._require(tier)
        self._stores[tier].put(key, value)

    def memoise(self, tier: str, key: str, produce: Callable[[], Tainted],
                context: RequestingContext) -> Tainted:
        """Return the cached value, or produce and store it.

        `produce` RETURNS A `Tainted`, and that is the contract rather than a
        convenience: the trust class belongs to whoever computed the value and
        cannot be reconstructed here.
        """
        hit = self.get(tier, key, context)
        if hit is not None:
            return hit
        value = produce()
        # THE PRODUCED VALUE IS ADMITTED TOO, and it is tempting not to bother:
        # it is fresh, so it "must" be fine. It need not be -- `produce` may
        # return external content, and returning it here because it did not come
        # from the cache would route around the decision on the one path that
        # looks safest.
        verdict = admit(value, context)
        if verdict.verdict != REUSE:
            raise PermissionError(
                f"the produced value is not admissible here: {verdict.reason}")
        self.put(tier, key, value)
        return value

    # -------------------------------------------------------------- the tiers

    def file_key(self, data: bytes) -> str:
        """Keyed on CONTENT. A file copied or checked out has a new mtime and
        the same bytes; keying on mtime would miss every hit worth having."""
        return content_key(FILE_HASH, hashlib.sha256(data).hexdigest())

    def chunk_key(self, file_hash: str, size: int, overlap: int) -> str:
        """The same file chunked differently is a different result, so the
        chunking parameters are part of the key and not context around it."""
        return content_key(CHUNK, file_hash, size, overlap)

    def summary_key(self, content: str, purpose: str) -> str:
        """PURPOSE IS PART OF THE KEY. A summary written for the compactor is
        not the summary the miss recorder asked for, and serving one for the
        other is a hit that returns the wrong answer -- worse than a miss."""
        return content_key(SUMMARY, hashlib.sha256(content.encode()).hexdigest(),
                           purpose)

    def prefix_key(self, system: str, block_a: str) -> str:
        """Identifies the prefix we are ABOUT to send, not its content.

        This tier stores no text. The provider's discount is prefix-keyed on
        bytes at their end; what is useful here is knowing whether the prefix
        changed, because a block A that varies per turn costs full freight
        while looking identical. Measured 2026-08-29: Groq does not cache at
        all, so a hit here is information and not a saving.
        """
        return content_key(PROMPT_PREFIX,
                           hashlib.sha256((system + block_a).encode()).hexdigest())

    # ------------------------------------------------------------------ report

    def report(self) -> dict:
        with self._lock:
            out = {t: self.stats[t].to_dict() for t in TIERS}
        out["embedding"] = {"built": False,
                            "why": ("nothing in this system produces an "
                                    "embedding: no vector store by design, "
                                    "selection is FTS5 plus a bounded graph "
                                    "walk, and local models are ruled out on "
                                    "this host")}
        return out

    @staticmethod
    def _require(tier: str) -> None:
        if tier not in TIERS:
            raise ValueError(
                f"unknown cache tier {tier!r}. Known: {TIERS}. "
                f"{EMBEDDING_NOT_BUILT!r} is specified and deliberately not "
                "built -- a cache for values nothing computes could never "
                "register a hit, and pretending otherwise would make the five "
                "tiers look complete.")
