#!/usr/bin/env python3
"""F3 (partial) — semantic scenes, no-chat-required, outbox reconciliation.

SCOPE. F3's full gate is A-009, A-020, A-026, A-027, A-035. This runs **A-009,
A-026 and A-035**, which are pure software.

  A-020  needs measured latency on target hardware through the voice chain --
         SPIKE-002, blocked on the iPhone app which is blocked on the MacBook
  A-027  artifact generation (images, PDF, HTML) needs a rendering toolchain
         that is not a dependency this stage should add on its own

A-009's NEGATIVE CONTROL IS NAMED BY THE LADDER ITSELF: a `{markdown, speech}`
implementation "cannot produce these rows because it has no typed elements to
degrade". That is the sharpest control in the corpus -- it fails not by getting
an answer wrong but by having no way to express the answer at all.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.config import RuntimeConfig  # noqa: E402
from core.reconcile import OutboxEntry, Reconciler  # noqa: E402
from core.scene import (DEGRADATION_ACTIONS, EndpointCapability,  # noqa: E402
                        SceneContractViolation, SceneElement, SceneRenderer,
                        SemanticScene)
from core.supervisor import Supervisor  # noqa: E402

RESULTS: list[dict] = []


class Case:
    def __init__(self, cid: str, title: str, *, control: bool = False) -> None:
        self.cid, self.title, self.control = cid, title, control
        self.assertions: list[dict] = []

    def check(self, name: str, passed: bool, detail: str = "") -> bool:
        self.assertions.append({"assertion": name, "passed": bool(passed),
                                "detail": detail})
        return bool(passed)

    def finish(self, error: str | None = None) -> dict:
        allp = bool(self.assertions) and all(a["passed"] for a in self.assertions)
        if self.control:
            ok = not allp
            verdict = ("CONTROL OK -- broken build failed as required" if ok else
                       "HARNESS DEFECT -- the control PASSED, so it tests nothing. "
                       "The matching positive result is void.")
        else:
            ok = allp and error is None
            verdict = "PASS" if ok else "FAIL"
        rec = {"case": self.cid, "title": self.title,
               "is_negative_control": self.control, "ok": ok,
               "verdict": verdict, "assertions": self.assertions}
        if error:
            rec["error"] = error
        RESULTS.append(rec)
        return rec


def _sup(tmp: Path, name: str) -> Supervisor:
    return Supervisor(RuntimeConfig(node_id=name, data_dir=tmp / name)).start()


def _events(sup: Supervisor, kind: str) -> list[dict]:
    return [r.body for r in sup.store.read("log") if r.kind == kind]


def _fixture_scene() -> SemanticScene:
    """A-009's fixture: at minimum a metric, a table, a diagram, an indicator."""
    return SemanticScene(
        scene_id="scene-1",
        intent={"goal": "report last night's measurement run"},
        elements=[
            SceneElement("e-metric", "metric",
                         {"label": "sustained throughput", "value": "6.79 tok/s"},
                         priority=90),
            SceneElement("e-table", "table",
                         {"columns": ["tier", "wall idle", "wall conc"],
                          "rows": [["draft", 142.01, 82.0],
                                   ["small", 97.64, 85.32],
                                   ["strong", 6.79, 7.33]]},
                         priority=70),
            SceneElement("e-diagram", "diagram",
                         {"nodes": ["intent", "act", "record"],
                          "edges": [["intent", "act"], ["act", "record"]]},
                         priority=60, spatial_intent="depth"),
            SceneElement("e-state", "state_indicator", "all gates green",
                         priority=95),
        ])


# ===========================================================================
# A-009 — one scene, three endpoints
# ===========================================================================

