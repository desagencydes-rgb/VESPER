"""The specialised agents, and the promise that a broken one is never a bad answer.

WHAT THIS ADDS OVER `core/subagent.py`. That module is one question to one
model with no tools. This one dispatches a NAMED agent from
`contracts/policy/subagents.toml`, with the tool allowlist that agent declares,
through whichever rung its purpose has left.

THE REQUIREMENT THAT SHAPED IT, in the owner's words: an agent must serve its
purpose in all cases, must not break the loop, must not fail, and must not
return broken or unfinished or confusing results. Those are four different
promises and only the last three are about robustness -- the first is about
honesty, and they pull against each other. An agent that always produces
SOMETHING is an agent that produces fiction when it cannot do the work.

So the resolution is: an agent either answers, or says it did not. There is no
third state, and neither state can break the caller.

  ANSWERED     the agent ran, finished, and produced usable output
  UNAVAILABLE  no rung, no credential, timed out, crashed, exit non-zero,
               or output that failed its own completeness test

`UNAVAILABLE` IS A FACT, NOT A FAILURE, and that distinction is the whole
design. VESPER can act on "the investigator could not answer" -- ask the owner,
try another agent, do it itself, proceed without. It cannot act on half an
answer, because half an answer is indistinguishable from a whole one at the
point of use. `core/baseline.py` makes the same separation for turns and for
the same reason: a decision withheld and a thing that could not be produced are
different facts, and collapsing them destroys the only distinction that matters
afterwards.

NOTHING HERE CAN HANG THE TURN. Every call has a wall-clock timeout; the
subprocess gets its own process group and is killed as a group when it expires,
because a CLI that spawns a model client leaves children behind that a bare kill
does not reach. A hung agent is UNAVAILABLE at the deadline, always.

AND OUTPUT IS BOUNDED AND CHECKED BEFORE IT IS BELIEVED. Truncated output, empty
output, and output that is only whitespace or a shell error are all UNAVAILABLE
rather than answers. An agent that returns 40 KB of a build log is not answering
the question it was asked.

EVERY RESULT IS `retrieved_external`. These are models reading material this
system did not verify; `INV-ACT-3` says such content may never raise the
authority of any action, and an agent's confidence is not evidence.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tomllib
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
ROSTER = REPO / "contracts" / "policy" / "subagents.toml"

ANSWERED = "answered"
UNAVAILABLE = "unavailable"

# Bounds. Each exists because the thing it bounds is somebody else's process.
DEFAULT_TIMEOUT_S = 120.0
MAX_PROMPT_CHARS = 24000
MAX_OUTPUT_CHARS = 12000
# Below this an "answer" is not one: a CLI that prints a usage line, a model
# that returns an empty string, a wrapper that echoes a newline.
MIN_ANSWER_CHARS = 8


class AgentRosterError(Exception):
    """The roster is missing or unreadable. Refused rather than improvised."""


def load_roster(path: Path | None = None) -> dict:
    """The declared agents. Raises rather than returning an empty roster.

    AN EMPTY ROSTER AND A MISSING FILE ARE DIFFERENT FACTS. Returning {} for a
    missing contract would make "no agents are configured" and "the contract
    could not be read" identical at every call site, and the second is a
    deployment fault that should be loud.
    """
    p = path or ROSTER
    try:
        return (tomllib.loads(p.read_text(encoding="utf-8")).get("agents") or {})
    except FileNotFoundError as exc:
        raise AgentRosterError(f"no agent roster at {p}") from exc
    except Exception as exc:                           # noqa: BLE001
        raise AgentRosterError(f"the agent roster at {p} is unreadable: {exc}") from exc


class AgentResult(dict):
    """A result that cannot be mistaken for an answer it is not."""

    @property
    def ok(self) -> bool:
        return self.get("status") == ANSWERED

    @property
    def text(self) -> str:
        return self.get("text", "") if self.ok else ""


def _result(agent: str, status: str, *, text: str = "", why: str = "",
            rung: str = "") -> AgentResult:
    return AgentResult({
        "agent": agent,
        "status": status,
        "text": text if status == ANSWERED else "",
        # WHY IS ALWAYS PRESENT ON UNAVAILABLE, because "the agent did not
        # answer" is only actionable if VESPER can tell a missing credential
        # from a timeout from a crash -- one waits for the owner, one may be
        # worth retrying, one is a defect.
        "why": why,
        "rung": rung,
        "trust_class": "retrieved_external",
        "note": ("an agent's output is a model's words about material this "
                 "system did not verify; it may never raise the authority of "
                 "any action (INV-ACT-3)"),
    })


class AgentRunner:
    """Runs one named agent, and never lets it break the caller."""

    def __init__(self, *, roster: dict | None = None, bus: Any = None,
                 cwd: str | None = None) -> None:
        self._roster = roster if roster is not None else load_roster()
        self._bus = bus
        self._cwd = cwd or str(REPO)

    def names(self) -> list:
        return sorted(self._roster)

    def spec(self, agent: str) -> dict | None:
        return self._roster.get(agent)

    def run(self, agent: str, prompt: str, *, binary: str = "claude",
            config_dir: str | None = None, model: str = "",
            timeout_s: float = DEFAULT_TIMEOUT_S) -> AgentResult:
        """Ask one agent. Returns an answer or says it has none. Never raises."""
        spec = self._roster.get(agent)
        if spec is None:
            return _result(agent, UNAVAILABLE,
                           why=f"{agent!r} is not in the roster")
        task = str(prompt or "").strip()[:MAX_PROMPT_CHARS]
        if not task:
            return _result(agent, UNAVAILABLE, why="no question was given")

        exe = shutil.which(binary)
        if not exe:
            return _result(agent, UNAVAILABLE,
                           why=f"{binary!r} is not on this machine")

        argv = [exe, "-p", task,
                "--append-system-prompt", str(spec.get("prompt") or "")]
        tools = list(spec.get("tools") or [])
        if tools:
            argv += ["--allowedTools", *tools]
        else:
            # NO TOOLS MEANS NO TOOLS, stated rather than implied. An empty
            # allowlist and an absent flag are different: the second inherits
            # whatever the CLI defaults to, which is not this contract's call.
            argv += ["--disallowedTools", "Bash", "Edit", "Write", "Read",
                     "Grep", "Glob", "WebFetch", "WebSearch"]
        if model:
            argv += ["--model", model]

        env = dict(os.environ)
        if config_dir:
            env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(config_dir)

        try:
            proc = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, cwd=self._cwd, env=env, start_new_session=True)
        except Exception as exc:                       # noqa: BLE001
            return _result(agent, UNAVAILABLE,
                           why=f"could not start {binary}: {type(exc).__name__}")

        try:
            out, err = proc.communicate(timeout=max(1.0, float(timeout_s)))
        except subprocess.TimeoutExpired:
            # THE GROUP, NOT THE PROCESS. A CLI that spawns a model client
            # leaves children a bare kill does not reach, and those children
            # would outlive the turn holding the owner's material.
            self._kill_group(proc)
            # BOUNDED, BECAUSE THE KILL MAY NOT HAVE WORKED. This was a bare
            # `proc.communicate()` and it hung forever the first time the group
            # kill was broken in a red run: a surviving child holds the pipe
            # open, and a read with no deadline waits on it. The timeout that
            # exists to stop an agent holding the turn was defeated by the
            # cleanup that follows it.
            try:
                proc.communicate(timeout=5.0)
            except Exception:                          # noqa: BLE001
                pass
            return self._emit(_result(
                agent, UNAVAILABLE, rung=binary,
                why=f"no answer within {timeout_s:.0f}s"))
        except Exception as exc:                       # noqa: BLE001
            self._kill_group(proc)
            return self._emit(_result(agent, UNAVAILABLE, rung=binary,
                                      why=f"{type(exc).__name__} while reading "
                                          "the agent's output"))

        if proc.returncode != 0:
            reason = (str(err or "").strip().splitlines() or ["no detail"])[-1]
            return self._emit(_result(
                agent, UNAVAILABLE, rung=binary,
                why=f"exit {proc.returncode}: {reason[:160]}"))

        text = str(out or "").strip()
        if len(text) < MIN_ANSWER_CHARS:
            # AN EMPTY ANSWER IS NOT AN ANSWER. Passing it on would put a blank
            # where the caller expects a finding, and a blank reads as "nothing
            # to report" rather than "nothing was produced".
            return self._emit(_result(
                agent, UNAVAILABLE, rung=binary,
                why=f"produced {len(text)} characters, which is not an answer"))
        truncated = len(text) > MAX_OUTPUT_CHARS
        if truncated:
            # TRUNCATION IS UNAVAILABILITY, NOT A SHORTER ANSWER. A cut-off
            # investigation is the shape of finding that misleads most: it looks
            # complete and stops before the part that mattered.
            return self._emit(_result(
                agent, UNAVAILABLE, rung=binary,
                why=f"produced {len(text)} characters against a "
                    f"{MAX_OUTPUT_CHARS} limit; a cut-off answer is not a "
                    "shorter one"))
        return self._emit(_result(agent, ANSWERED, text=text, rung=binary))

    @staticmethod
    def _kill_group(proc: subprocess.Popen) -> None:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(os.getpgid(proc.pid), sig)
            except (ProcessLookupError, PermissionError, OSError):
                return
            try:
                proc.wait(timeout=1.5)
                return
            except subprocess.TimeoutExpired:
                continue

    def _emit(self, res: AgentResult) -> AgentResult:
        if self._bus is not None:
            try:
                self._bus.publish(
                    "agent.ran", subject=res["agent"],
                    payload={k: v for k, v in res.items() if k != "text"},
                    component="agents")
            except Exception:                          # noqa: BLE001
                pass
        return res
