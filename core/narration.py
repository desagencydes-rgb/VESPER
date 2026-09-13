"""What VESPER says while a request is failing over. Templated, never generated.

SR-004 asks for the error type and the retry time to be SHOWN. That is not a
log line: the owner is sitting in front of a request that is not answering, and
the difference between a system that is working and one that has hung is
whether it says so.

NO MODEL PRODUCES ANY OF THIS, for three reasons that are all structural:

  1. THE THING THAT FAILED IS THE MODEL LAYER. Asking a model to narrate its
     own unavailability is a dependency loop that breaks precisely when it is
     needed. The narration must work when nothing else does.
  2. A GENERATED SENTENCE CANNOT BE ASSERTED ON. A template renders identically
     every time, so a check compares an exact string rather than hoping.
  3. IT MUST COST NOTHING. A spoken status line that became a provider call
     would spend quota to explain that quota is spent.

THE BUDGET DECIDES WHETHER IT SPEAKS, AND THIS CLASS DOES NOT RE-DECIDE IT.
`interruption_budget.toml` holds a strict lattice and says preparation is
unbudgeted. A failing request the owner is waiting on is `active_user_task` --
speaking is the point. The identical failure inside a 3 a.m. autonomous run is
`proactive`, and narrating ten retries then would satisfy the letter of SR-004
while violating RB-006. Both requirements stand unmodified; the class arbitrates.

THE VOICE IS AN INSTRUMENT AND ITS SELF-REPORT IS NOT EVIDENCE. `spd-say`
exiting 0 is not a sound in the room -- this corpus records that in as many
words. So `speak()` reports what it ATTEMPTED and whether the process exited,
and never claims the owner heard anything.
"""

from __future__ import annotations

import time as _time
import shutil
import subprocess
import threading
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
NARRATION = REPO / "contracts" / "policy" / "narration.toml"
BUDGET = REPO / "contracts" / "policy" / "interruption_budget.toml"

# The gateway's vocabulary, imported by value so a new classification cannot
# silently arrive with no line to say for it.
from .gateway import LOCAL, TERMINAL, TRANSIENT    # noqa: E402

# Classifications this module speaks for that are not gateway exception
# classes: they are outcomes the gateway reaches by other paths. `descent` is
# the ladder moving after a rung whose own line has no destination clause
# (a rate limit or a server error that outlasted its retries).
EXTRA = ("quota_unavailable_on_tier", "cost_policy", "exhausted_all",
         "greeting", "descent")

# WHAT `{next_rung}` MAY SAY, and it is decided by the row's measured locality,
# never by a constant handed in at startup. The owner heard "moving to a local
# model" for two days from a node whose nearest thing to a local rung was
# ollama.com: the phrase was INV-HW-1-correct and the FACT was false. Unknown
# renders as remote -- INV-HW-2, an unmeasured locality is not local.
NEXT_RUNG_LOCAL = "a model on this machine"
NEXT_RUNG_OTHER = "another provider"

# ONE HOUR, the window every `max_*_per_hour` figure in the budget is written
# against. Sliding, so "this hour" means the last 3600 s and not a clock face.
HOUR_S = 3600.0


# HOW LONG THE SAME FAILURE STAYS QUIET after it has been said once.
# `interruption_budget.toml` declares max_contacts_per_hour = 2 for a focused
# session and nothing read it: `announce` consults `speak_when` -- may this
# CLASS speak at all -- and that is the only half anything consulted. So a
# permitted class was permitted EVERY time, one outage narrated once per retry
# per rung, and the owner reported hearing the same sentence over and over.
REPEAT_SILENCE_S = 90.0


class NarrationRefused(Exception):
    """A template could not be loaded or rendered. Fail loudly at load."""


@dataclass(frozen=True, slots=True)
class Utterance:
    classification: str
    text: str
    spoken: bool
    reason: str

    def to_dict(self) -> dict:
        return {"classification": self.classification, "text": self.text,
                "spoken": self.spoken, "reason": self.reason}


