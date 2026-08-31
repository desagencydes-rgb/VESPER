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
import json
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
class SpanVerdict:
    """Whether a span re-reads, AND why not when it does not.

    `verify() -> bool` was enough while every span was a file: the reason was
    always "those bytes changed". With two backing stores the reasons diverge --
    a fabricated sequence number, a citation into the wrong store, a record that
    exists and does not say what was quoted -- and collapsing them to False
    reports a citation problem as a byte problem.
    """

    ok: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class EvidenceResolver:
    """What a span needs to re-read itself. Each span asks for its own half.

    THE ALTERNATIVE WAS AN `isinstance` LADDER IN `ClaimChecker`, which works
    for two span types and rots on the third -- and `SpanIndex` promises that a
    real retriever "slots in behind the same interface", which a type switch in
    the checker quietly revokes. Here the checker calls one method and the span
    decides what it needs.

    `store` IS OPTIONAL AND ITS ABSENCE IS A REFUSAL, NOT A PASS. A resolver
    built with a filesystem root alone cannot resolve a log receipt, and the
    tempting behaviour -- skip what cannot be checked -- would make every
    memory-derived citation verify by default in exactly the configuration that
    cannot check it.
    """

    root: Path
    store: Any = None

    @classmethod
    def of(cls, x: "EvidenceResolver | Path | str") -> "EvidenceResolver":
        """Accept a bare root for the file-only callers that predate this type.

        Safe precisely because `LogReceipt` refuses a store-less resolver: a
        receipt handed a bare path fails loudly instead of passing silently.
        """
        return x if isinstance(x, cls) else cls(Path(x))


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

    def resolve(self, resolver: "EvidenceResolver | Path") -> SpanVerdict:
        """Re-read the bytes and confirm they are still what was cited."""
        r = EvidenceResolver.of(resolver)
        f = r.root / self.path
        if not f.exists():
            return SpanVerdict(False, f"{self.path} no longer exists")
        raw = f.read_bytes()[self.start:self.end]
        if hashlib.sha256(raw).hexdigest() != self.sha256:
            return SpanVerdict(
                False, f"{self.path}:{self.start}-{self.end} no longer hashes "
                       "to what was cited")
        return SpanVerdict(True)

    def verify(self, resolver: "EvidenceResolver | Path") -> bool:
        return self.resolve(resolver).ok

    def cite(self) -> str:
        return f"{self.path}:{self.start}-{self.end}"

    def to_dict(self) -> dict:
        return {"path": self.path, "start": self.start, "end": self.end,
                "sha256": self.sha256, "bytes": self.end - self.start}


