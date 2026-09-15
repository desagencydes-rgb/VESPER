"""Research and project workflows: the owner's question, worked end to end, in
VESPER's own place, with every step recorded and nothing claimed without a run.

THE OWNER, 2026-09-13: *"can vesper work on a project? can vesper run a real
scientist level research, on an unsolved/undiscovered subject? can vesper
actually help with my studies on ai? can vesper help making and learning an
LLM?"* The honest answer is a WORKFLOW that does those things and shows its
work, not a sentence that says it can. Two workflows, both built from the
agent roster (`contracts/policy/subagents.toml`) and the actor:

  research(question)
    1 scholar      -> sources.md    the state of the art, WITH URLs; no URL, no run
    2 drafter      -> plan.md       hypotheses and one experiment that can run here
    3 implementer  -> experiment.py the experiment as a self-contained script
    4 the actor    -> run.md        the script RUN through the ordinary act path
    5 auditor      -> findings.md   what the run showed, against the sources

  project(goal)
    1 navigator    -> where.md      where the relevant things are
    2 implementer  -> files         the code, as files with names
    3 the actor    -> run.md        the project's entry point RUN
    4 auditor      -> report.md     what works, what does not, what is next

THE EXPERIMENT IS RUN BY THE ACTOR, NEVER BY THIS MODULE. `actor.maybe_act` is
the same door a typed sentence goes through -- intent, authorisation, the
ladder, the flag bar -- so a workflow cannot become a second way of running
commands (INV-AUTH-1). There is no `subprocess` import here, by design, and a
check refuses one. Everything lands in VESPER's own place (`core/places.py`),
never in the owner's repo.

A STEP THAT FAILS STOPS THE RUN AND SAYS SO. Findings are never written
without sources (INV-EVID-2), a script is never "run" if none was produced, and
a run whose experiment did not execute reports that rather than inventing
what it would have shown. Each step's status is written to `workflows.json`
as it happens, so the board shows the run while it is running.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import threading
import time
from typing import Any, Callable

from core.places import OWN_PLACE, ensure_own_place

STATE = pathlib.Path.home() / "Library" / "Application Support" / "VESPER"
STATUS = STATE / "workflows.json"
RESEARCH, PROJECT = "research", "project"
STEP_TIMEOUT_S = 600.0
# THE LITERATURE STEP READS THE WORLD AND TAKES AS LONG AS THE WORLD DOES.
# Measured 2026-09-14: a review of the Collatz stochastic-model question was
# still searching at 9 min 36 s and was cut off at 600 s with nothing written,
# while a one-fact question had answered in 34 s. Every other step reasons over
# text it was handed and keeps the shared limit.
AGENT_TIMEOUT_S = {"scholar": 1500.0}
# How many times a script that ran and failed goes back to the implementer with
# its own error before the run reports the failure it has.
MAX_REPAIRS = 2
_LOCK = threading.RLock()
_URL = re.compile(r"https?://[^\s)>\]\"']+")


class WorkflowRefused(ValueError):
    pass


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:48] or "untitled")


def _read_status(path: pathlib.Path | None = None) -> dict:
    p = path or STATUS
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("runs"), list):
            return d
    except (OSError, json.JSONDecodeError):
        pass
    return {"runs": []}


def _write_status(d: dict, path: pathlib.Path | None = None) -> None:
    p = path or STATUS
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    tmp.replace(p)


def runs(kind: str | None = None, path: pathlib.Path | None = None) -> list:
    rs = _read_status(path)["runs"]
    rs = [r for r in rs if kind is None or r.get("kind") == kind]
    return sorted(rs, key=lambda r: r.get("started_ms", 0), reverse=True)[:12]


def _code_blocks(text: str) -> list[tuple[str, str]]:
    """(hinted filename or '', code) for every fenced block."""
    out = []
    for m in re.finditer(r"```([a-zA-Z0-9_+.-]*)[^\n]*\n(.*?)```", text, re.S):
        code = m.group(2)
        hint = ""
        first = code.split("\n", 1)[0]
        fm = re.match(r"\s*#\s*file:\s*([\w./-]+)", first)
        if fm:
            hint = fm.group(1)
            code = code.split("\n", 1)[1] if "\n" in code else ""
        out.append((hint, code))
    return out


def _last_exit(outcome: dict) -> int | None:
    """The exit code of the last command the actor ran for one sentence, or None.

    The turn's own `result` is its first command; when the actor recovered from a
    failed attempt, `steps` holds every command in order and the last one is the
    one that counts."""
    detail = outcome.get("detail") if isinstance(outcome.get("detail"), dict) else {}
    for s in reversed(detail.get("steps") or []):
        res = ((s or {}).get("detail") or {}).get("result") if isinstance(s, dict) else None
        if isinstance(res, dict) and isinstance(res.get("exit_code"), int):
            return res["exit_code"]
    res = detail.get("result") if isinstance(detail.get("result"), dict) else {}
    return res.get("exit_code") if isinstance(res.get("exit_code"), int) else None


class Workflow:
    """One run. Steps write files and status as they go."""

    def __init__(self, kind: str, title: str, *, runner: Any, act: Callable[[str], Any] | None,
                 bus: Any = None, workdir: pathlib.Path | None = None,
                 status_path: pathlib.Path | None = None, config_dir: str | None = None,
                 binary: str | None = None, timeout_s: float = STEP_TIMEOUT_S) -> None:
        if kind not in (RESEARCH, PROJECT):
            raise WorkflowRefused(f"{kind!r} is not a workflow")
        title = str(title or "").strip()
        if len(title) < 8:
            raise WorkflowRefused("a workflow needs a real question or goal, not a word")
        self.kind, self.title = kind, title
        self.runner, self.act, self.bus = runner, act, bus
        self.config_dir, self.binary, self.timeout_s = config_dir, binary, timeout_s
        self.status_path = status_path
        base = pathlib.Path(workdir) if workdir else ensure_own_place()
        self.id = f"{kind}-{int(time.time())}-{_slug(title)[:24]}"
        self.dir = base / ("research" if kind == RESEARCH else "projects") / _slug(title)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.steps: list[dict] = []
        self.status = "running"
        self.summary = ""
        self._record()

    # ------------------------------------------------------------ bookkeeping
    def _record(self) -> None:
        with _LOCK:
            d = _read_status(self.status_path)
            d["runs"] = [r for r in d["runs"] if r.get("id") != self.id]
            d["runs"].append({"id": self.id, "kind": self.kind, "title": self.title,
                              "started_ms": int(self.id.split("-")[1]) * 1000,
                              "status": self.status, "dir": str(self.dir),
                              "steps": self.steps, "summary": self.summary[:600]})
            d["runs"] = sorted(d["runs"], key=lambda r: r.get("started_ms", 0))[-40:]
            _write_status(d, self.status_path)

    def _step(self, name: str, status: str, detail: str = "", path: str = "") -> None:
        self.steps.append({"name": name, "status": status, "detail": detail[:300],
                           "path": path, "at_ms": int(time.time() * 1000)})
        if self.bus is not None:
            self.bus.publish("workflow.step", subject=self.id,
                             payload={"kind": self.kind, "step": name, "status": status,
                                      "detail": detail[:300], "path": path},
                             component="workflows")
        self._record()

    def _finish(self, status: str, summary: str) -> None:
        self.status, self.summary = status, summary
        self._record()
        if self.bus is not None:
            self.bus.publish("workflow.finished", subject=self.id,
                             payload={"kind": self.kind, "status": status,
                                      "summary": summary[:600], "dir": str(self.dir)},
                             component="workflows")

    def _ask(self, agent: str, prompt: str) -> tuple[bool, str]:
        # A CALLER'S SHORTER LIMIT STANDS (tests pass one); the default is
        # lengthened only for the agent that has to search.
        limit = (max(self.timeout_s, AGENT_TIMEOUT_S.get(agent, 0.0))
                 if self.timeout_s >= STEP_TIMEOUT_S else self.timeout_s)
        kw: dict = {"timeout_s": limit}
        if self.config_dir:
            kw["config_dir"] = self.config_dir
        if self.binary:
            kw["binary"] = self.binary
        res = self.runner.run(agent, prompt, **kw)
        # `AgentResult` IS a dict with an `ok` PROPERTY (core/agents.py); a plain
        # dict from a fixture carries an `ok` key. The first live run read the
        # dict branch for an AgentResult, found no "ok" key, and marked an
        # answered step failed (2026-09-14, 01:31).
        if hasattr(type(res), "ok"):
            ok = bool(res.ok)
        else:
            ok = bool(res.get("ok", res.get("status") == "ok"))
        text = res.text if hasattr(type(res), "text") else str(res.get("text", ""))
        why = str(res.get("why", "")) if isinstance(res, dict) else ""
        return ok, (text if ok else (why or text))

    def _write(self, name: str, text: str) -> str:
        p = self.dir / name
        p.write_text(text, encoding="utf-8")
        return str(p)

    def _run_script(self, path: pathlib.Path, what: str) -> tuple[bool, str]:
        """Through the actor. A workflow has no command of its own."""
        if self.act is None:
            return False, "no actor to run it through; a workflow never runs commands itself"
        # `python3` AND A QUOTED PATH. The first live run asked for `python3.13`,
        # which the sandbox cannot find on its PATH, and the unquoted path split
        # at "Application Support" into two arguments; the actor recovered on its
        # own with `python3`, one failed step later (2026-09-14, run.md). The
        # prompts ask for code that runs on that interpreter.
        sentence = (f"run this command in your own place and show me its output: "
                    f"python3 \"{path}\" -- it is {what} I asked you to build; "
                    f"it may take up to two minutes")
        try:
            out = self.act(sentence)
        except Exception as exc:                          # noqa: BLE001
            return False, f"the actor raised {type(exc).__name__}: {exc}", False
        if out is None:
            return False, "the actor did not treat that as a request to run anything", False
        d = out.to_dict() if hasattr(out, "to_dict") else (out if isinstance(out, dict) else {"said": str(out)})
        kind = str(d.get("kind", ""))
        said = str(d.get("said", ""))
        code = _last_exit(d)
        detail = json.dumps(d.get("detail", {}), default=str)[:4000]
        text = (f"# Run\n\nactor outcome: {kind}" + (f", exit {code}" if code is not None else "")
                + f"\n\n{said}\n\n## Detail\n\n{detail}\n")
        # ACTED IS NOT SUCCEEDED. The actor reports that it ran a command; the
        # command's own exit code says whether the script worked. A script that
        # ran and failed can be repaired; a refusal cannot, and is not retried.
        failed_by_exit = kind == "acted" and code not in (0, None)
        return kind == "acted" and not failed_by_exit, text, failed_by_exit

    def _repair(self, *, brief: str, files: list, run_text: str, attempt: int,
                rules: str, entry: str) -> list:
        """A script that ran and failed goes back to the implementer with its own
        error, the way a person reads the traceback and fixes the line. Returns
        the names written; empty when nothing usable came back."""
        shown = "\n\n".join(
            f"# file: {n}\n{(self.dir / n).read_text(encoding='utf-8', errors='replace')[:6000]}"
            for n in files if (self.dir / n).is_file())
        ok, code_text = self._ask("implementer", (
            f"{brief}\n\nThese files were run and {entry} failed.\n\nFiles:\n{shown[:12000]}\n\n"
            f"What running it printed:\n{run_text[:5000]}\n\nFix the cause. {rules} Reply with each "
            "file that changes as its own code block whose FIRST LINE is `# file: <name>`, and nothing else."))
        blocks = [(h, c) for h, c in _code_blocks(code_text) if h] if ok else []
        if not blocks:
            path = self._write(f"repair-{attempt}.md", code_text or "")
            self._step(f"repair {attempt}", "failed", (code_text or "no files came back")[:200], path)
            return []
        names = []
        for h, c in blocks:
            name = pathlib.PurePosixPath(h).name  # the first write's rule: no directories, no escapes
            (self.dir / name).write_text(c, encoding="utf-8")
            names.append(name)
        self._step(f"repair {attempt}", "ok", ", ".join(names), str(self.dir))
        return names

    # --------------------------------------------------------------- research
    def research(self) -> None:
        q = self.title
        ok, text = self._ask("scholar", f"Research question: {q}\n\nReview the literature and report as instructed.")
        urls = _URL.findall(text) if ok else []
        if not ok or not urls:
            path = self._write("sources.md", text or "(no answer)")
            self._step("scholar", "failed", (text[:200] if not ok else "no URL in the review; a claim without a source is not a finding"), path)
            self._finish("unsupported", "the literature step produced no sources, so nothing downstream was written (INV-EVID-2)")
            return
        src_path = self._write("sources.md", text)
        self._step("scholar", "ok", f"{len(set(urls))} source URL(s)", src_path)

        ok, plan = self._ask("drafter", (
            f"Research question: {q}\n\nLiterature review (with sources):\n{text[:9000]}\n\n"
            "Write (1) two or three testable hypotheses, (2) ONE small experiment that can run "
            "on a laptop in under 60 seconds using only the Python 3.9 standard library, no network, "
            "no installs, printing numbers that bear on the hypotheses, (3) what result would "
            "support or refute each hypothesis. Be concrete about the algorithm and the data it generates."))
        if not ok:
            path = self._write("plan.md", plan)
            self._step("drafter", "failed", plan[:200], path)
            self._finish("failed", "no experiment plan")
            return
        plan_path = self._write("plan.md", plan)
        self._step("drafter", "ok", "hypotheses and one runnable experiment", plan_path)

        ok, code_text = self._ask("implementer", (
            f"Plan:\n{plan[:9000]}\n\nWrite the experiment as ONE self-contained Python 3.9 script, "
            "standard library only, no network, deterministic (seed it), finishing in under 60 "
            "seconds, printing its results as plain lines. Reply with a single ```python code block "
            "whose first line is `# file: experiment.py`, and nothing else."))
        blocks = [c for h, c in _code_blocks(code_text)] if ok else []
        if not ok or not blocks or "print" not in blocks[0]:
            path = self._write("implementer.md", code_text)
            self._step("implementer", "failed", "no runnable script came back", path)
            self._finish("failed", "no experiment script")
            return
        script = self.dir / "experiment.py"
        script.write_text(blocks[0], encoding="utf-8")
        self._step("implementer", "ok", f"{len(blocks[0].splitlines())} lines", str(script))

        ran, run_text, repairable = self._run_script(script, "the experiment")
        run_path = self._write("run.md", run_text)
        self._step("run", "ok" if ran else "failed", ("executed through the actor" if ran else run_text[:200]), run_path)
        for attempt in range(1, MAX_REPAIRS + 1):
            if ran or not repairable:
                break
            if not self._repair(brief=f"Plan:\n{plan[:6000]}", files=["experiment.py"], run_text=run_text,
                                attempt=attempt, entry="experiment.py",
                                rules=("Keep the file named experiment.py. Python 3.9 standard library only, "
                                       "no network, deterministic (seeded), finishing in under 60 seconds, "
                                       "printing its results as plain lines.")):
                break
            ran, run_text, repairable = self._run_script(script, "the experiment, repaired")
            run_path = self._write(f"run-{attempt + 1}.md", run_text)
            self._step(f"run {attempt + 1}", "ok" if ran else "failed",
                       ("executed through the actor" if ran else run_text[:200]), run_path)
        if not ran:
            self._finish("failed", "the experiment did not execute; no findings are written for a run that did not happen")
            return

        ok, findings = self._ask("auditor", (
            f"Research question: {q}\n\nSources (with URLs):\n{text[:6000]}\n\nPlan:\n{plan[:4000]}\n\n"
            f"What actually ran and printed:\n{run_text[:6000]}\n\n"
            "Write the findings: what the run showed, how it bears on each hypothesis, what it does "
            "NOT show, and what a real study would need next. Cite the sources by URL where you rely "
            "on them. Do not claim anything the run output does not support."))
        if not ok or not _URL.findall(findings):
            path = self._write("findings-draft.md", findings)
            self._step("auditor", "failed", "findings without a cited source are not written as findings", path)
            self._finish("unsupported", "the findings step cited no source")
            return
        f_path = self._write("findings.md", findings)
        self._step("auditor", "ok", "findings with sources", f_path)
        self._finish("done", findings[:600])

    # ---------------------------------------------------------------- project
    def project(self) -> None:
        g = self.title
        ok, where = self._ask("navigator", (
            f"Goal: {g}\n\nSay, briefly, what such a project needs: the files, the entry point, and "
            "how it would be run and checked on a laptop with the Python 3.9 standard library only."))
        w_path = self._write("where.md", where)
        self._step("navigator", "ok" if ok else "failed", where[:120], w_path)

        ok, code_text = self._ask("implementer", (
            f"Goal: {g}\n\nNotes:\n{where[:4000] if ok else ''}\n\nWrite the project as files. Python 3.9 "
            "standard library only, no network, no installs. Give each file as its own ```python (or "
            "```text) code block whose FIRST LINE is `# file: <name>`; include an entry point named "
            "main.py that runs in under 90 seconds, prints what it did and exits 0. Nothing else in the reply."))
        blocks = [(h, c) for h, c in _code_blocks(code_text) if h] if ok else []
        # THE GATE AND THE WRITER MUST READ THE HEADER THE SAME WAY, and they did
        # not. The writer below takes `PurePosixPath(h).name`, so a block headed
        # `# file: char_lm_run/main.py` lands as `main.py` -- while this line
        # compared the WHOLE header and declared the reply had no entry point.
        # Two language-model project runs failed as "no files with a main.py came
        # back" (2026-09-14 18:11, 2026-09-15 09:10) against replies that both
        # contained one, in a directory. The agent is following a perfectly
        # ordinary convention; the disagreement was ours.
        names_given = {pathlib.PurePosixPath(h).name for h, _ in blocks}
        if not ok or "main.py" not in names_given:
            path = self._write("implementer.md", code_text)
            self._step("implementer", "failed", "no files with a main.py came back", path)
            self._finish("failed", "no project files")
            return
        written = []
        for h, c in blocks:
            name = pathlib.PurePosixPath(h).name           # no directories, no escapes
            (self.dir / name).write_text(c, encoding="utf-8")
            written.append(name)
        self._step("implementer", "ok", ", ".join(written), str(self.dir))

        ran, run_text, repairable = self._run_script(self.dir / "main.py", "the project's entry point")
        run_path = self._write("run.md", run_text)
        self._step("run", "ok" if ran else "failed", ("executed through the actor" if ran else run_text[:200]), run_path)
        for attempt in range(1, MAX_REPAIRS + 1):
            if ran or not repairable:
                break
            names = self._repair(brief=f"Goal: {g}", files=written, run_text=run_text, attempt=attempt,
                                 entry="main.py",
                                 rules=("Python 3.9 standard library only, no network, no installs; main.py "
                                        "runs in under 90 seconds, prints what it did and exits 0."))
            if not names:
                break
            written = sorted(set(written) | set(names))
            ran, run_text, repairable = self._run_script(self.dir / "main.py", "the project's entry point, repaired")
            run_path = self._write(f"run-{attempt + 1}.md", run_text)
            self._step(f"run {attempt + 1}", "ok" if ran else "failed",
                       ("executed through the actor" if ran else run_text[:200]), run_path)

        ok, report = self._ask("auditor", (
            f"Goal: {g}\n\nFiles written: {', '.join(written)}\n\nWhat running main.py did:\n{run_text[:6000]}\n\n"
            "Report: what works as shown by the run, what did not, what is unverified, and the next step. "
            "Do not claim anything the run output does not support."))
        r_path = self._write("report.md", report if ok else f"(no report: {report})")
        self._step("auditor", "ok" if ok else "failed", report[:120], r_path)
        self._finish("done" if ran else "failed",
                     (report[:600] if ok else "no report") if ran else "the entry point did not execute")

    def run(self) -> None:
        try:
            (self.research if self.kind == RESEARCH else self.project)()
        except Exception as exc:                          # noqa: BLE001
            self._step("workflow", "failed", f"{type(exc).__name__}: {exc}")
            self._finish("failed", f"{type(exc).__name__}: {exc}")


def _claude_binary() -> str | None:
    import shutil
    for cand in (shutil.which("claude"), str(pathlib.Path.home() / ".local" / "bin" / "claude"),
                 "/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
        if cand and pathlib.Path(cand).exists():
            return cand
    return None


def _agents_config_dir() -> str | None:
    """The account the agents share, never the owner's own.

    AND "NEVER THE OWNER'S OWN" WAS NOT TRUE UNTIL 2026-09-14. This read
    `VESPER_CLAUDE_CONFIG_DIR` out of `secrets.env`; that key is not on this
    machine; and the None it returned is not "no account" -- it is the CLI's
    DEFAULT account, which here is the owner's personal one. Every research and
    project run was spending the owner's own subscription while this docstring
    said the opposite, and nothing could see it because an absent fallback looks
    like an omission rather than a choice of whose subscription to spend.
    `core/claude_limits.py` resolves the secret first and the contract second.
    """
    try:
        from core import claude_limits
        return claude_limits.default().config_dir(claude_limits.AGENTS)
    except Exception:                                     # noqa: BLE001
        return None


def start(kind: str, title: str, *, runner: Any, act: Callable[[str], Any] | None,
          bus: Any = None, workdir: pathlib.Path | None = None,
          status_path: pathlib.Path | None = None, background: bool = True,
          config_dir: str | None = None, binary: str | None = None,
          timeout_s: float = STEP_TIMEOUT_S) -> dict:
    """Start a run. Background by default: agents take minutes and the pump must
    not wait for them."""
    if runner is None:
        raise WorkflowRefused("no agent runner; the workflow has nobody to ask")
    wf = Workflow(kind, title, runner=runner, act=act, bus=bus, workdir=workdir,
                  status_path=status_path,
                  config_dir=config_dir if config_dir is not None else _agents_config_dir(),
                  binary=binary if binary is not None else _claude_binary(),
                  timeout_s=timeout_s)
    if background:
        threading.Thread(target=wf.run, name=f"workflow-{wf.id}", daemon=True).start()
    else:
        wf.run()
    return {"id": wf.id, "dir": str(wf.dir), "status": wf.status}
