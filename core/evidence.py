"""Retrieval, grounding and memory authority — INV-EVID-1..3, INV-MEM-1.

THE CENTRAL CLAIM THIS FILE DEFENDS: a source reference must resolve to a
REPRODUCIBLE RETRIEVED SPAN, and a similarity score is never grounding
(INV-EVID-2, A-003.4). Those are different things and the difference is the
whole file. A vector search returns "document 7 scored 0.83" -- which says the
retriever found it relevant, not that the document says what the answer claims.
A span says: bytes 4,120-4,398 of this file, and here they are. One can be
checked by anyone; the other has to be believed.

So `SourceSpan` carries (path, byte offsets, sha256 of the exact bytes), and
`verify()` re-reads the file and compares. A span whose file changed underneath
it fails verification rather than silently citing text that no longer exists.

WHY GROUNDING IS PER-CLAIM AND NOT PER-RESPONSE. A-003.2 is the adversarial
case: a mostly-grounded answer containing ONE unsupported specific. A
per-response check passes it -- most of the response IS grounded, the average
looks fine -- and that is exactly the failure mode, because the one invented
specific is the part a reader will act on. A-003's mandatory negative control
is a per-response checker failing 3.2, and it is the evidence that claim-level
tracking was necessary rather than fastidious.

INV-EVID-3: UNKNOWN IS A RETURN VALUE, NOT AN ERROR. An empty retrieval is
never coerced into an answer. The pressure to fill a hole is exactly where
invention starts.

INV-EVID-1 / A-003.3: a `model_prior` claim is never emittable as an assertion
in a gated policy class. It may be recorded, labelled as what it is. Rank 6 of
DF-MEMORY-AUTHORITY says model prior is NEVER authoritative -- not "authoritative
when nothing else is available", which is when it would actually get used.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .bus import EventBus

UNKNOWN = "UNKNOWN"

# REM-010 4.6. A stated TOTAL order, so conflict resolution is not a judgement
# call made differently each time.
MEMORY_RANKS = {
    1: "system_rules_or_policy",
    2: "authoritative_source_of_record",
    3: "direct_observation_within_ttl",
    4: "explicit_user_statement",
    5: "derived_or_inferred",
    6: "model_prior",
}
# Rank 6 is never authoritative. Stated as a constant so the rule is one place.
NEVER_AUTHORITATIVE = 6
# When these three disagree the specified default is to ASK, not to pick.
MUST_ASK_RANKS = frozenset({2, 3, 4})

# Policy classes where an unsupported claim may not be emitted at all.
GATED_POLICY_CLASSES = ("research", "consequential_action", "world_fact",
                        "memory_write")


class Unsupported(Exception):
    """A claim reached an emission path without support. Never caught quietly."""


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """A byte-exact, re-readable region of a real file.

    Not a document id, not a chunk index, not a score. Those identify something
    the retriever liked; this identifies text that can be produced again.
    """

    path: str
    start: int
    end: int
    sha256: str
    text: str

    def verify(self, root: Path) -> bool:
        """Re-read the bytes and confirm they are still what was cited."""
        f = root / self.path
        if not f.exists():
            return False
        raw = f.read_bytes()[self.start:self.end]
        return hashlib.sha256(raw).hexdigest() == self.sha256

    def to_dict(self) -> dict:
        return {"path": self.path, "start": self.start, "end": self.end,
                "sha256": self.sha256, "bytes": self.end - self.start}


@dataclass(frozen=True, slots=True)
class Claim:
    """One assertion, with the spans that support it.

    `support` is a tuple of SourceSpan. Empty support is not a warning state --
    it is the definition of an unsupported claim, and `ClaimChecker` will not
    let it through a gated policy class.
    """

    text: str
    support: tuple = ()
    trust_class: str = "model_generated"
    memory_rank: int = 5

    def supported(self) -> bool:
        return len(self.support) > 0

    def to_dict(self) -> dict:
        return {"text": self.text, "supported": self.supported(),
                "support": [s.to_dict() for s in self.support],
                "trust_class": self.trust_class,
                "memory_rank": self.memory_rank}


class SpanIndex:
    """Retrieval that returns SPANS, never summaries-of-summaries (A-006).

    Deliberately a literal substring index over byte ranges. It is not clever
    and it is not meant to be: the property under test is that what comes back
    is byte-reproducible from the source, and a smarter retriever would make
    that property harder to see rather than more true. A real embedding
    retriever slots in behind the same interface, and must return the same
    SourceSpan type -- which is the point of pinning the type here.

    It never loads whole files into the answer. `search` reads each file once
    to locate offsets and returns only the matched windows.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._files: list[Path] = []

    def add_file(self, rel: str) -> None:
        self._files.append(self.root / rel)

    def add_tree(self, subdir: str, suffixes: Iterable[str] = (".py", ".md", ".toml")) -> None:
        base = self.root / subdir
        for f in sorted(base.rglob("*")):
            if f.is_file() and f.suffix in tuple(suffixes):
                self._files.append(f)

    def search(self, needle: str, *, window: int = 160,
               limit: int = 10) -> list[SourceSpan]:
        out: list[SourceSpan] = []
        probe = needle.encode()
        for f in self._files:
            try:
                raw = f.read_bytes()
            except OSError:
                continue
            start = 0
            while len(out) < limit:
                i = raw.find(probe, start)
                if i < 0:
                    break
                lo = max(0, i - window // 2)
                hi = min(len(raw), i + len(probe) + window // 2)
                chunk = raw[lo:hi]
                out.append(SourceSpan(
                    path=f.relative_to(self.root).as_posix(),
                    start=lo, end=hi,
                    sha256=hashlib.sha256(chunk).hexdigest(),
                    text=chunk.decode("utf-8", "replace"),
                ))
                start = i + len(probe)
            if len(out) >= limit:
                break
        return out


class ClaimChecker:
    """Per-claim grounding. The unit is the claim, never the response."""

    def __init__(self, bus: EventBus, root: Path) -> None:
        self._bus = bus
        self._root = Path(root)
        self.unsupported_claims = 0
        self.total_claims = 0

    def check(self, claims: list[Claim], *, policy_class: str,
              subject: str = "response") -> dict:
        """Returns a report. Raises only if a gated class carries an unsupported claim."""
        results = []
        bad: list[Claim] = []
        for cl in claims:
            self.total_claims += 1
            reasons = []
            if not cl.supported():
                reasons.append("no support: a claim with no retrieved span is "
                               "invented, whatever the rest of the response does")
            for sp in cl.support:
                if not sp.verify(self._root):
                    reasons.append(
                        f"span {sp.path}:{sp.start}-{sp.end} does not re-read to "
                        "its recorded hash -- a citation that cannot be "
                        "reproduced is not grounding (INV-EVID-2)")
            # INV-EVID-1 / A-003.3: model_prior is never an assertion in a
            # gated class, however confident and however well it reads.
            if cl.memory_rank == NEVER_AUTHORITATIVE and policy_class in GATED_POLICY_CLASSES:
                reasons.append(
                    f"memory_rank 6 (model_prior) is never authoritative and is "
                    f"not emittable as an assertion in policy class "
                    f"{policy_class!r} (INV-EVID-1)")
            if reasons:
                self.unsupported_claims += 1
                bad.append(cl)
            results.append({**cl.to_dict(), "problems": reasons})

        report = {
            "policy_class": policy_class,
            "claims": len(claims),
            "unsupported": len(bad),
            # A-003's release metric: tracked as a RATE, not only pass/fail,
            # because "did this response pass" hides a slow drift upward.
            "unsupported_claim_rate": (len(bad) / len(claims)) if claims else 0.0,
            "detail": results,
        }
        if bad:
            self._bus.publish("evidence.unsupported_claims", subject=subject,
                              payload=report, component="evidence")
        if bad and policy_class in GATED_POLICY_CLASSES:
            raise Unsupported(
                f"{len(bad)} of {len(claims)} claims are unsupported in gated "
                f"policy class {policy_class!r}. The offending claims are "
                "converted to questions or dropped -- never emitted. First: "
                f"{bad[0].text[:90]!r}")
        return report

    def rate(self) -> float:
        return (self.unsupported_claims / self.total_claims) if self.total_claims else 0.0


def resolve_memory_conflict(bus: EventBus, candidates: list[Claim], *,
                            subject: str) -> dict:
    """DF-MEMORY-AUTHORITY. Returns a resolution, or a question.

    THE SPECIFIED DEFAULT WHEN RANKS 2, 3 AND 4 DISAGREE IS TO ASK. Not to take
    the highest rank, not to take the most recent, not to average. REM-010 4.6
    calls this "the RB-002-compliant outcome and the specified default, not an
    implementation choice" -- so a silent pick here is a spec violation, not a
    design preference.
    """
    if not candidates:
        return {"outcome": UNKNOWN, "reason": "no candidates",
                "value": UNKNOWN}

    by_rank: dict[int, list[Claim]] = {}
    for c in candidates:
        by_rank.setdefault(c.memory_rank, []).append(c)

    disagreeing = {r for r in by_rank if r in MUST_ASK_RANKS}
    distinct_values = {c.text for c in candidates if c.memory_rank in MUST_ASK_RANKS}

    if len(disagreeing) >= 2 and len(distinct_values) > 1:
        q = {
            "outcome": "ASK",
            "reason": ("ranks " + ", ".join(str(r) for r in sorted(disagreeing))
                       + " disagree. REM-010 4.6: VESPER MUST surface the conflict "
                         "and ask. A silent pick is a spec violation, not a "
                         "design choice."),
            "candidates": [c.to_dict() for c in candidates],
            "value": UNKNOWN,
        }
        bus.publish("memory.conflict", subject=subject, payload=q,
                    component="evidence")
        return q

    best_rank = min(by_rank)
    if best_rank == NEVER_AUTHORITATIVE:
        # Only a model prior is available. That is not an answer.
        out = {"outcome": UNKNOWN, "value": UNKNOWN,
               "reason": ("only rank 6 (model_prior) is available, and rank 6 is "
                          "NEVER authoritative -- not even when it is the only "
                          "thing there, which is exactly when it would get used")}
        bus.publish("memory.unknown", subject=subject, payload=out,
                    component="evidence")
        return out

    winner = by_rank[best_rank][0]
    return {"outcome": "RESOLVED", "value": winner.text,
            "rank": best_rank, "authority": MEMORY_RANKS[best_rank],
            "reason": f"highest authority present is rank {best_rank}, "
                      f"and no rank 2/3/4 disagreement exists"}
