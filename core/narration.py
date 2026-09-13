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

# The gateway's vocabulary, imported by value so a new classification cannot
# silently arrive with no line to say for it.
from .gateway import TERMINAL, TRANSIENT           # noqa: E402

# Classifications this module speaks for that are not gateway exception
# classes: they are outcomes the gateway reaches by other paths.
EXTRA = ("quota_unavailable_on_tier", "cost_policy", "exhausted_all",
         "greeting")


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
                 speaker: Any = None) -> None:
        self._bus = bus
        self._lock = threading.RLock()
        self._speaker = speaker            # injected in tests; None = real voice
        raw = tomllib.loads((path or NARRATION).read_text(encoding="utf-8"))
        self._fields = set(raw.get("fields") or ())
        sp = raw.get("speech") or {}
        self._speak_when = set(sp.get("speak_when") or ())
        self._log_only = set(sp.get("log_only_when") or ())
        # WHEN EACH CLASSIFICATION WAS LAST SPOKEN. Keyed on the KIND of
        # failure, so two different problems inside a minute are two things
        # the owner hears, and one problem twelve times is one.
        self._said_at: dict = {}
        self._lines: dict[str, str] = {}
        for row in raw.get("line") or []:
            self._lines[row["classification"]] = row["text"]

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
                 interruption_class: str = "proactive", **fields: Any) -> Utterance:
        """Render, and speak only if the budget's class permits it."""
        text = self.render(classification, **fields)
        may_speak = interruption_class in self._speak_when
        spoken = False
        reason = ""
        if may_speak:
            spoken, reason = self._say(text)
        else:
            reason = (f"interruption_class={interruption_class} is log-only "
                      "(RB-006 proportionality: narrating every retry of an "
                      "unattended run is noise, not status)")
        u = Utterance(classification, text, spoken, reason)
        if self._bus is not None:
            self._bus.publish("narration.emitted", subject=classification,
                              payload=u.to_dict(), component="narration")
        return u

    # ------------------------------------------------------------- wiring

    def attach(self, bus: Any, *, interruption_class: str = "proactive",
               next_rung: str = "another provider") -> None:
        """Narrate `gateway.attempt` events as they happen.

        SUBSCRIBED RATHER THAN CALLED, and the decoupling is the point. The
        gateway must not hold a reference to a voice: SR-004 is about what a
        person is told, and a call path that has to know about speech is one
        that breaks in every headless context -- a cloud session, a test, a node
        with no audio. The gateway publishes what happened; whether that becomes
        a sound is somebody else's decision, made here.

        `interruption_class` is supplied by the CALLER because only the caller
        knows whether anyone is waiting. The same failure is `active_user_task`
        when the owner is watching and `proactive` at 3 a.m., and this class
        cannot tell those apart from the event alone.
        """
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
            # THE BUDGET DECLARES A RATE AND NOTHING READ IT. `announce` checks
            # `speak_when` -- may this CLASS speak at all -- and that is the only
            # half of `interruption_budget.toml` anything consults. The contract
            # also declares `max_contacts_per_hour = 2` for a focused session,
            # and a permitted class was permitted EVERY time: one outage narrates
            # once per retry per rung, so the owner hears the same sentence ten
            # times and reports "i keep hearing rate limited shit again".
            #
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
                return
            self._said_at[cls] = now
            ms = payload.get("retry_after_ms") or payload.get("server_retry_after_ms")
            self.announce(
                cls, interruption_class=interruption_class,
                provider_class="a provider",
                attempt=payload.get("attempt", 1),
                max_attempts=payload.get("max_attempts", 10),
                retry_in_seconds=(round(ms / 1000) if ms else 0),
                next_rung=next_rung)

        bus.subscribe("gateway.attempt", on_attempt, name="narration-attempt",
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