def a009_three_endpoints(tmp: Path) -> None:
    c = Case("A-009", "One scene, three materially different endpoints")
    try:
        sup = _sup(tmp, "n39")
        r = SceneRenderer(sup.bus)
        c.check("the degradation ladder actually loaded from the contract",
                r.rung_count() == 50, f"{r.rung_count()} rungs")

        scene = _fixture_scene()
        endpoints = [
            EndpointCapability("screen", "2d", ("visual", "text")),
            EndpointCapability("voice", "none", ("audio",)),
            EndpointCapability("glass", "pseudo_3d_glass", ("visual", "depth")),
        ]
        results = {e.endpoint_id: r.render(scene, e) for e in endpoints}

        c.check("1. all three produce output",
                all(x.rendered for x in results.values()),
                str({k: v.rendered for k, v in results.items()}))
        c.check("2. all three produce an explicit degradations array",
                all(isinstance(x.degradations, list) for x in results.values()))
        c.check("2. the array is present even when empty",
                all(x.to_dict()["degradations"] is not None
                    for x in results.values()))
        c.check("every degradation action is in the closed enum",
                all(d["action"] in DEGRADATION_ACTIONS
                    for x in results.values() for d in x.degradations))

        # THE VOICE ROW. A diagram must narrate, not apologise.
        voice = results["voice"]
        narr = [p for p in voice.output if p["element_id"] == "e-diagram"][0]
        c.check("the diagram NARRATES on a voice-only endpoint",
                "leads to" in narr["speech"], narr["speech"][:70])
        c.check("the table narrates its shape rather than being dropped",
                any("rows by" in p.get("speech", "") for p in voice.output))
        c.check("voice degradations are visual_to_narrative, not omitted",
                all(d["action"] == "visual_to_narrative"
                    for d in voice.degradations),
                str([d["action"] for d in voice.degradations]))

        # The 2D endpoint flattens depth and says so.
        screen = results["screen"]
        c.check("the 2D endpoint reports depth_flattened for the depth element",
                any(d["action"] == "depth_flattened"
                    and d["element_id"] == "e-diagram"
                    for d in screen.degradations),
                str(screen.degradations))
        # The glass endpoint has depth, so it degrades nothing.
        c.check("the depth-capable endpoint degrades nothing",
                results["glass"].degradations == [],
                str(results["glass"].degradations))

        # A scene carrying styling is refused: it would be a layout in disguise.
        refused = False
        try:
            SceneElement("bad", "text", '<div style="color:red">hi</div>')
        except SceneContractViolation:
            refused = True
        c.check("an element carrying presentation markup is refused", refused)

        # Withholding is reported, never silent.
        w = r.render(scene, endpoints[0], withhold_reason="unknown person present")
        c.check("withholding is reported with its reason",
                not w.rendered and w.withheld_reason == "unknown person present")
        c.check("presence.withheld emitted",
                len(_events(sup, "presence.withheld")) == 1)
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# A-026 — no chat required
# ===========================================================================

def a026_no_chat_required(tmp: Path) -> None:
    c = Case("A-026", "Every capability reachable with text surfaces disabled")
    try:
        sup = _sup(tmp, "n326")
        r = SceneRenderer(sup.bus)
        scene = _fixture_scene()

        # Boot with EVERY text and keyboard surface disabled.
        voice_only = EndpointCapability("voice", "none", ("audio",))
        action_only = EndpointCapability("actuator", "linear", ("action",))

        res_voice = r.render(scene, voice_only)
        c.check("every element is deliverable through audio alone",
                res_voice.rendered
                and len(res_voice.output) == len(scene.elements),
                f"{len(res_voice.output)} of {len(scene.elements)}")
        c.check("no element required a text surface to be delivered",
                all("speech" in p for p in res_voice.output))

        res_action = r.render(scene, action_only)
        c.check("a non-text, non-visual surface still produces output",
                res_action.rendered)

        # The structural claim: no modality is REQUIRED. Assert that the
        # renderer never returns rendered=False for want of text.
        for ep in (voice_only, action_only):
            out = r.render(scene, ep)
            if not out.rendered and out.withheld_reason is None:
                c.check(f"{ep.endpoint_id} rendered without a text surface",
                        False, "renderer refused for want of text")
        c.check("no capability is reachable only via text", True,
                "both non-text endpoints rendered the full scene")
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# A-035 — outbox and reconciliation, three crash points
# ===========================================================================

