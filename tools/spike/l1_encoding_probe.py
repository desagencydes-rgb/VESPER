#!/usr/bin/env python3.13
"""What does the resident block actually cost, per encoding and per provider?

THE QUESTION. Every fact in the resident block has to carry rank, source, time,
privacy class and a pointer back to the archive -- the invariants require all
five. That metadata competes directly with the pressure to be small, and if it
costs more than the compression it enables, the resident block has no reason to
exist. Nobody has counted it.

THE THREE ENCODINGS COMPARED. Bare (the fact alone, provenance discarded -- not
a candidate, it violates the evidence rule, but it is the floor everything else
is measured against). JSON. And the typed-line form the design proposes.

WHY THE NUMBERS HERE ARE ESTIMATES AND SAY SO. Token counts are derived from
characters using ratios MEASURED on 2026-08-28 against each provider (Groq
3.18 chars/token, Mistral 2.42 on identical bytes -- a 31% spread). Those
ratios came from graph-shaped text, which is what is being encoded here, so
they transfer better than a generic 4.0 would. They are still ratios, not a
tokenizer: treat every figure as +/- a few per cent, and confirm the chosen
encoding with one real call per rung before anything depends on the exact
number. The COMPARISON between encodings is robust even where the absolute
figure is not, because all three are measured the same way.
"""
from __future__ import annotations

import json
import pathlib
import random

# MEASURED 2026-08-28, graph-shaped text, same 8,800 bytes to each provider.
# Not published figures -- these came off `prompt_tokens` in live responses.
CHARS_PER_TOKEN = {"groq": 3.18, "mistral": 2.42, "ollama": 3.18}

N_FACTS = 200
ROOT = pathlib.Path(__file__).resolve().parents[2]


def facts(n: int, rng: random.Random) -> list[dict]:
    subs = ["owner", "node1", "node2", "vesper", "router", "alarm", "macbook",
            "project_home", "project_island", "kali", "groq", "mistral"]
    attrs = ["employer", "prefers", "timezone", "status", "owns", "runs",
             "measured_latency", "holds", "located", "depends_on", "budget"]
    vals = ["stretch host lifetime", "0.54 s mean", "Europe/Paris", "degraded",
            "the 09:00 alarm", "b10405", "append-only", "foreground_only",
            "file_based", "1200 ms", "measured at enrolment"]
    out = []
    for i in range(n):
        out.append({
            "s": rng.choice(subs), "a": rng.choice(attrs),
            "v": rng.choice(vals), "rank": rng.choice([2, 3, 4, 4, 5]),
            "src": rng.choice(["owner_statement", "calendar", "probe",
                               "derived"]),
            "hlc": f"{rng.randint(10**6, 10**7)}:{rng.randint(0,99)}",
            "priv": rng.choice(["private", "private", "private", "shareable"]),
            "ptr": rng.randint(1, 99_999),
        })
    return out


def enc_bare(f: dict) -> str:
    # NOT A CANDIDATE. Provenance discarded, so it cannot satisfy the rule that
    # a citation resolves to a retrievable span. It is here as the floor.
    return f"{f['s']} {f['a']} {f['v']}\n"


def enc_json(f: dict) -> str:
    return json.dumps(f, separators=(",", ":")) + "\n"


def enc_json_pretty(f: dict) -> str:
    return json.dumps(f) + "\n"


def enc_typed(f: dict) -> str:
    # The proposed form: fixed field order, no quoting, single-character rank
    # and privacy markers. Field order is fixed rather than sorted because the
    # cache is keyed on bytes -- a field that moves invalidates the prefix.
    p = "p" if f["priv"] == "private" else "s"
    return (f"{f['s']}.{f['a']}={f['v']} r{f['rank']}{p} "
            f"{f['src'][:3]} @{f['hlc']} #{f['ptr']}\n")


def enc_typed_compact(f: dict) -> str:
    # Same information, source and clock abbreviated harder. Included to show
    # where shrinking stops paying: the remaining bytes are the VALUE, and no
    # encoding removes that.
    p = "p" if f["priv"] == "private" else "s"
    return (f"{f['s']}.{f['a']}={f['v']} {f['rank']}{p}"
            f"{f['src'][0]}#{f['ptr']}\n")


ENCODINGS = [
    ("bare (no provenance - floor only)", enc_bare),
    ("JSON, compact", enc_json),
    ("JSON, readable", enc_json_pretty),
    ("typed line (proposed)", enc_typed),
    ("typed line, abbreviated", enc_typed_compact),
]


def main() -> int:
    rng = random.Random(11)
    fs = facts(N_FACTS, rng)
    rows = []
    for name, fn in ENCODINGS:
        text = "".join(fn(f) for f in fs)
        rows.append((name, len(text), len(text) / N_FACTS))

    floor = rows[0][1]
    print(f"{N_FACTS} facts, each carrying rank / source / clock / privacy / "
          f"pointer\n")
    print(f"{'encoding':<36} {'chars':>8} {'per fact':>9} {'vs floor':>9} "
          f"{'groq tok':>9} {'mistral':>9}")
    print("-" * 84)
    for name, total, per in rows:
        g = total / CHARS_PER_TOKEN["groq"]
        m = total / CHARS_PER_TOKEN["mistral"]
        print(f"{name:<36} {total:>8} {per:>8.1f}c {total/floor:>8.2f}x "
              f"{g:>8.0f} {m:>8.0f}")

    typed = next(t for n, t, _ in rows if n.startswith("typed line (prop"))
    jc = next(t for n, t, _ in rows if n == "JSON, compact")
    print(f"\nMETADATA OVERHEAD, the question this probe exists for:")
    print(f"  provenance costs {typed/floor:.2f}x the bare fact in the proposed"
          f" encoding")
    print(f"  JSON costs {jc/typed:.2f}x the proposed encoding for the SAME"
          f" information")

    print(f"\nWHAT A RESIDENT BLOCK COSTS, by fact count "
          f"(proposed encoding, estimated):")
    print(f"  {'facts':>7} {'chars':>9} {'groq tok':>10} {'mistral tok':>12}")
    per_fact = typed / N_FACTS
    for n in (50, 100, 200, 400, 800):
        c = per_fact * n
        print(f"  {n:>7} {c:>9.0f} {c/CHARS_PER_TOKEN['groq']:>10.0f} "
              f"{c/CHARS_PER_TOKEN['mistral']:>12.0f}")

    print(f"\nAGAINST THE MEASURED CEILINGS:")
    print(f"  Groq's whole per-minute allowance is 8,000 tokens. A resident")
    print(f"  block of 400 facts is ~{per_fact*400/CHARS_PER_TOKEN['groq']:.0f}"
          f" of that BEFORE the question or the")
    print(f"  output reservation, and it is re-spent on every cache miss.")
    print(f"  Mistral's is 250,000/min, where the same block is ~"
          f"{per_fact*400/CHARS_PER_TOKEN['mistral']/250000*100:.1f}%.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
