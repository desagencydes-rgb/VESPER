"""Properties of the host action boundary over randomised vocabularies.

WHY THIS EXISTS SEPARATELY FROM CI-056.

CI-056 reads the ONE vocabulary in the tree -- the input least likely to be
wrong, because it is reviewed. This exercises the enforcement code over the
space of vocabularies it will meet as actions are added, enabled and retired,
which is where a boundary actually erodes: not in the file that was reviewed,
but in the tenth edit to it that nobody read as carefully as the first.

THE LOAD-BEARING PROPERTY IS THE READ LINE'S DIRECTION.

`changes_host` decides whether an action needs owner authorisation. Inverted,
it asks permission for reads and grants host mutations freely. Every test that
merely checks "authorisation is consulted" still passes, because it IS
consulted -- on the wrong set. It is one comparison operator, it looks correct
in review, and it inverts the entire owner policy. That is the same shape as
the `max` that becomes a `min` in the fabric contract, and it gets the same
treatment: a negative control that flips it and proves this harness goes red.

A REFUSE-EVERYTHING BUILD SATISFIES EVERY SAFETY PROPERTY HERE. So does a
vocabulary with no enabled actions. Both are useless and both would pass, which
is why branch coverage is asserted at the end rather than assumed.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.host import ActionRefused, ActionVocabulary, HostContractViolation  # noqa: E402

TIERS = ("observe", "self", "advise", "adjust_reversible", "destructive")
NON_MUTATING = ("observe", "advise")
READ_LINE = "advise"
CONSENT = ("never", "per_rule", "per_instance")
PROVENANCES = ("verified_local", "model_generated", "retrieved_external",
               "owner", "system", "")


def rand_vocabulary(rng: random.Random, tmp: Path) -> tuple[Path, dict]:
    """A syntactically valid vocabulary with randomised rows.

    Deliberately generates vocabularies CI-056 would reject -- enabled rows
    above the read line, irreversible rows in low tiers. The enforcement code
    must hold the line even when handed a contract that should never have been
    merged, because "the check would have caught it" is not a property of the
    runtime.
    """
    n = rng.randint(1, 9)
    rows: dict[str, dict] = {}
    for i in range(n):
        tier = rng.choice(TIERS)
        rev = rng.random() < 0.7
        rows[f"act_{i}"] = {
            "tier": tier,
            "enabled": rng.random() < 0.5,
            "reversible": rev,
            "inverse": f"act_{rng.randrange(n)}" if rev else "",
            "requires_owner_consent": rng.choice(CONSENT),
            "max_targets_per_window": rng.randint(1, 32),
            "window_seconds": 3600,
        }
    lines = ["schema_version = 1", "", "[policy]", "fail_closed = true",
             'action_provenance_required = "verified_local"',
             f"tiers = {list(TIERS)!r}".replace("'", '"'),
             f'read_line = "{READ_LINE}"',
             f"non_mutating_tiers = {list(NON_MUTATING)!r}".replace("'", '"'), ""]
    for name, a in rows.items():
        lines.append(f"[action.{name}]")
        for k, v in a.items():
            lines.append(f"{k} = {json.dumps(v)}")
        lines.append("")
    p = tmp / "vocab.toml"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p, rows


def rand_request(rng: random.Random, rows: dict) -> tuple[str, str, str | None]:
    name = (rng.choice(list(rows)) if rows and rng.random() < 0.8
            else f"undeclared_{rng.randrange(1000)}")
    return name, rng.choice(PROVENANCES), (f"OD-{rng.randrange(999)}"
                                           if rng.random() < 0.5 else None)


# --------------------------------------------------------------------- props

def prop_absent_is_refused(outcome, name, prov, auth, rows, v) -> str | None:
    if name not in rows and outcome != "REFUSED":
        return f"{name!r} is not in the vocabulary and was not refused"
    return None


def prop_disabled_is_refused(outcome, name, prov, auth, rows, v) -> str | None:
    if name in rows and not rows[name]["enabled"] and outcome != "REFUSED":
        return f"{name!r} is disabled and was not refused"
    return None


def prop_provenance_is_exact(outcome, name, prov, auth, rows, v) -> str | None:
    if prov != "verified_local" and outcome != "REFUSED":
        return f"{name!r} permitted on provenance {prov!r}"
    return None


def prop_host_change_needs_authorisation(outcome, name, prov, auth, rows, v) -> str | None:
    """THE property. An enabled, correctly-provenanced action that reaches
    outside VESPER must still be refused without an owner authorisation."""
    if name in rows and v.changes_host(name) and not auth and outcome != "REFUSED":
        return (f"{name!r} (tier {rows[name]['tier']}) changes the host and was "
                f"permitted with no owner authorisation")
    return None


def prop_permit_implies_every_condition(outcome, name, prov, auth, rows, v) -> str | None:
    if outcome != "ALLOWED":
        return None
    if name not in rows:
        return f"{name!r} permitted while absent from the vocabulary"
    if not rows[name]["enabled"]:
        return f"{name!r} permitted while disabled"
    if prov != "verified_local":
        return f"{name!r} permitted on provenance {prov!r}"
    if v.changes_host(name) and not auth:
        return f"{name!r} permitted as a host change with no authorisation"
    return None


def prop_read_line_partitions(outcome, name, prov, auth, rows, v) -> str | None:
    """changes_host must be exactly 'above the read line', in that direction."""
    if name not in rows:
        return None
    expected = TIERS.index(rows[name]["tier"]) > TIERS.index(READ_LINE)
    if v.changes_host(name) != expected:
        return (f"changes_host({name!r}) = {v.changes_host(name)} but tier "
                f"{rows[name]['tier']!r} vs read line {READ_LINE!r} implies {expected}")
    return None


PROPERTIES = [prop_absent_is_refused, prop_disabled_is_refused,
              prop_provenance_is_exact, prop_host_change_needs_authorisation,
              prop_permit_implies_every_condition, prop_read_line_partitions]


def evaluate(v, name, prov, auth):
    try:
        a = v.check(name, provenance=prov, owner_authorisation=auth)
        return ("ALLOWED", a)
    except ActionRefused:
        return ("REFUSED", None)


def run(rng: random.Random, iterations: int, tmp: Path, vocab_cls=ActionVocabulary) -> dict:
    failures: list[str] = []
    outcomes = {"ALLOWED": 0, "REFUSED": 0}
    assertions = 0
    for _ in range(iterations):
        p, rows = rand_vocabulary(rng, tmp)
        try:
            v = vocab_cls(p)
        except HostContractViolation:
            continue
        for _ in range(6):
            name, prov, auth = rand_request(rng, rows)
            outcome, act = evaluate(v, name, prov, auth)
            outcomes[outcome] += 1
            if outcome == "ALLOWED" and act is None:
                failures.append("permitted without returning an action")
            for prop in PROPERTIES:
                assertions += 1
                msg = prop(outcome, name, prov, auth, rows, v)
                if msg:
                    failures.append(f"{prop.__name__}: {msg}")
    return {"failures": failures[:20], "n_failures": len(failures),
            "assertions": assertions, "outcomes": outcomes}


class InvertedReadLine(ActionVocabulary):
    """NEGATIVE CONTROL -- the one-operator slip this harness exists to catch.

    `>` becomes `<`. Authorisation is still consulted on every call, so any
    test asserting "authorisation is checked" stays green. What changes is WHO
    it is checked for: reads start demanding owner sign-off and host mutations
    stop. If this build passes, the harness is not testing the read line.
    """

    def changes_host(self, name: str) -> bool:
        a = self._actions.get(name)
        return a is not None and self.tiers.index(a.tier) < self._line


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=20260820)
    ap.add_argument("--out")
    args = ap.parse_args()
    t0 = time.time()

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        print(f"HOST ACTION BOUNDARY -- {args.iterations} randomised vocabularies, seed {args.seed}\n")
        res = run(random.Random(args.seed), args.iterations, tmp)
        print(f"  properties       {res['assertions']:,} assertions, {res['n_failures']} failures")
        for f in res["failures"]:
            print(f"      {f}")
        print(f"  outcomes         {res['outcomes']}")

        # A vocabulary that refuses everything satisfies every property above.
        reached = res["outcomes"]
        covered = reached["ALLOWED"] > 0 and reached["REFUSED"] > 0
        print(f"  branch coverage  reached ALLOWED and REFUSED: {covered}")

        print("\n  negative control -- read line inverted:")
        neg = run(random.Random(args.seed), max(200, args.iterations // 10),
                  tmp, vocab_cls=InvertedReadLine)
        caught = neg["n_failures"] > 0
        print(f"      {neg['n_failures']} failures across {neg['assertions']:,} assertions")
        print(f"      harness detects the inversion: {caught}")
        if not caught:
            print("      DEFECT: the negative control PASSED. This harness "
                  "cannot see the fault it was written for.")

    ok = not res["n_failures"] and covered and caught
    dt = time.time() - t0
    print(f"\n  HOST STRESS: {'PASS' if ok else 'FAIL'}   ({dt:.1f}s)")
    if args.out:
        Path(args.out).write_text(json.dumps(
            {"seed": args.seed, "iterations": args.iterations, "properties": res,
             "negative_control": {"failures": neg["n_failures"], "caught": caught},
             "ok": ok}, indent=2), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