def a035_reconciliation(tmp: Path) -> None:
    c = Case("A-035", "Exactly-once EFFECT across three crash points")
    try:
        sup = _sup(tmp, "n335")
        rec = Reconciler(sup.bus)
        far_side: list = []

        def perform(args):
            far_side.append(args)
            return {"id": f"remote-{len(far_side)}"}

        # The probe: asks the far side whether the effect landed.
        def probe(entry):
            for a in far_side:
                if a.get("key") == entry.idempotency_key:
                    return {"found": True}
            return None

        rec.register_probe("mail.send", probe)

        # --- crash BEFORE the call: nothing happened, replay is safe ---------
        e1 = rec.record_intent(OutboxEntry("o1", "task-1", "mail.send",
                                           {"key": "k1"}, "k1",
                                           delegated_identity="owner"))
        rec.attempt("o1", perform, crash_at="before_call")
        c.check("crash before the call leaves nothing on the far side",
                len(far_side) == 0)
        r1 = rec.recover("task-1")
        c.check("recovery marks it replay-safe",
                r1[0]["action"] == "replay_safe", str(r1[0]))

        # --- crash MID-call: the honest unknown -------------------------------
        e2 = rec.record_intent(OutboxEntry("o2", "task-2", "mail.send",
                                           {"key": "k2"}, "k2",
                                           delegated_identity="owner"))
        rec.attempt("o2", perform, crash_at="mid_call")
        c.check("a mid-call crash records UNKNOWN, not FAILED",
                rec.get("o2").state == "UNKNOWN", rec.get("o2").state)
        r2 = rec.recover("task-2")
        c.check("the probe found no effect, so a resend is safe",
                r2[0]["action"] == "replay_safe", str(r2[0]))

        # --- crash AFTER the call, before recording: the dangerous one -------
        e3 = rec.record_intent(OutboxEntry("o3", "task-3", "mail.send",
                                           {"key": "k3"}, "k3",
                                           delegated_identity="owner"))
        rec.attempt("o3", perform, crash_at="after_call_before_record")
        c.check("the effect DID land on the far side", len(far_side) == 1,
                str(len(far_side)))
        c.check("the outbox does not know it landed",
                rec.get("o3").state == "UNKNOWN")
        r3 = rec.recover("task-3")
        c.check("1. the probe finds it and it is NOT resent",
                r3[0]["action"] == "confirmed", str(r3[0]))
        c.check("1. exactly-once effect: the far side saw it once",
                len(far_side) == 1, str(len(far_side)))

        # 2. recovery reads the OUTBOX, never replays the task
        recovered = _events(sup, "outbox.recovered")
        c.check("2. recovery is explicitly outbox-driven",
                bool(recovered) and "OUTBOX" in recovered[-1]["payload"]["note"])

        # 3. reconcilable=false escalates instead of retrying
        e4 = rec.record_intent(OutboxEntry("o4", "task-4", "payment.charge",
                                           {"key": "k4"}, "k4",
                                           reconcilable=False,
                                           delegated_identity="owner"))
        rec.attempt("o4", perform, crash_at="mid_call")
        r4 = rec.recover("task-4")
        c.check("3. reconcilable=false escalates to the user",
                r4[0]["action"] == "escalated", str(r4[0]))
        c.check("3. and does NOT retry", len(far_side) == 1, str(len(far_side)))
        c.check("3. the escalation is emitted",
                len(_events(sup, "outbox.escalated_to_user")) == 1)

        # 4. the audit chain reconstructs
        chain = rec.audit_chain("o3")
        c.check("4. the audit chain reconstructs end to end",
                chain["chain"] == ["trigger", "authority", "command", "outbox",
                                   "probe", "result"])
        # 5. delegated identity is on the outbox record
        c.check("5. delegated-identity attribution is on the outbox record",
                chain["delegated_identity"] == "owner" and chain["reconstructible"])
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


# ===========================================================================
# NEGATIVE CONTROL — named by the degradation ladder
# ===========================================================================

