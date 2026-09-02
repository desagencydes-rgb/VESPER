"""Commands that outlive the turn that started them — and the stop that reaches them.

WHY THIS IS ITS OWN MODULE. A background process is the first thing VESPER can
start that is not bounded by the turn. Everything else in the act path finishes
before `maybe_act` returns: the step budget bounds the loop, the timeout bounds
each command, and the interlock is asked before every step. A process that keeps
running has none of those, so the properties have to be rebuilt around it here
rather than assumed from the caller.

THE STOP IS THE WHOLE PROBLEM. `core/actor.py` asks `permitted()` before every
step, which is what makes the emergency stop reach work already running -- and a
background process has no step boundary to ask at. Left alone it is a way to
start work that never sees the stop at all, which would quietly undo the thing
that was fixed hours earlier the same day.

AND THE INTERLOCK CANNOT DO THE KILLING. `INV-STOP-2` bans the interlock from
importing anything that can fail, block or refuse -- it is a dead-man's switch,
and every dependency that can hang is a way for stopping to become impossible
exactly when it is wanted. `engage()` therefore MARKS in-flight work resumable
and kills nothing. So the killing happens on this side: whoever holds the
processes asks the interlock, and the pump already asks it every pass.

A STOP OF AUTONOMY IS NOT A STOP OF THE OWNER'S OWN WORK. Each process records
the period it was started under. `STOP_AUTONOMY` terminates what VESPER started
for itself and leaves what the owner asked for running, because that is what the
words mean -- and because an owner who says "stop what you're doing on your own"
and loses the build they asked for will not use the stop again.

TERMINATE, THEN KILL, THEN GIVE UP AND SAY SO. `terminate()` is a signal a
process may ignore; a stop that politely asks and then reports success is the
`spd-say exiting 0` failure this corpus keeps finding. So the escalation is
real, and a process that survives both is RECORDED as surviving rather than
counted as stopped.

NOTHING OUTLIVES THE RUNTIME. The registry kills everything at interpreter exit,
because a VESPER that has quit and left a command running is a VESPER whose stop
does not exist any more.
"""

from __future__ import annotations

import atexit
import os
import signal
import subprocess
import threading
import time
import uuid
from typing import Any

# HOW MANY MAY RUN AT ONCE. Bounded because the proposer decides when to start
# one: an unbounded pool is a fork bomb reachable by a steered model, and the
# host this runs on is a laptop the owner is also using.
MAX_BACKGROUND = 4
# How long a terminate is given before the kill. Short: this is the emergency
# stop's tail, and the budget it inherits is A-031.1's two seconds.
TERM_GRACE_S = 1.5
# Output is captured to a bounded buffer per process. A command that prints
# forever must not become a memory leak that outlives the turn.
MAX_CAPTURE_BYTES = 64 * 1024


class TooManyBackgroundCommands(Exception):
    """The pool is full. Refused rather than queued: a queue hides the bound."""


class _Job:
    __slots__ = ("job_id", "cmd", "period", "proc", "started_ms", "out",
                 "_lock", "_reader", "truncated", "argv")

    def __init__(self, job_id: str, cmd: str, period: str,
                 proc: subprocess.Popen, argv: list | None = None) -> None:
        self.job_id, self.cmd, self.period = job_id, cmd, period
        # WHAT WAS ACTUALLY EXECUTED, not what the caller says it did. A
        # `contained: True` in a return value is the instrument reporting on
        # itself; the argv is the evidence, and a check that reads it can tell
        # a contained command from one that merely claims to be.
        self.argv = list(argv or [])
        self.proc = proc
        self.started_ms = int(time.time() * 1000)
        self.out = bytearray()
        self.truncated = False
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._drain, daemon=True,
                                        name=f"bg-{job_id[:8]}")
        self._reader.start()

    def _drain(self) -> None:
        """Read the pipe as it fills.

        NOT `communicate()` AT WAIT TIME. A process whose output fills the pipe
        buffer BLOCKS until someone reads it, so a job nobody has waited on yet
        would hang forever holding a slot -- and the stop would then be killing
        something that was already stuck rather than working.
        """
        stream = self.proc.stdout
        if stream is None:
            return
        try:
            for chunk in iter(lambda: stream.read(4096), b""):
                with self._lock:
                    room = MAX_CAPTURE_BYTES - len(self.out)
                    if room <= 0:
                        self.truncated = True
                        continue          # keep draining so the pipe never fills
                    self.out.extend(chunk[:room])
                    if len(chunk) > room:
                        self.truncated = True
        except Exception:                              # noqa: BLE001
            pass

    def snapshot(self) -> dict:
        with self._lock:
            text = self.out.decode("utf-8", "replace")
        code = self.proc.poll()
        return {"job_id": self.job_id, "cmd": self.cmd, "period": self.period,
                "argv0": self.argv[0] if self.argv else "",
                "running": code is None, "exit_code": code,
                "output": text, "truncated": self.truncated,
                "started_ms": self.started_ms}


