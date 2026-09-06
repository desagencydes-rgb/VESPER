"""Credential detection and redaction — deterministic, and never a model.

WHY A MODEL MAY NOT DO THIS, and it is not cost. Sending the text to a model to
ask whether it contains a secret IS the leak. The request has been made, the
bytes have been transmitted, and the provider's logs hold them whatever the
answer comes back as. `MEMORY_ARCHITECTURE.md` states it flatly -- "running it
is the leak" -- and a model may be a SECOND pass, over text a deterministic
first pass has already cleared. Never the first.

"MAKE THE MODEL FORGET IT" IS NOT AVAILABLE. There is no recall. A credential
inside an outbound request is sent and logged the instant it goes, and every
mitigation after that point is theatre. This is why the guard sits before the
pipe rather than anywhere convenient.

ONE DETECTOR, TWO CALLERS, and this is the same shape the sensor layer takes
with the verifier -- `source -> probe` and `fact -> probe` share one registry
rather than growing two. Here:

    CAPTURE  the updater refuses credential-shaped material before it is ever
             written to memory, and keeps a tombstone instead
    EGRESS   the redactor clears every request leaving this machine

`MEMORY_ARCHITECTURE.md` is explicit that the second is an EGRESS component and
not a provider component: git history is effectively permanent, a force-push
does not remove a secret from clones, forks or unreachable objects, so the
GitHub backup and node sync are boundaries exactly as much as a provider is.
Two implementations would drift, and the one that drifted would be the one
nobody was watching.

A FINDING NEVER CARRIES THE VALUE IT FOUND. This is the whole discipline of the
tombstone rule and it is easy to violate by accident, because a detector that
reports what it matched is far easier to debug. `MEMORY_ARCHITECTURE.md`: a
quarantine holding every credential VESPER has ever seen is a more attractive
target than the vault -- it is the one place they are all gathered, and it was
built to be the low-security bin. So `Finding` holds an offset, a length, a
pattern name and an entropy score, and there is deliberately no field the value
could be put in.

PATTERNS ARE THE FLOOR, ENTROPY IS THE NET. A pattern list alone only ever
catches the shapes someone thought of, and every provider invents a new prefix.
Entropy alone flags hashes, UUIDs and base64 payloads in ordinary text. So a
literal pattern match is reported on its own authority, and an unrecognised
token must ALSO clear a length floor, a charset-mix test and the benign-shape
list before it counts.

THIS MODULE ENFORCES `INV-PRIV-7`, RATIFIED BY THE OWNER 2026-08-31. For the
day before that it enforced nothing formally, and that is worth keeping: checked
against all 139 invariants on 2026-08-30, NOTHING said a credential may not reach
a provider, and the handwritten source never mentions credentials at all. So the
guard was built, wired and gated while claiming no coverage -- the check ran and
was deliberately left out of `CHECKS.toml`, because registering it meant
declaring an invariant that did not exist, and inventing one to close my own gap
is the manufactured claim `ci-registry` refuses.

`INV-PRIV-6` remains the nearest rule and a DIFFERENT guard at the same point: it
matches a provider's egress class against the content's privacy class, while this
removes credentials REGARDLESS of both, because an E1_PRIVATE provider must not
receive a key either.

A MODEL MAY NOT PERFORM THE DETECTION -- NOT AS A FIRST PASS, AND NOT AS A
SECOND. `MEMORY_ARCHITECTURE.md` says "a model may be a second pass; never the
first", and that line is WRONG, superseded by the owner 2026-08-31: a second pass
adds value only by catching what the deterministic pass MISSED, and catching it
means transmitting it -- so it leaks precisely what it exists to find. If the
first pass were perfect the second would be unnecessary; since it is not, the
second is self-defeating. The only coherent model pass is over ALREADY-REDACTED
text, checking for OVER-redaction, which sees no secrets by construction and is
not detection.

The under-claim is the safe direction: the guard runs, and nothing reports
coverage it does not have.

THE TWO CALLERS WANT DIFFERENT ERROR DIRECTIONS, and pretending otherwise is
how one of them ends up wrong. Capture should refuse generously: an over-refusal
is a retrievable inconvenience in the quarantine, an under-refusal is a
permanent record of something that should never have been written. Egress cannot
be equally generous -- over-redaction there corrupts the request the owner
actually asked for. `scan()` therefore takes a `generous` flag rather than
baking one caller's asymmetry into both.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

# Literal shapes, reported on their own authority. Each is anchored on a prefix
# a vendor actually issues, so a match is evidence rather than a guess.
PATTERNS: tuple = (
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b")),
    ("openai_style_key", re.compile(r"\bsk-(?:proj-|ant-|or-)?[A-Za-z0-9_-]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[0-9A-Za-z-]{10,}\b")),
    ("private_key_block", re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("bearer_header", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}={0,2}")),
    # `NAME=value` where the name says what it is. The name is the evidence,
    # which is why this one does not need the value to look like anything.
    ("named_secret_assignment", re.compile(
        r"\b[A-Za-z0-9_]*(?:API_?KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL)"
        r"[A-Za-z0-9_]*\s*[:=]\s*[\"']?([^\s\"';]{8,})", re.IGNORECASE)),
)

# Shapes that score high on entropy and are not secrets. Checked BEFORE the
# entropy net, because each of these appears in ordinary VESPER text -- an HLC
# string is in every record this system writes, and flagging it would make the
# detector fire on its own audit trail.
BENIGN: tuple = (
    re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),  # uuid
    re.compile(r"^[0-9a-f]{32}$"), re.compile(r"^[0-9a-f]{40}$"),
    re.compile(r"^[0-9a-f]{64}$"),                                   # md5/sha1/sha256
    re.compile(r"^hlc:[0-9]+:[0-9]+(?::.+)?$"),                      # this system's own clock
    re.compile(r"^[0-9]+(?:\.[0-9]+)*$"),                            # versions, numbers
    re.compile(r"^(?:https?|file)://\S+$"),
    # PATHS, AND THIS ONE IS A DELIBERATE TRADE rather than an oversight.
    # `docs/planning/MEMORY_ARCHITECTURE.md` clears the length floor and mixes
    # case, so the entropy net flagged it -- and VESPER's memory is going to be
    # full of repository paths. A redactor that corrupts every path in every
    # request is not a redactor anyone can leave switched on, and the failure
    # would present as VESPER talking nonsense about its own files rather than
    # as a security control doing its job.
    #
    # WHAT THIS GIVES UP, stated rather than discovered later: a base64 blob
    # drawn only from [A-Za-z0-9_.-] and `/` can wear this shape. It is not a
    # hole in the floor -- the prefix patterns and `named_secret_assignment`
    # are what catch real credentials, and both run before the net and neither
    # consults this list. The net exists for unrecognised shapes, and this
    # narrows the net, not the floor.
    re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+$"),           # a/b/c.ext
    re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9]{1,8}$"),               # file.ext
)

# An unrecognised token must clear all three before entropy is consulted at all.
MIN_TOKEN_LEN = 20
MIN_ENTROPY_BITS = 3.6          # per character, Shannon over the token
MIN_ENTROPY_BITS_GENEROUS = 3.0

REDACTION = "[REDACTED:{kind}]"


@dataclass(frozen=True, slots=True)
class Finding:
    """WHAT was found and WHERE -- deliberately never the value itself.

    There is no `value` field and adding one is the defect this class exists to
    prevent: the tombstone must be enough to audit the detector and useless to
    anyone who steals the store it lives in.
    """

    kind: str
    start: int
    end: int
    entropy: float
    source: str = "unknown"

    @property
    def length(self) -> int:
        return self.end - self.start

    def to_dict(self) -> dict:
        return {"kind": self.kind, "start": self.start, "end": self.end,
                "length": self.length, "entropy": round(self.entropy, 2),
                "source": self.source}


def shannon_bits(s: str) -> float:
    """Bits of entropy per character. 0.0 for the empty string, not an error."""
    if not s:
        return 0.0
    counts: dict = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _charset_mixed(tok: str) -> bool:
    """Does the token mix classes the way a generated key does?

    A long lowercase word and a long hex digest both score respectably on
    entropy and neither is a credential. Requiring two of three classes is what
    separates `supercalifragilistic` from `k3Jx9_QmZ2vLp0aB`.
    """
    classes = sum((any(c.islower() for c in tok), any(c.isupper() for c in tok),
                   any(c.isdigit() for c in tok)))
    return classes >= 2


def _path_segments(tok: str) -> list | None:
    """The segments of a path-shaped token, or None if it is not one.

    ONLY FOR THINGS SHAPED LIKE PATHS, and that narrowness is deliberate: a
    secret can contain `/`, so this does not relax the rule for tokens
    generally -- only for ones that BEGIN like a path, where the leading `/`,
    `./`, `../` or `~/` is evidence no API key format produces.
    """
    if not tok.startswith(("/", "./", "../", "~/")):
        return None
    segments = [s for s in tok.split("/") if s]
    return segments or None


def _worst_segment(tok: str) -> str:
    """The part of a path-shaped token that decides, or the token itself.

    THE SAME PART MUST DECIDE BOTH TESTS, AND IT DID NOT. `_token_bits` was
    already narrowed to score a path per SEGMENT -- because joining several
    ordinary words varies the character distribution and pushes an innocent
    path over the floor. `_charset_mixed` was left reading the WHOLE token, so
    a path went on mixing classes the same accidental way: `~/Downloads/x.txt`
    has an uppercase `D` from one segment and lowercase from another and passes
    a test that is supposed to mean "this looks generated".

    WHAT IT COST, TWICE. Measured 2026-09-06: the owner asked VESPER to write
    `~/Downloads/vesper_changes_demo.txt`. `vesper_changes_demo.txt` is all
    lowercase and would have been skipped on its own; joined to `Downloads` it
    read as mixed, its entropy was 3.92 against a 3.6 floor, and the redactor
    rewrote the owner's own path to `[REDACTED:high_entropy_token]` before the
    model ever saw it. VESPER then created a file literally named
    `~[REDACTED:high_entropy_token]` inside its own app bundle. Every stage
    after the redactor behaved correctly on input the redactor had corrupted --
    the same sentence the 2026-09-04 note above had to write.

    A REAL SECRET INSIDE A PATH IS STILL CAUGHT, because it is the worst
    segment: it carries both the entropy and the mixed charset, and both tests
    now ask that one segment rather than asking the join.
    """
    segments = _path_segments(tok)
    if not segments:
        return tok
    return max(segments, key=shannon_bits)


def _token_bits(tok: str) -> float:
    """Entropy for the redaction decision, judged per path SEGMENT.

    A FILESYSTEM PATH IS NOT A SECRET, AND IT SCORED LIKE ONE. The scan's
    charset includes `/`, `.`, `-` and `_`, so an absolute path matches as a
    single token -- and a four-segment home path carries 4.06 bits against a
    3.6 floor purely because joining several ordinary words varies the
    character distribution. Every segment of it is far below the floor: 1.92,
    2.52, 2.52, 3.10.

    WHAT IT COST. Measured 2026-09-04: the owner asked VESPER to run a script,
    the proposer correctly emitted `shell.run python3 "<path>/hey.py"`, and the
    redactor rewrote the path to `[REDACTED:high_entropy_token]`. The mangled
    command then scored L5 instead of L3 -- fail-closed on an unparseable
    token, which is right -- and L5 was above the ceiling for a later step of a
    turn, so the action was refused as `weak_authorization`. The owner was told
    VESPER needed permission it could not even ask for. Every stage after the
    redactor behaved correctly on input the redactor had corrupted.

    ONLY FOR THINGS SHAPED LIKE PATHS, and that narrowness is deliberate. A
    secret can contain `/`, so this does not relax the rule for tokens
    generally -- only for ones that BEGIN like a path, where the leading `/`,
    `./`, `../` or `~/` is evidence no API key format produces. Within those,
    the score is the WORST segment, so a real secret sitting inside a path is
    still caught by the segment that holds it.
    """
    return shannon_bits(_worst_segment(tok))


def _is_benign(tok: str) -> bool:
    return any(p.match(tok) for p in BENIGN)


def scan(text: str, *, generous: bool = False, source: str = "unknown") -> list:
    """Every credential-shaped span in `text`. Deterministic, no model, no I/O.

    `generous=True` is the CAPTURE setting: it lowers the entropy floor, because
    an over-refusal there lands in a quarantine the owner can release from,
    while an under-refusal is permanent. Egress uses the default, where an
    over-redaction corrupts the request the owner actually asked for.
    """
    findings: list = []
    claimed: list = []

    for kind, pat in PATTERNS:
        for m in pat.finditer(text):
            # Group 1 where the pattern defines one (the assignment case, whose
            # evidence is the NAME but whose secret is the VALUE), else the
            # whole match.
            start, end = (m.span(1) if m.re.groups else m.span())
            findings.append(Finding(kind=kind, start=start, end=end,
                                    entropy=shannon_bits(text[start:end]),
                                    source=source))
            claimed.append((start, end))

    floor = MIN_ENTROPY_BITS_GENEROUS if generous else MIN_ENTROPY_BITS
    for m in re.finditer(r"[A-Za-z0-9_\-+/=\.]{%d,}" % MIN_TOKEN_LEN, text):
        start, end = m.span()
        if any(start < c_end and c_start < end for c_start, c_end in claimed):
            continue                      # a pattern already owns this span
        tok = m.group()
        # BOTH TESTS ASK THE SAME SEGMENT. Asking `_charset_mixed` about the
        # whole token while `_token_bits` asks about one segment is how a path
        # kept passing the "this looks generated" test on evidence that came
        # from the join rather than from any part of it. See `_worst_segment`.
        if _is_benign(tok) or not _charset_mixed(_worst_segment(tok)):
            continue
        bits = _token_bits(tok)
        if bits >= floor:
            findings.append(Finding(kind="high_entropy_token", start=start,
                                    end=end, entropy=bits, source=source))

    findings.sort(key=lambda f: f.start)
    return findings


def redact(text: str, *, generous: bool = False, source: str = "unknown") -> tuple:
    """`(clean_text, findings)`. The only text that may cross a boundary.

    Replaces from the end backwards so earlier offsets stay valid -- replacing
    forwards shifts every span after the first substitution, and the resulting
    corruption looks like a detector miss rather than like an indexing bug.
    """
    findings = scan(text, generous=generous, source=source)
    out = text
    for f in sorted(findings, key=lambda f: f.start, reverse=True):
        out = out[:f.start] + REDACTION.format(kind=f.kind) + out[f.end:]
    return out, findings


def clean(text: str, *, generous: bool = False) -> bool:
    """True when nothing credential-shaped is present."""
    return not scan(text, generous=generous)