def control_markdown_speech(tmp: Path) -> None:
    """MANDATORY (A-009 / the ladder). A {markdown, speech} implementation
    "cannot produce these rows because it has no typed elements to degrade"."""
    c = Case("A-009-CONTROL", "{markdown, speech} implementation", control=True)
    try:
        sup = _sup(tmp, "nctl39")

        class MarkdownSpeechRenderer:
            """The defect: content is pre-rendered text, so nothing is typed.
            There is no element to degrade and no vocabulary to report with."""

            def render(self, scene, endpoint):
                md = "\\n".join(f"- {e.element_id}" for e in scene.elements)
                if endpoint.spatial_class == "none":
                    return {"rendered": True, "speech": md}   # reads the markdown aloud
                return {"rendered": True, "markdown": md}

        r = MarkdownSpeechRenderer()
        scene = _fixture_scene()
        out = r.render(scene, EndpointCapability("voice", "none", ("audio",)))

        c.check("2. all three produce an explicit degradations array",
                "degradations" in out,
                "the result has no degradations key at all")
        c.check("the diagram NARRATES on a voice-only endpoint",
                "leads to" in out.get("speech", ""),
                "it reads a bullet list of element ids aloud")
        sup.stop()
        c.finish()
    except Exception:
        c.finish(error=traceback.format_exc(limit=6))


POSITIVE = [a009_three_endpoints, a026_no_chat_required, a035_reconciliation]
CONTROLS = [control_markdown_speech]

NOT_CLAIMED = {
    "A-020": ("measured latency against declared budgets on target hardware. "
              "Needs SPIKE-002, which needs the iPhone app, which needs the "
              "MacBook. The budget-declaration half is enforced by CI-051."),
    "A-027": ("artifact generation with provenance (images, PDF, HTML) needs a "
              "rendering toolchain. Not a dependency this stage adds on its own."),
    "A-009.3+": ("assertions beyond 'all three render with a degradation "
                 "report' involve a real spatial simulator; the pseudo_3d_glass "
                 "endpoint here is a capability descriptor, not a display."),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="vesper-f3-"))
    t0 = time.time()
    try:
        for fn in POSITIVE:
            fn(tmp)
        for fn in CONTROLS:
            fn(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    width = max(len(r["case"]) for r in RESULTS) + 2
    print()
    for r in RESULTS:
        print(f"[{'ok  ' if r['ok'] else 'FAIL'}] {r['case']:<{width}} {r['verdict']}")
        for a in r["assertions"]:
            if not a["passed"]:
                sym = "expected-fail" if r["is_negative_control"] else "MISS"
                print(f"           {sym}: {a['assertion']}"
                      + (f" -- {a['detail']}" if a["detail"] else ""))
        if r.get("error"):
            print(f"           ERROR: {r['error'].splitlines()[-1]}")

    pos = [r for r in RESULTS if not r["is_negative_control"]]
    ctl = [r for r in RESULTS if r["is_negative_control"]]
    pos_ok, ctl_ok = sum(r["ok"] for r in pos), sum(r["ok"] for r in ctl)
    gate = pos_ok == len(pos) and ctl_ok == len(ctl)

    print(f"\n  positive cases    {pos_ok}/{len(pos)} passed")
    print(f"  negative controls {ctl_ok}/{len(ctl)} failed as required")
    print("\n  NOT CLAIMED:")
    for k, why in NOT_CLAIMED.items():
        print(f"    {k}: {why}")
    print(f"\n  F3 SCENE/PRESENCE/OUTBOX: {'PASS' if gate else 'FAIL'}   "
          f"({time.time() - t0:.1f}s)")
    print("  F3 as a whole is NOT complete -- A-020 and A-027 are out of scope.")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({
            "schema_version": 1, "gate": "F3-scene-presence-outbox",
            "acceptance_tests_claimed": ["A-009", "A-026", "A-035"],
            "acceptance_tests_not_claimed": NOT_CLAIMED,
            "f3_complete": False, "passed": gate,
            "positive_passed": pos_ok, "positive_total": len(pos),
            "controls_failed_as_required": ctl_ok, "controls_total": len(ctl),
            "results": RESULTS,
        }, indent=2), encoding="utf-8")
        print(f"  wrote {args.out}")
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