class BackgroundJobs:
    """Every command still running, and the only thing that can end them."""

    def __init__(self, bus: Any = None) -> None:
        self._bus = bus
        self._jobs: dict = {}
        self._lock = threading.RLock()
        atexit.register(self.terminate_all, reason="runtime_exit")

    def start(self, argv: list, *, cmd: str, period: str, cwd: str,
              env: dict | None = None) -> dict:
        with self._lock:
            live = [j for j in self._jobs.values() if j.proc.poll() is None]
            if len(live) >= MAX_BACKGROUND:
                raise TooManyBackgroundCommands(
                    f"{len(live)} background commands are already running "
                    f"(limit {MAX_BACKGROUND}). Wait for one, or run this in "
                    "the foreground.")
        # `start_new_session` PUTS IT IN ITS OWN PROCESS GROUP, and that is what
        # makes the stop able to reach a command that spawns children. Killing
        # the pid alone leaves `npm test`'s node processes running with nothing
        # holding a handle to them -- work VESPER started, still going, after
        # the stop, and invisible.
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, cwd=cwd, env=env,
                                start_new_session=True)
        job = _Job(str(uuid.uuid4()), cmd, period, proc, argv)
        with self._lock:
            self._jobs[job.job_id] = job
        self._emit("shell.background_started",
                   {"job_id": job.job_id, "cmd": cmd, "period": period,
                    "pid": proc.pid})
        return {"job_id": job.job_id, "running": True, "pid": proc.pid}

    def poll(self, job_id: str) -> dict:
        job = self._jobs.get(job_id)
        if job is None:
            return {"job_id": job_id, "unknown": True}
        return job.snapshot()

    def wait(self, job_id: str, *, timeout_s: float = 30.0) -> dict:
        """Block until it finishes or the timeout expires. Never forever."""
        job = self._jobs.get(job_id)
        if job is None:
            return {"job_id": job_id, "unknown": True}
        try:
            job.proc.wait(timeout=max(0.0, float(timeout_s)))
        except subprocess.TimeoutExpired:
            pass
        snap = job.snapshot()
        snap["timed_out"] = snap["running"]
        return snap

    def running(self) -> list:
        return [j.snapshot() for j in list(self._jobs.values())
                if j.proc.poll() is None]

    def terminate_all(self, *, period: str | None = None,
                      reason: str = "stop") -> list:
        """End what is running. `period` narrows it; None means everything.

        RETURNS WHAT ACTUALLY DIED, not what was asked to. A process that
        survives SIGTERM and SIGKILL is reported as surviving -- an instrument's
        self-report is not evidence, and a stop that says "stopped" about
        something still running is worse than one that says it failed.
        """
        out: list = []
        with self._lock:
            targets = [j for j in self._jobs.values()
                       if j.proc.poll() is None
                       and (period is None or j.period == period)]
        for job in targets:
            out.append(self._end(job, reason))
        if out:
            self._emit("shell.background_terminated",
                       {"reason": reason, "period": period, "jobs": out})
        return out

    def _end(self, job: _Job, reason: str) -> dict:
        pid = job.proc.pid
        for sig, label in ((signal.SIGTERM, "term"), (signal.SIGKILL, "kill")):
            try:
                # THE GROUP, NOT THE PROCESS. Children outlive a bare kill.
                os.killpg(os.getpgid(pid), sig)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                job.proc.wait(timeout=TERM_GRACE_S if sig == signal.SIGTERM else 1.0)
                return {"job_id": job.job_id, "cmd": job.cmd, "ended": label,
                        "reason": reason}
            except subprocess.TimeoutExpired:
                continue
        return {"job_id": job.job_id, "cmd": job.cmd, "ended": "SURVIVED",
                "reason": reason,
                "note": ("the command ignored SIGTERM and SIGKILL. It is still "
                         "running and the stop did NOT reach it.")}

    def reap(self) -> int:
        """Forget finished jobs so the table does not grow with the uptime."""
        with self._lock:
            done = [k for k, j in self._jobs.items()
                    if j.proc.poll() is not None
                    and (time.time() * 1000 - j.started_ms) > 300_000]
            for k in done:
                self._jobs.pop(k, None)
        return len(done)

    def _emit(self, kind: str, payload: dict) -> None:
        if self._bus is not None:
            try:
                self._bus.publish(kind, subject=payload.get("job_id", "bg"),
                                  payload=payload, component="background")
            except Exception:                          # noqa: BLE001
                pass
