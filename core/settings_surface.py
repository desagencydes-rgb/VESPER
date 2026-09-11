"""The settings surface's own readings (§11.6).

WHY A PRODUCER AND NOT A LIST OF LABELS. The owner's note on §11.6 is one
sentence and the whole design is in it: *"the card stops reading UNAVAILABLE and
becomes the same card at full screen"*. A settings screen that names
thirty-five things and shows a value for none of them is the UNAVAILABLE card
again with more words in it.

So every item below either READS SOMETHING REAL or says why it cannot, and the
two are never confused. `INV-HW-2`'s rule applied to a surface: UNKNOWN means
unavailable, fail-closed, with the reason carried.

WHAT THIS DELIBERATELY DOES NOT DO IS WRITE.

The settings the owner routed here are mostly GOVERNED CONTRACTS --
`host_actions.toml`, `cost_policy.toml`, `trigger_registry.toml`,
`capability_profiles.toml`. `host_actions.toml` says in its own header that
enabling a row is *"a governed act, not a configuration tweak"*, and
`governed_surfaces.toml` names which files need review and by whom. A settings
screen with a toggle next to `enabled = false` would route around every one of
those reviews from a button -- and `CI-056` would still be green, because the
file it reads would have been edited by something the owner approved once.

So this reads, explains, and says WHERE a change is made. The items that are
genuinely the owner's own preference rather than a governed contract -- voice,
language, quiet hours, wake word -- are the ones that can become editable, and
they are marked so the surface can tell them apart.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import tomllib
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

# The owner's own routing export, §11.6, in their order. Thirty-four items plus
# `Explain this setting`, which the doc notes is *"in each dialog, on hover"* --
# a property of every other item rather than a thirty-fifth peer, so it is not a
# row here. It is the `why` field every row carries.
ITEMS: tuple[tuple[str, str, str], ...] = (
    # (id, name, what it is)
    ("enable-disable-actions", "Enable / disable actions",
     "Which host actions VESPER may perform at all. Above the read line, a row "
     "ships disabled until an owner authorisation is recorded against it."),
    ("rule-authoring", "Rule authoring",
     "The trigger predicates that decide when VESPER acts unprompted."),
    ("authorization", "Authorization",
     "The six levels, what each costs to approve, and which are single-use."),
    ("capability-profiles", "Capability profiles",
     "What each enrolled machine measurably sustains. UNKNOWN means unavailable."),
    ("host-actions", "Host actions",
     "The closed vocabulary of things VESPER may do to the machine it runs on."),
    ("network-fabric", "Network fabric",
     "The declared segments and the trust ceiling of each. No addresses."),
    ("cost-policy", "Cost policy",
     "What VESPER may spend, per rung, and the choke point that enforces it."),
    ("latency-budgets", "Latency budgets",
     "How long each class of work may take before it is treated as late."),
    ("interruption-budget", "Interruption budget",
     "How often VESPER may interrupt the owner, and what resets the count."),
    ("trigger-registry", "Trigger registry",
     "Every trigger, its predicate, and whether the clock alone can fire it."),
    ("persona-policy", "Persona policy",
     "How VESPER addresses the owner, and what it may never say."),
    ("execution-classes", "Execution classes",
     "The scheduling clamp each kind of work runs under on this platform."),
    ("operating-periods", "Operating periods",
     "The named parts of the day that change what VESPER may do."),
    ("model-routing", "Model routing",
     "Which rung answers which question, and what happens when one is withdrawn."),
    ("backup-restore", "Backup & restore",
     "What VESPER carries forward, and what a restore cannot rebuild."),
    ("config-diff", "Config diff",
     "What changed in the governed files, and who reviewed it."),
    ("scheduled-changes", "Scheduled changes",
     "Configuration changes that take effect later, before they do."),
    ("reset-to-measured", "Reset to measured",
     "Throw away declared numbers and go back to what was measured here."),
    ("validate-config", "Validate config",
     "Run every contract check against the files as they stand."),
    ("scene-element-types", "Scene element types",
     "The kinds of thing a scene may contain, and what each may reach."),
    ("endpoint-selection", "Endpoint selection",
     "Which surface VESPER reaches the owner through, as a profile."),
    ("privacy-routing", "Privacy routing",
     "Which work may leave this machine, and what is redacted before it does."),
    ("quiet-hours", "Quiet hours",
     "When VESPER stays silent, and what still gets through."),
    ("do-not-disturb", "Do not disturb",
     "Silence now, without changing the standing schedule."),
    ("voice-and-speed", "Voice & speed",
     "The voice VESPER speaks in, and how fast."),
    ("wake-word", "Wake word",
     "The phrase that starts listening, and what it costs to keep armed."),
    ("language", "Language",
     "The language VESPER answers in, and which ones recognise on-device."),
    ("notification-rules", "Notification rules",
     "What is worth telling the owner about, and how loudly."),
    ("gate-status", "Gate status",
     "Every mechanical check, and how many are passing right now."),
    ("self-test-evidence", "Self-test evidence",
     "Each check's red run: the proof it can detect the fault it names."),
    ("traceability", "Traceability",
     "Which requirements are specified, and which are deliberately not."),
    ("spikes", "Spikes",
     "The measurements that settled a question, with their status."),
    ("decisions", "Decisions (ADRs)",
     "The architectural decisions, and which are accepted."),
    ("limitation-records", "Limitation records",
     "What VESPER cannot do, recorded so it is not rediscovered."),
)

# WHICH ITEMS ARE THE OWNER'S PREFERENCE AND WHICH ARE GOVERNED CONTRACTS.
#
# The distinction decides whether a surface may ever offer to change it. A
# preference is the owner's to set; a governed contract is changed by a reviewed
# edit, and `governed_surfaces.toml` names the reviewer. A toggle next to a
# governed row would route around that review from a button -- which is exactly
# what `host_actions.toml` means by "enabling one is a governed act, not a
# configuration tweak".
OWNER_PREFERENCE = frozenset({
    "voice-and-speed", "wake-word", "language", "quiet-hours", "do-not-disturb",
    "notification-rules", "endpoint-selection",
})


def _toml(rel: str) -> dict | None:
    try:
        return tomllib.loads((REPO / rel).read_text(encoding="utf-8"))
    except Exception:                                     # noqa: BLE001
        return None


def _count_lines(rel: str, pattern: str) -> int | None:
    try:
        text = (REPO / rel).read_text(encoding="utf-8")
    except Exception:                                     # noqa: BLE001
        return None
    return len(re.findall(pattern, text, re.M))


def _reading(item_id: str) -> tuple[str, str, str]:
    """(value, source, why_unavailable) for one item.

    THE SOURCE IS PART OF THE READING AND NOT DECORATION. A number on a settings
    screen with no source is the shape `MEMORY.md` opens by refusing -- the
    island's "320k assertions" column was wrong for weeks because a figure
    travelled without one.
    """
    if item_id in ("host-actions", "enable-disable-actions"):
        doc = _toml("contracts/policy/host_actions.toml")
        if not doc:
            return "", "", "the action vocabulary could not be read"
        acts = doc.get("action") or {}
        on = [n for n, a in acts.items() if a.get("enabled")]
        tiers = (doc.get("policy") or {}).get("tiers") or []
        line = (doc.get("policy") or {}).get("read_line")
        above = [n for n, a in acts.items()
                 if a.get("tier") in tiers and line in tiers
                 and tiers.index(a.get("tier")) > tiers.index(line)]
        waiting = [n for n in above if not acts[n].get("enabled")]
        if item_id == "host-actions":
            return (f"{len(acts)} declared, {len(on)} enabled",
                    "contracts/policy/host_actions.toml", "")
        return (f"{len(on)} enabled, {len(waiting)} awaiting authorisation",
                "contracts/policy/host_actions.toml", "")

    if item_id == "trigger-registry":
        doc = _toml("contracts/policy/trigger_registry.toml")
        if not doc:
            return "", "", "the trigger registry could not be read"
        trg = doc.get("triggers") or {}
        on = [k for k, v in trg.items() if v.get("enabled")]
        return (f"{len(trg)} declared, {len(on)} enabled",
                "contracts/policy/trigger_registry.toml", "")

    if item_id == "cost-policy":
        doc = _toml("contracts/policy/cost_policy.toml")
        if not doc:
            return "", "", "the cost policy could not be read"
        return (f"{len(doc)} sections declared",
                "contracts/policy/cost_policy.toml", "")

    if item_id == "latency-budgets":
        # `profile`, `path` AND `chain`, not `budget`. Same false zero as above.
        doc = _toml("contracts/policy/latency_budgets.toml")
        if not doc:
            return "", "", "the latency budgets could not be read"
        parts = {k: doc.get(k) for k in ("profile", "path", "chain")
                 if isinstance(doc.get(k), dict)}
        if not parts:
            return "", "", ("the contract declares none of profile, path or "
                            "chain, so there is nothing to count")
        n = sum(len(v) for v in parts.values())
        return (f"{n} budget(s) across {', '.join(parts)}",
                "contracts/policy/latency_budgets.toml", "")

    if item_id == "interruption-budget":
        doc = _toml("contracts/policy/interruption_budget.toml")
        if not doc:
            return "", "", "the interruption budget could not be read"
        return (f"{len(doc)} section(s) declared",
                "contracts/policy/interruption_budget.toml", "")

    if item_id == "capability-profiles":
        # THE KEY IS `capability`, AND GUESSING IT WRONG PRODUCED A ZERO.
        # Driven 2026-09-11: `doc.get("profile")` missed and the row read
        # "0 profile(s), 0 measured" -- a FALSE reading, which is worse than
        # UNAVAILABLE because it looks like a measurement. `measured` is a
        # top-level flag here, not a per-profile one.
        doc = _toml("contracts/policy/capability_profiles.toml")
        if not doc:
            return "", "", "the capability profiles could not be read"
        caps = doc.get("capability") or {}
        if not caps:
            return "", "", ("the contract declares no `capability` table, so "
                            "there is nothing to count rather than zero of it")
        measured = bool(doc.get("measured"))
        return (f"{len(caps)} capability profile(s), "
                f"measured = {str(measured).lower()}",
                "contracts/policy/capability_profiles.toml", "")

    if item_id == "network-fabric":
        doc = _toml("contracts/policy/network_fabric.toml")
        if not doc:
            return "", "", "the network fabric contract could not be read"
        seg = doc.get("segment") or doc.get("segments") or {}
        return (f"{len(seg)} segment(s) declared",
                "contracts/policy/network_fabric.toml", "")

    if item_id == "persona-policy":
        doc = _toml("contracts/policy/persona.toml")
        if not doc:
            return "", "", "the persona contract could not be read"
        return (f"{len(doc)} section(s) declared",
                "contracts/policy/persona.toml", "")

    if item_id == "voice-and-speed":
        doc = _toml("contracts/policy/voice.toml")
        if not doc:
            return "", "", "the voice contract could not be read"
        v = doc.get("voice") or {}
        name = str(v.get("name") or v.get("voice") or "")
        rate = v.get("rate") or v.get("speed")
        if name or rate:
            return (f"{name or 'default'}"
                    + (f", rate {rate}" if rate else ""),
                    "contracts/policy/voice.toml", "")
        return (f"{len(doc)} section(s) declared",
                "contracts/policy/voice.toml", "")

    if item_id == "execution-classes":
        try:
            from core.host import EXECUTION_CLASSES
            return (", ".join(EXECUTION_CLASSES), "core/host.py", "")
        except Exception:                                 # noqa: BLE001
            return "", "", "the host adapter could not be loaded"

    if item_id == "gate-status":
        # READ FROM THE DOCUMENT THE GATE ITSELF POLICES, not counted here. A
        # second counter would be a second number to drift, and `CI-089` exists
        # precisely because that pair drifted eight times.
        try:
            text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
            m = re.search(r"checks\.py all\s*#\s*(\d+) checks", text)
            if m:
                return (f"{m.group(1)} mechanical checks",
                        "CLAUDE.md, policed by CI-089", "")
        except Exception:                                 # noqa: BLE001
            pass
        return "", "", "the documented gate count could not be read"

    if item_id == "self-test-evidence":
        try:
            text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
            m = re.search(r"red-then-green,\s*(\d+) cases", text)
            if m:
                return (f"{m.group(1)} executed red runs",
                        "CLAUDE.md, policed by CI-089", "")
        except Exception:                                 # noqa: BLE001
            pass
        return "", "", "the documented red-run count could not be read"

    if item_id == "spikes":
        doc = _toml("docs/spikes/INDEX.toml")
        if not doc:
            return "", "", "the spike index could not be read"
        sp = doc.get("spikes") or doc.get("spike") or {}
        return (f"{len(sp)} spike(s) indexed",
                "docs/spikes/INDEX.toml (the status authority)", "")

    if item_id == "decisions":
        # COUNTED AS DISTINCT IDS, not as table rows: the register cites ADR ids
        # in prose as well, and a line-anchored pattern found none at all.
        try:
            text = (REPO / "docs" / "ADR" / "ADR-REGISTER.md").read_text(encoding="utf-8")
        except Exception:                                 # noqa: BLE001
            return "", "", "the ADR register could not be read"
        ids = sorted(set(re.findall(r"\bADR-(\d{3})\b", text)))
        if not ids:
            return "", "", "the register names no ADR ids"
        return f"{len(ids)} decision(s) registered", "docs/ADR/ADR-REGISTER.md", ""

    if item_id == "limitation-records":
        # THERE IS NO `docs/limitations/`, and the honest answer is to say that
        # rather than to report zero of something that has no home yet. The
        # records exist -- `MEMORY.md` is full of them -- but not as a counted
        # artifact, so a number here would be invented.
        d = REPO / "docs" / "limitations"
        if not d.is_dir():
            return "", "", ("there is no docs/limitations/ directory: "
                            "limitations are recorded in MEMORY.md and in the "
                            "protocol documents, not as a counted set")
        n = len(list(d.glob("*.md")))
        return f"{n} limitation(s) recorded", "docs/limitations/", ""

    if item_id == "config-diff":
        # WHAT CHANGED IN THE GOVERNED FILES, asked of git rather than tracked
        # separately -- a second record of the same fact is a second thing to
        # drift.
        try:
            out = subprocess.run(
                ["git", "status", "--porcelain", "--", "contracts/"],
                capture_output=True, text=True, cwd=str(REPO), timeout=10)
            n = len([l for l in out.stdout.splitlines() if l.strip()])
            return (f"{n} governed file(s) changed and uncommitted",
                    "git status over contracts/", "")
        except Exception:                                 # noqa: BLE001
            return "", "", "git could not be asked what changed"

    if item_id == "validate-config":
        return ("run `python3.13 tools/ci/checks.py all`",
                "tools/ci/checks.py", "")

    if item_id == "traceability":
        return ("run `python3.13 tools/traceability_lint.py`",
                "tools/traceability_lint.py", "")

    if item_id == "scene-element-types":
        doc = _toml("contracts/policy/governed_surfaces.toml")
        if doc:
            return (f"{len(doc.get('surface') or doc)} governed surface(s)",
                    "contracts/policy/governed_surfaces.toml", "")
        return "", "", "the governed surfaces contract could not be read"

    # EVERYTHING ELSE SAYS SO, AND SAYS WHY. This is the honest half: the owner
    # routed thirty-four items here and this tree can read some of them today.
    # Inventing a plausible value for the rest is the defect every gate in this
    # corpus exists to refuse.
    return "", "", ("no producer reads this yet, so nothing here is a "
                    "measurement -- it is named so it is not forgotten")


def rows() -> list:
    """Every settings item, with a real reading or an honest absence."""
    now = int(time.time() * 1000)
    out = []
    for item_id, name, what in ITEMS:
        value, source, why = _reading(item_id)
        row: dict[str, Any] = {
            "id": item_id, "name": name, "what": what,
            "governed": item_id not in OWNER_PREFERENCE,
        }
        if value:
            row.update(status="available", value=value, source=source,
                       at_ms=now, ttl_ms=600_000)
        else:
            row.update(status="unavailable", reason=why)
        # WHERE A CHANGE IS MADE, said on every governed row. A settings screen
        # that shows a governed value and offers no way to change it looks broken
        # unless it says why -- and the reason is the review, not a missing
        # button.
        if row["governed"]:
            row["change_by"] = ("a reviewed edit to the contract above; "
                                "governed_surfaces.toml names the reviewer")
        out.append(row)
    return out