@dataclass(frozen=True, slots=True)
class LogReceipt:
    """A citation into L3: the span type an L2 fact can actually produce.

    THE GAP THIS CLOSES was recorded in `core/arbiter.py` rather than worked
    around: `SourceSpan` is a byte range in a file, an L2 fact's provenance is a
    log SEQUENCE in SQLite, and manufacturing a path from a seq would yield a
    citation that looks resolvable and is not -- worse than none, and precisely
    what `INV-EVID-2` refuses. `Claim.supported()` was therefore False for every
    memory-derived claim, so the arbiter could pick a winner and not cite it.

    `quoted` IS THE FIELD THAT MAKES THIS MORE THAN A HASH, and omitting it is
    the easy mistake. A receipt asserting only "record 412 exists and its body
    hashes to X" verifies perfectly while the claim built on it misquotes the
    record -- which is the failure this module's own header names: a mostly
    grounded answer carrying ONE unsupported specific. So the quoted text must
    be FOUND in the resolved record, not merely accompanied by it.

    WHAT VERIFICATION ACTUALLY CATCHES DEPENDS ON THE STORE, and the honest
    accounting matters because otherwise a case is written that can never fire.
    `log`, `audit` and `tombstones` are append-only at the storage layer --
    UPDATE and DELETE are refused by trigger -- so a body there cannot change
    under a correct citation and the hash comparison is a belt on a fastened
    seatbelt. What the hash defends against there is a WRONGLY BUILT receipt,
    and what genuinely fires is a FABRICATED seq, a seq pointing into the wrong
    store or kind, and quoted text that is not in the record. In `state` and
    `workspace`, which are mutable, the hash does its ordinary work.
    """

    store: str
    seq: int
    kind: str
    sha256: str
    quoted: str
    text: str = ""

    # `Claim.to_dict` and the checker's messages read `path`; a receipt names
    # its store and sequence in the same slot so neither has to branch on type.
    @property
    def path(self) -> str:
        return f"{self.store}#{self.seq}"

    @staticmethod
    def body_hash(body: dict) -> str:
        """Hash the CANONICAL rendering, the same one `StoreSet.append` stores.

        Any other rendering makes the receipt un-reproducible for a reason that
        has nothing to do with the record: dict ordering.
        """
        return hashlib.sha256(
            json.dumps(body, sort_keys=True).encode()).hexdigest()

    @classmethod
    def of(cls, store: str, record: Any, quoted: str) -> "LogReceipt":
        return cls(store=store, seq=int(record.seq), kind=record.kind,
                   sha256=cls.body_hash(record.body), quoted=quoted,
                   text=json.dumps(record.body, sort_keys=True)[:400])

    def resolve(self, resolver: "EvidenceResolver | Path") -> SpanVerdict:
        r = EvidenceResolver.of(resolver)
        if r.store is None:
            # NOT A SKIP. A resolver that cannot reach L3 cannot confirm this
            # citation, and treating unverifiable as verified would make every
            # memory-derived claim pass in exactly the configuration unable to
            # check it. UNKNOWN is UNAVAILABLE here as everywhere else.
            return SpanVerdict(
                False, "no L3 store on the resolver, so this receipt cannot be "
                       "re-read; unverifiable is not verified")
        rec = r.store.record(self.store, self.seq)
        if rec is None:
            return SpanVerdict(
                False, f"{self.store}#{self.seq} does not exist: a sequence "
                       "number is a plausible integer whether or not a record "
                       "was ever written at it")
        if rec.kind != self.kind:
            return SpanVerdict(
                False, f"{self.store}#{self.seq} is {rec.kind!r}, not "
                       f"{self.kind!r} -- the citation resolves to a different "
                       "record than the one it names")
        if self.body_hash(rec.body) != self.sha256:
            return SpanVerdict(
                False, f"{self.store}#{self.seq} no longer hashes to what was "
                       "cited")
        if not _contains(rec.body, self.quoted):
            return SpanVerdict(
                False, f"{self.quoted!r} does not appear in {self.store}#"
                       f"{self.seq}. The record is real and does not say this: "
                       "one unsupported specific inside an otherwise grounded "
                       "answer is the case a hash-only receipt waves through.")
        return SpanVerdict(True)

    def verify(self, resolver: "EvidenceResolver | Path") -> bool:
        return self.resolve(resolver).ok

    def cite(self) -> str:
        return f"{self.store}#{self.seq}"

    def to_dict(self) -> dict:
        return {"path": self.path, "store": self.store, "seq": self.seq,
                "kind": self.kind, "sha256": self.sha256,
                "quoted": self.quoted}


def _contains(body: Any, needle: str) -> bool:
    """Is `needle` present in any leaf of the record body?

    Walks nested values rather than matching the rendered JSON, so a quote can
    never be satisfied by a KEY NAME or by punctuation the renderer inserted
    between two unrelated fields.
    """
    if needle == "":
        return False
    if isinstance(body, dict):
        return any(_contains(v, needle) for v in body.values())
    if isinstance(body, (list, tuple)):
        return any(_contains(v, needle) for v in body)
    return needle in str(body)


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

    def __init__(self, bus: EventBus, root: Path, store: Any = None) -> None:
        self._bus = bus
        self._root = Path(root)
        # One resolver, built once. Each span asks it for the half it needs.
        self._resolver = EvidenceResolver(Path(root), store)
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
                v = sp.resolve(self._resolver)
                if not v.ok:
                    reasons.append(
                        f"span {sp.cite()} does not re-read: {v.reason} -- a "
                        "citation that cannot be reproduced is not grounding "
                        "(INV-EVID-2)")
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