class Announcer:
    """Renders and (sometimes) speaks the operational status of a request."""

    def __init__(self, bus: Any = None, *, path: Path | None = None,
                 speaker: Any = None, budget_path: Path | None = None) -> None:
        self._bus = bus
        self._lock = threading.RLock()
        self._speaker = speaker            # injected in tests; None = real voice
        raw = tomllib.loads((path or NARRATION).read_text(encoding="utf-8"))
        self._fields = set(raw.get("fields") or ())
        sp = raw.get("speech") or {}
        self._speak_when = set(sp.get("speak_when") or ())
        self._log_only = set(sp.get("log_only_when") or ())
        # THE BUDGET CELL FOR A REQUEST THE OWNER IS WAITING ON. Declared in the
        # narration contract rather than here, because "the owner is present
        # and attending" is a claim about the owner and belongs on a governed
        # surface. Absent, no cell is assumed and nothing is spoken: the budget
        # contract's own rule is that an undeclared cell is zero.
        wc = sp.get("waiting_cell") or []
        self._waiting_cell = tuple(wc) if len(wc) == 2 else None
        # WHEN EACH CLASSIFICATION WAS LAST SPOKEN. Keyed on the KIND of
        # failure, so two different problems inside a minute are two things
        # the owner hears, and one problem twelve times is one.
        self._said_at: dict = {}
        self._lines: dict[str, str] = {}
        for row in raw.get("line") or []:
            self._lines[row["classification"]] = row["text"]

        # THE RATE, READ AT LAST. `interruption_budget.toml` declares, per
        # (operating period, attention state), how many times an hour the owner
        # may be contacted and what it may cost, and what speech costs. For two
        # weeks only `speak_when` was consulted -- a membership test -- so a
        # permitted class was permitted every time and the declared two
        # contacts an hour sat unread. Every spoken line is a contact here.
        b = tomllib.loads((budget_path or BUDGET).read_text(encoding="utf-8"))
        self._budget_cells: dict = b.get("budget") or {}
        cost = (b.get("modality_cost") or {}).get("speech")
        if not isinstance(cost, int):
            raise NarrationRefused(
                "interruption_budget.toml declares no integer cost for speech; "
                "a spoken line whose cost is unknown cannot be budgeted, and an "
                "unbudgeted contact is the defect this reads to prevent.")
        self._speech_cost = cost
        self._exempt = set((b.get("exempt") or {}).get("classes") or ())
        # (monotonic seconds, cost) of every SPOKEN contact, pruned to the hour.
        self._contacts: list[tuple[float, int]] = []

        # EVERY CLASSIFICATION THE GATEWAY CAN PRODUCE MUST HAVE A LINE, checked
        # at load rather than discovered at the moment of failure. A missing
        # template is silence exactly when the owner is waiting to be told
        # something, which is the failure this whole module exists to prevent.
        missing = [c for c in (*TRANSIENT, *TERMINAL, *EXTRA)
                   if c not in self._lines]
        if missing:
            raise NarrationRefused(
                f"no narration line for {missing}. Every classification the "
                "gateway can produce needs one -- a missing template is silence "
                "at the exact moment the owner is waiting to be told something.")

        # A template naming a field nobody supplies renders into a KeyError at
        # failure time. Refused here instead.
        for cls, text in self._lines.items():
            for tok in _placeholders(text):
                if tok not in self._fields:
                    raise NarrationRefused(
                        f"line {cls!r} references {{{tok}}}, which is not in the "
                        f"declared field set {sorted(self._fields)}. A template "
                        "that cannot be rendered is worse than none.")

    # ---------------------------------------------------------------- render

    def render(self, classification: str, **fields: Any) -> str:
        """The exact sentence. Deterministic, so a check can compare it."""
        text = self._lines.get(classification)
        if text is None:
            raise NarrationRefused(f"no line for classification {classification!r}")
        needed = _placeholders(text)
        missing = [t for t in needed if t not in fields or fields[t] is None]
        if missing:
            # NOT rendered with blanks. "Retrying in  seconds" reads as a bug to
            # a listener and destroys trust in every other line.
            raise NarrationRefused(
                f"line {classification!r} needs {missing} and they were not "
                "supplied. A half-rendered sentence is worse than silence.")
        return text.format(**{k: fields[k] for k in needed})

    # ----------------------------------------------------------------- speak

    def announce(self, classification: str, *,
                 interruption_class: str = "proactive",
                 budget_cell: tuple | None = None, **fields: Any) -> Utterance:
        """Render, and speak only if the budget's class AND rate permit it.

        Two questions, both asked of `interruption_budget.toml`: may this
        CLASS speak at all (the lattice), and has this HOUR any contact left
        (the rate). The second was never asked before, and the answer to the
        first alone is what let one outage narrate itself ten times.
        """
        text = self.render(classification, **fields)
        may_speak = interruption_class in self._speak_when
        spoken = False
        reason = ""
        if not may_speak:
            reason = (f"interruption_class={interruption_class} is log-only "
                      "(RB-006 proportionality: narrating every retry of an "
                      "unattended run is noise, not status)")
        elif interruption_class in self._exempt:
            spoken, reason = self._say(text)
        else:
            with self._lock:
                ok, why = self._budget_permits(budget_cell or self._waiting_cell)
                if ok:
                    spoken, reason = self._say(text)
                    if spoken:
                        # A contact is a sentence that was ATTEMPTED aloud;
                        # one the synthesiser refused cost the owner nothing.
                        self._contacts.append((_time.monotonic(), self._speech_cost))
                else:
                    reason = why
        u = Utterance(classification, text, spoken, reason)
        if self._bus is not None:
            self._bus.publish("narration.emitted", subject=classification,
                              payload=u.to_dict(), component="narration")
        return u

    def _budget_permits(self, cell: tuple | None) -> tuple:
        """May one more spoken contact happen this hour under `cell`?

        `cell` is (operating_period, attention_state). A MISSING CELL IS ZERO,
        the budget contract's own rule: absence never means unlimited. Speech
        must be a permitted modality there, and both the contact count and the
        cost spent in the last hour must leave room for one more.
        """
        if cell is None:
            return False, ("budget: no cell declared for this request, and an "
                           "undeclared cell is max_contacts_per_hour = 0")
        period, attention = cell
        row = (self._budget_cells.get(period) or {}).get(attention)
        if not isinstance(row, dict):
            return False, (f"budget: {period}.{attention} is not declared in "
                           "interruption_budget.toml, and an undeclared cell is "
                           "max_contacts_per_hour = 0")
        if "speech" not in (row.get("permitted_modalities") or []):
            return False, (f"budget: speech is not a permitted modality in "
                           f"{period}.{attention}")
        now = _time.monotonic()
        self._contacts = [(t, c) for t, c in self._contacts if now - t < HOUR_S]
        max_contacts = int(row.get("max_contacts_per_hour", 0))
        max_cost = int(row.get("max_cost_per_hour", 0))
        if len(self._contacts) >= max_contacts:
            return False, (f"budget: {len(self._contacts)} contact(s) this hour "
                           f"is the declared maximum for {period}.{attention} "
                           f"(max_contacts_per_hour = {max_contacts})")
        spent = sum(c for _, c in self._contacts)
        if spent + self._speech_cost > max_cost:
            return False, (f"budget: {spent} of {max_cost} spent this hour in "
                           f"{period}.{attention}, and speech costs "
                           f"{self._speech_cost}")
        return True, ""

    # ------------------------------------------------------------- wiring

    def attach(self, bus: Any, *, interruption_class: str = "proactive",
               budget_cell: tuple | None = None) -> None:
        """Narrate the gateway's events as they happen.

        SUBSCRIBED RATHER THAN CALLED, and the decoupling is the point. The
        gateway must not hold a reference to a voice: SR-004 is about what a
        person is told, and a call path that has to know about speech is one
        that breaks in every headless context -- a cloud session, a test, a node
        with no audio. The gateway publishes what happened; whether that becomes
        a sound is somebody else's decision, made here.

        `interruption_class` is supplied by the CALLER because only the caller
        knows whether anyone is waiting. The same failure is `active_user_task`
        when the owner is watching and `proactive` at 3 a.m., and this class
        cannot tell those apart from the event alone. `budget_cell` likewise:
        the caller may know the owner's attention state; absent, the contract's
        `waiting_cell` stands in for a request the owner is waiting on.

        TWO TOPICS, TWO KINDS OF SENTENCE. `gateway.attempt` names the rung that
        FAILED and carries the retry state; it can never say where the ladder
        goes next, because at that moment the router has not chosen. So a line
        whose template has a destination clause is not spoken from an attempt:
        it waits for `gateway.descended`, which the gateway publishes only once
        the successor's own skip filters have passed and it is about to be
        called -- a fact, not a prediction. The constant that used to fill
        `{next_rung}` at startup ("a local model", on a node with no local
        rung) is gone with the parameter that carried it.
        """
        def _quiet(cls: str) -> bool:
            # SUPPRESSED PER CLASSIFICATION, NOT GLOBALLY. Two DIFFERENT problems
            # inside a minute are two things worth hearing; the same one twelve
            # times is one thing said twelve times.
            #
            # `time.monotonic`, AND INV-COORD-4 PERMITS IT. This orders nothing
            # and supersedes nothing -- it asks "has an interval elapsed", which
            # `CLAUDE.md` names explicitly as the case that is neither.
            now = _time.monotonic()
            last = self._said_at.get(cls, 0.0)
            if last and (now - last) < REPEAT_SILENCE_S:
                if self._bus is not None:
                    self._bus.publish(
                        "narration.suppressed", subject=cls,
                        payload={"classification": cls,
                                 "since_last_s": round(now - last, 1),
                                 "note": ("the same failure was already spoken; "
                                          "saying it again is noise, not status")},
                        component="narration")
                return True
            self._said_at[cls] = now
            return False

        def on_attempt(ev: Any) -> None:
            payload = getattr(ev, "payload", {}) or {}
            cls = payload.get("classification")
            if not cls or payload.get("outcome") == "ok":
                return          # nothing to say about a call that worked
            if cls not in self._lines:
                # A classification with no line is a DEFECT, not a reason to
                # crash the call path. CI-061 fails on it; here it is recorded
                # and the request continues -- narration must never be able to
                # take down the thing it is describing.
                if self._bus is not None:
                    self._bus.publish(
                        "narration.no_line", subject=cls,
                        payload={"classification": cls,
                                 "note": "no narration line; CI-061 covers this"},
                        component="narration")
                return
            if "next_rung" in _placeholders(self._lines[cls]):
                # THE DESTINATION IS NOT KNOWN YET. Saying "moving to X" here
                # would assert a descent the router has not made -- the same
                # defect as the old constant, just harder to see. The sentence
                # is spoken from `gateway.descended`, if and when it happens.
                if self._bus is not None:
                    self._bus.publish(
                        "narration.deferred", subject=cls,
                        payload={"classification": cls,
                                 "provider_id": payload.get("provider_id"),
                                 "note": ("the line names a destination; it is "
                                          "spoken when the ladder actually moves")},
                        component="narration")
                return
            if _quiet(cls):
                return
            ms = payload.get("retry_after_ms") or payload.get("server_retry_after_ms")
            self.announce(
                cls, interruption_class=interruption_class,
                budget_cell=budget_cell,
                provider_class="a provider",
                attempt=payload.get("attempt", 1),
                max_attempts=payload.get("max_attempts", 10),
                retry_in_seconds=(round(ms / 1000) if ms else 0))

        def on_descended(ev: Any) -> None:
            payload = getattr(ev, "payload", {}) or {}
            frm = payload.get("from_classification") or ""
            # The departed rung's own line, if it has a destination clause;
            # otherwise the generic descent (a rate limit or a server error
            # that outlasted its retries has a "retrying" line, not a "moving").
            cls = (frm if frm in self._lines
                   and "next_rung" in _placeholders(self._lines[frm])
                   else "descent")
            if _quiet(cls):
                return
            # MEASURED LOCALITY, NEVER A NAME. `unknown` is remote here: a rung
            # nobody measured as being on this machine is not said to be.
            where = (NEXT_RUNG_LOCAL if payload.get("to_locality") == LOCAL
                     else NEXT_RUNG_OTHER)
            self.announce(
                cls, interruption_class=interruption_class,
                budget_cell=budget_cell,
                provider_class="a provider", attempt=1, max_attempts=1,
                retry_in_seconds=0, next_rung=where)

        bus.subscribe("gateway.attempt", on_attempt, name="narration-attempt",
                      idempotency_key=lambda e: e.event_id)
        bus.subscribe("gateway.descended", on_descended, name="narration-descent",
                      idempotency_key=lambda e: e.event_id)

    def _say(self, text: str) -> tuple:
        """Attempt speech. Reports what was ATTEMPTED, never what was heard.

        A LAUNCHER RETURNING 0 IS NOT A SOUND IN THE ROOM. This corpus records
        that mistake explicitly, so nothing here claims the owner heard
        anything -- only that the process was started and how it exited.
        """
        if self._speaker is not None:
            self._speaker(text)
            return True, "injected speaker"
        exe = shutil.which("say")
        if not exe:
            return False, "no local speech synthesiser on this host"
        try:
            cp = subprocess.run([exe, text], capture_output=True,
                                text=True, timeout=30)
        except Exception as e:                      # noqa: BLE001
            return False, f"speech process failed: {type(e).__name__}: {e}"
        if cp.returncode != 0:
            return False, f"speech process exited {cp.returncode}"
        return True, "speech process exited 0 (NOT evidence the owner heard it)"


def _placeholders(text: str) -> list:
    """`{name}` tokens in order, without importing a formatter."""
    out, i = [], 0
    while True:
        a = text.find("{", i)
        if a == -1:
            return out
        b = text.find("}", a)
        if b == -1:
            return out
        out.append(text[a + 1:b])
        i = b + 1
