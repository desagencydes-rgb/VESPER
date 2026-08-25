#!/usr/bin/env python3
"""SPIKE-015 -- can one small local model do VESPER's front-end work, and what
does it cost this host to run it? Stdlib only.

WHAT THIS IS FOR. The small tier is being re-decided. Published benchmarks rank
models against each other on tasks nobody here will run; what is not published,
and what actually decides this, is whether a candidate holds up on VESPER's own
work ON THIS HOST without making the machine unpleasant to use. There is no
tokens/sec figure for any candidate on this silicon anywhere -- that was
checked, not assumed -- so it has to be measured.

THREE RULES THIS FILE FOLLOWS.

1. THE HARNESS DOES NOT GRADE TASTE. Every answer is recorded in full so a
   human can read it. Automatic verdicts are only issued where a check is
   objective: did the tool call parse and name the right function, did the
   arithmetic come out right, did the needle come back out of the haystack, did
   the generated code pass its asserts. "Was the prose good" is not scored,
   because a harness that scores it is a harness that can be tuned until it
   likes the answer.

2. SPEED IS MEASURED THREE WAYS AND THEY ARE NOT INTERCHANGEABLE. The server's
   own `predicted_per_second` is the model's rate. Wall clock includes the
   client, the transport and the queue. And for a THINKING model the number
   that decides whether it can hold a conversation is neither: it is time to
   the first token the user is actually shown, because reasoning tokens are
   never spoken and never displayed. A thinking model can be fast by every
   published measure and still leave a four-second silence before it says
   anything.

3. THE MACHINE'S COMFORT IS A PASS CRITERION, NOT A FOOTNOTE. The owner asked
   for a model that stays invisible until you go looking for it. So the guard
   below samples the host throughout and ABORTS the run when the machine starts
   to suffer -- an abort is a result, and the alternative is discovering the
   cost after cooking the laptop for an hour.

NO SUDO. Battery temperature, amperage, thermal warnings and the memory
pressure band are all readable without it. `powermetrics` would give more and
needs root, so it stays in SPIKE-013 where the owner drives it.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# BATTERY TEMPERATURE WAS THE WRONG SENSOR, and trusting it produced a false
# all-clear that the owner corrected from across the room.
#
# Measured 2026-08-25: across four runs this sensor moved 30.6 -> 30.96 C and
# the harness reported "heat is a non-issue". The owner reported the machine
# hot and the battery down ~30% in minutes. The owner was right. The battery is
# a large thermal mass at the base of the chassis; it lags the SoC by many
# minutes and barely responds to a compute burst at all. A die at 90 C and a
# battery at 31 C are the same reading on this instrument.
#
# POWER IS THE HONEST PROXY AND IT NEEDS NO SUDO. Watts are the CAUSE of both
# symptoms -- the heat and the drain -- and the pack reports them directly:
#
#     idle, nothing loaded      5.1 W
#     model loaded, idle       14.8 W      <- 3x idle to be merely AVAILABLE
#     generating               34 - 41 W   <- 6-8x idle, near-identical for
#                                             a 1.7B and a 4B
#
# Temperature is still recorded, and is still NOT graded. A sensor worth
# logging is not the same as a sensor worth gating on.
TEMP_ABSOLUTE_ABORT_C = 42.0
TEMP_RISE_ABORT_C = 12.0

# Sustained draw that means the machine is working hard enough to be felt.
# Set from the measurements above: idle is ~5 W, generation is ~35-40 W, so a
# sustained figure above this is the model and nothing else.
POWER_SUSTAINED_ABORT_W = 45.0
# kern.memorystatus_level is a BAND, not a size -- a smaller number means more
# pressure. Recorded because a model that swaps has stopped being lightweight
# whatever its token rate says.
MEMORY_BAND_ABORT = 25


def _sh(cmd: list, timeout: float = 10.0) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.stdout
    except Exception:
        return ""


def _s64(v: int) -> int:
    """ioreg reports signed values as unsigned 64-bit. Convert back.

    Without this a discharging battery reads as 1.8e19 mA, which is not a
    plausible current and would sail through any threshold written for one.
    """
    return v - (1 << 64) if v >= (1 << 63) else v


class HostGuard:
    """Samples the host while the model runs, and calls a stop when it hurts."""

    def __init__(self, interval: float = 5.0) -> None:
        self.interval = interval
        self.samples: list[dict] = []
        self.aborted: str | None = None
        self.baseline_temp_c: float | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def sample(self) -> dict:
        out = _sh(["ioreg", "-rc", "AppleSmartBattery"])
        temp = amp = cap = None
        m = re.search(r'"Temperature"\s*=\s*(\d+)', out)
        if m:
            temp = int(m.group(1)) / 100.0
        m = re.search(r'"InstantAmperage"\s*=\s*(\d+)', out)
        if m:
            amp = _s64(int(m.group(1)))
        volt = None
        m = re.search(r'"Voltage"\s*=\s*(\d+)', out)
        if m:
            volt = int(m.group(1))
        m = re.search(r'"CurrentCapacity"\s*=\s*(\d+)', out)
        if m:
            cap = int(m.group(1))
        band = _sh(["sysctl", "-n", "kern.memorystatus_level"]).strip()
        load = _sh(["sysctl", "-n", "vm.loadavg"]).strip()
        therm = _sh(["pmset", "-g", "therm"])
        warned = "warning level" in therm and "No thermal warning" not in therm
        # Watts, from the pack's own current and voltage. Recorded on every
        # sample because it is the figure that explains both the heat and the
        # drain, and the first version of this file collected the amperage and
        # then never used it.
        watts = (abs(amp) * volt / 1e6) if (amp is not None and volt) else None
        s = {
            "t": time.time(),
            "battery_temp_c": temp,
            "power_watts": round(watts, 1) if watts else None,
            "instant_amperage_ma": amp,
            "voltage_mv": volt,
            "charge_percent": cap,
            "memory_band": int(band) if band.isdigit() else None,
            "loadavg": load,
            "thermal_warning": warned,
        }
        self.samples.append(s)
        return s

    def _check(self, s: dict) -> None:
        if self.aborted:
            return
        t = s.get("battery_temp_c")
        if t is not None:
            if self.baseline_temp_c is None:
                self.baseline_temp_c = t
            if t >= TEMP_ABSOLUTE_ABORT_C:
                self.aborted = (f"battery temperature {t:.1f}C reached the "
                                f"{TEMP_ABSOLUTE_ABORT_C}C abort threshold")
            elif t - self.baseline_temp_c >= TEMP_RISE_ABORT_C:
                self.aborted = (f"battery temperature rose {t - self.baseline_temp_c:.1f}C "
                                f"above the {self.baseline_temp_c:.1f}C baseline")
        w = s.get("power_watts")
        if w is not None and w >= POWER_SUSTAINED_ABORT_W:
            self.aborted = (f"sustained draw {w:.1f} W against a ~5 W idle. "
                            "This is what the owner feels as heat, and what "
                            "empties the battery; the temperature sensor does "
                            "not see it for several minutes.")
        if s.get("thermal_warning"):
            self.aborted = "the OS recorded a thermal or performance warning level"
        b = s.get("memory_band")
        if b is not None and b <= MEMORY_BAND_ABORT:
            self.aborted = (f"memory pressure band fell to {b} -- a model that "
                            "pushes the owner's working set out is not lightweight")

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self._check(self.sample())

    def start(self) -> None:
        self._check(self.sample())
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._check(self.sample())

    def summary(self) -> dict:
        temps = [s["battery_temp_c"] for s in self.samples if s["battery_temp_c"]]
        watts = [s["power_watts"] for s in self.samples if s.get("power_watts")]
        amps = [s["instant_amperage_ma"] for s in self.samples
                if s["instant_amperage_ma"] is not None]
        caps = [s["charge_percent"] for s in self.samples if s["charge_percent"]]
        bands = [s["memory_band"] for s in self.samples if s["memory_band"]]
        # THE WORST SAMPLE GOVERNS, not the mean. A mean hides the minute the
        # machine was unusable, and that minute is the whole question here.
        return {
            "samples": len(self.samples),
            "power_watts": {"median": sorted(watts)[len(watts)//2] if watts else None,
                            "peak": max(watts) if watts else None,
                            "idle_reference_w": 5.1},
            "battery_temp_c": {"start": temps[0] if temps else None,
                               "peak": max(temps) if temps else None,
                               "end": temps[-1] if temps else None},
            "instant_amperage_ma": {"peak_draw": min(amps) if amps else None,
                                    "median": sorted(amps)[len(amps) // 2] if amps else None},
            "charge_percent": {"start": caps[0] if caps else None,
                               "end": caps[-1] if caps else None,
                               "used": (caps[0] - caps[-1]) if len(caps) > 1 else None},
            "memory_band": {"start": bands[0] if bands else None,
                            "worst": min(bands) if bands else None},
            "aborted": self.aborted,
        }


class Endpoint:
    """The model under test, over the OpenAI-compatible route."""

    def __init__(self, base_url: str, model: str = "local") -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def props(self) -> dict:
        try:
            with urllib.request.urlopen(f"{self.base_url}/props", timeout=10) as r:
                return json.loads(r.read())
        except Exception as e:
            return {"error": str(e)}

    def chat(self, messages: list, max_tokens: int = 512,
             tools: list | None = None, timeout: float = 300.0) -> dict:
        body = {"model": self.model, "messages": messages,
                "max_tokens": max_tokens, "temperature": 0.7, "stream": True}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json"})

        # STREAMED, because the number that matters cannot be measured any
        # other way. A non-streamed call gives one timestamp at the end, and
        # time-to-first-VISIBLE-token -- the pause the user actually sits
        # through while a thinking model reasons -- is invisible in it.
        t0 = time.time()
        t_first_any = t_first_visible = None
        reasoning = []
        content = []
        tool_acc: dict = {}
        finish = None
        usage = {}
        timings = {}
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                for raw in r:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        d = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if d.get("timings"):
                        timings = d["timings"]
                    if d.get("usage"):
                        usage = d["usage"]
                    for ch in d.get("choices") or []:
                        delta = ch.get("delta") or {}
                        if ch.get("finish_reason"):
                            finish = ch["finish_reason"]
                        rc = delta.get("reasoning_content")
                        if rc:
                            t_first_any = t_first_any or time.time()
                            reasoning.append(rc)
                        c = delta.get("content")
                        if c:
                            t_first_any = t_first_any or time.time()
                            t_first_visible = t_first_visible or time.time()
                            content.append(c)
                        # TOOL CALL ARGUMENTS ARRIVE IN FRAGMENTS, keyed by
                        # index, and must be concatenated. Appending each delta
                        # as its own call reads the arguments as just "{" and
                        # scores a perfectly good call as a failure -- which is
                        # what the first run of this harness did to the
                        # baseline model, on the axis that decides the whole
                        # question. The bug flattered nothing; it condemned.
                        for tc in delta.get("tool_calls") or []:
                            idx = tc.get("index", 0)
                            slot = tool_acc.setdefault(
                                idx, {"id": None,
                                      "function": {"name": "", "arguments": ""}})
                            if tc.get("id"):
                                slot["id"] = tc["id"]
                            f = tc.get("function") or {}
                            if f.get("name"):
                                slot["function"]["name"] += f["name"]
                            if f.get("arguments"):
                                slot["function"]["arguments"] += f["arguments"]
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}",
                    "wall_seconds": time.time() - t0}

        t_end = time.time()
        tool_calls = [tool_acc[k] for k in sorted(tool_acc)]
        text = "".join(content)
        think = "".join(reasoning)
        # Some builds inline the reasoning in <think> tags rather than sending
        # reasoning_content. Both are handled: a thinking budget that is
        # invisible to the harness would flatter the model on exactly the axis
        # this test exists to measure.
        if not think:
            m = re.search(r"<think>(.*?)</think>", text, re.S)
            if m:
                think = m.group(1)
                text = (text[:m.start()] + text[m.end():]).strip()
        return {
            "text": text,
            "reasoning": think,
            "tool_calls": tool_calls,
            "finish_reason": finish,
            "usage": usage,
            "timings": timings,
            "wall_seconds": t_end - t0,
            "ttft_any_seconds": (t_first_any - t0) if t_first_any else None,
            "ttft_visible_seconds": (t_first_visible - t0) if t_first_visible else None,
            "server_tokens_per_sec": timings.get("predicted_per_second"),
            "tokens_predicted": timings.get("predicted_n") or usage.get("completion_tokens"),
            "tokens_evaluated": timings.get("prompt_n") or usage.get("prompt_tokens"),
        }


def image_message(text: str, image_path: Path) -> list:
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    suffix = image_path.suffix.lower().lstrip(".")
    mime = "image/jpeg" if suffix in ("jpg", "jpeg") else f"image/{suffix}"
    return [{"role": "user", "content": [
        {"type": "text", "text": text},
        {"type": "image_url",
         "image_url": {"url": f"data:{mime};base64,{b64}"}}]}]


# ---------------------------------------------------------------- the checks

def check_contains_all(answer: str, needles: list) -> tuple[bool, str]:
    low = answer.lower()
    missing = [n for n in needles if n.lower() not in low]
    return (not missing), ("all present" if not missing else f"missing: {missing}")


def check_number(answer: str, expected: float, tol: float = 0.001) -> tuple[bool, str]:
    nums = [float(x.replace(",", "")) for x in
            re.findall(r"-?\d[\d,]*\.?\d*", answer.replace("$", ""))]
    hit = any(abs(n - expected) <= tol for n in nums)
    return hit, (f"found {expected}" if hit else f"expected {expected}, saw {nums[:12]}")


def check_tool_call(result: dict, fn: str, arg_needles: list) -> tuple[bool, str]:
    """Objective: did a parseable call to the RIGHT function come back?

    Accepts both the structured tool_calls channel and a JSON object in the
    text, because a model that emits a correct call in prose has demonstrated
    the capability even if the plumbing did not classify it -- and the
    difference between those two is a template problem, not a model one.
    """
    calls = result.get("tool_calls") or []
    for c in calls:
        f = (c.get("function") or {})
        name = f.get("name") or ""
        args = f.get("arguments") or ""
        if fn in name:
            ok, why = check_contains_all(str(args), arg_needles)
            return ok, f"structured call {name}({args[:120]}) -- {why}"
    blob = result.get("text", "") + result.get("reasoning", "")
    if fn in blob:
        ok, why = check_contains_all(blob, arg_needles)
        return ok, f"named {fn} in text only (not structured) -- {why}"
    return False, f"no call to {fn}; tool_calls={len(calls)}"


def check_code_runs(answer: str, harness: str) -> tuple[bool, str]:
    """Extract a python block, run it with asserts, in a subprocess with a cap."""
    m = re.search(r"```(?:python)?\s*(.*?)```", answer, re.S)
    code = m.group(1) if m else answer
    prog = code + "\n\n" + harness
    try:
        p = subprocess.run([sys.executable, "-c", prog],
                           capture_output=True, text=True, timeout=20)
        return p.returncode == 0, (p.stderr.strip().splitlines()[-1][:160]
                                   if p.returncode else "asserts passed")
    except subprocess.TimeoutExpired:
        return False, "generated code did not terminate in 20s"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def build_needle_haystack(depth: int = 220) -> tuple[str, str]:
    """A long-context test with a verifiable answer.

    Filler is drawn from the repo's own prose rather than lorem ipsum: a model
    that can find a fact in unrelated noise has proved less than one that can
    find it in text that reads like everything else around it.
    """
    src = (REPO / "docs" / "source" / "HANDWRITTEN_TRANSCRIPTION.txt")
    body = src.read_text(encoding="utf-8", errors="replace") if src.exists() else ""
    lines = [l for l in body.splitlines() if l.strip()]
    filler = (lines * 40)[:depth]
    secret = "The fabric's reattestation cadence for a Z1 node is 37 hours."
    filler.insert(len(filler) // 2, secret)
    return ("\n".join(filler),
            "How many hours is the reattestation cadence for a Z1 node, "
            "according to the document? Answer with the number only.")


def suite(assets: dict, budget_scale: float = 1.0) -> list:
    """Every axis the owner named, one test each, with a check where possible."""
    haystack, needle_q = build_needle_haystack()
    tests: list = []

    def add(name, axis, messages, *, max_tokens=512, tools=None, check=None,
            note=""):
        # THE BUDGET IS SCALED IN ONE PLACE. A reasoning model spends its
        # budget thinking FIRST, so a cap sized for an instruct model returns
        # finish_reason "length" with an empty answer and the test records a
        # capability failure that never happened. Every per-test number below
        # is the visible-answer budget; `budget_scale` buys the thinking room.
        tests.append({"name": name, "axis": axis, "messages": messages,
                      "max_tokens": int(max_tokens * budget_scale),
                      "tools": tools, "check": check, "note": note})

    add("conversation", "conversation",
        [{"role": "user", "content":
          "In two sentences, and without a preamble, tell me what you are."}],
        max_tokens=400,
        note="Latency of the FIRST VISIBLE token is the figure that matters here.")

    add("arithmetic_reasoning", "thinking",
        [{"role": "user", "content":
          "A node sustains 45.8 tokens/sec. Speech needs 3.25 tokens/sec to "
          "keep up. How many concurrent speech streams can it feed at 2x "
          "safety margin? Give the integer only."}],
        max_tokens=900, check=lambda r: check_number(r["text"], 7))

    add("science_reasoning", "research",
        [{"role": "user", "content":
          "A 4B parameter model at Q4_K_M quantisation uses roughly 0.55 bytes "
          "per parameter for weights. Estimate the weight memory in GB, then "
          "say what ELSE consumes memory at inference time. Be specific."}],
        max_tokens=1200,
        check=lambda r: check_contains_all(r["text"], ["kv", "context"]))

    add("coding", "coding",
        [{"role": "user", "content":
          "Write a Python function `hlc_compare(a, b)` where a and b are "
          "tuples (physical_ms, logical, node_id). Return -1, 0 or 1 ordering "
          "by physical_ms, then logical, then node_id lexicographically. "
          "Return ONLY a python code block."}],
        max_tokens=1400,
        check=lambda r: check_code_runs(r["text"], """
assert hlc_compare((1,0,'a'), (2,0,'a')) == -1
assert hlc_compare((2,0,'a'), (1,0,'a')) == 1
assert hlc_compare((1,1,'a'), (1,0,'a')) == 1
assert hlc_compare((1,0,'a'), (1,0,'b')) == -1
assert hlc_compare((1,0,'a'), (1,0,'a')) == 0
"""))

    add("tool_call_single", "self_action",
        [{"role": "system", "content":
          "You have tools. When a tool applies, call it rather than answering."},
         {"role": "user", "content":
          "What is the battery level on node nd_macbook right now?"}],
        max_tokens=700,
        tools=[{"type": "function", "function": {
            "name": "get_node_metric",
            "description": "Read a live metric from an enrolled node.",
            "parameters": {"type": "object", "properties": {
                "node_id": {"type": "string"},
                "metric": {"type": "string",
                           "enum": ["battery", "cpu", "memory", "tokens_per_sec"]}},
                "required": ["node_id", "metric"]}}}],
        check=lambda r: check_tool_call(r, "get_node_metric",
                                        ["nd_macbook", "battery"]))

    add("tool_call_multi_turn", "self_action",
        [{"role": "system", "content":
          "You have tools. Call them one at a time and use earlier results."},
         {"role": "user", "content":
          "Check the battery on nd_macbook, and if it is under 80 percent, "
          "queue a task called 'defer_heavy_work'. Start now."},
         {"role": "assistant", "content": None,
          "tool_calls": [{"id": "c1", "type": "function", "function": {
              "name": "get_node_metric",
              "arguments": '{"node_id":"nd_macbook","metric":"battery"}'}}]},
         {"role": "tool", "tool_call_id": "c1", "content": '{"battery": 74}'}],
        max_tokens=700,
        tools=[{"type": "function", "function": {
            "name": "get_node_metric",
            "description": "Read a live metric from an enrolled node.",
            "parameters": {"type": "object", "properties": {
                "node_id": {"type": "string"}, "metric": {"type": "string"}},
                "required": ["node_id", "metric"]}}},
            {"type": "function", "function": {
                "name": "queue_task",
                "description": "Queue a task by name.",
                "parameters": {"type": "object", "properties": {
                    "name": {"type": "string"}}, "required": ["name"]}}}],
        check=lambda r: check_tool_call(r, "queue_task", ["defer_heavy_work"]),
        note="BFCL multi-turn is where small models collapse. This is the test "
             "that matters most for the autonomy loop.")

    add("long_context_needle", "large_dataset",
        [{"role": "user", "content": haystack + "\n\n" + needle_q}],
        max_tokens=300, check=lambda r: check_number(r["text"], 37),
        note="Verifiable retrieval from a long document of same-register prose.")

    if assets.get("handwriting"):
        add("handwriting_ocr", "report_reading",
            image_message(
                "This is a page of handwritten engineering notes. Transcribe "
                "the readable text as faithfully as you can.",
                assets["handwriting"]),
            max_tokens=1600,
            check=lambda r: check_contains_all(
                r["text"], ["api", "model"]),
            note="Hardest OCR case there is, and it is the project's own source "
                 "corpus. Ground truth: docs/source/HANDWRITTEN_TRANSCRIPTION.txt")

    if assets.get("ui"):
        add("ui_reading", "ui_reading",
            image_message(
                "This is a screenshot of an application interface. List every "
                "text label and every number you can read, then say what the "
                "interface is showing.",
                assets["ui"]),
            max_tokens=1200,
            note="Scored by reading it. VESPER must read ITS OWN surface.")

    if assets.get("screen"):
        add("live_screen_reading", "ui_action",
            image_message(
                "This is a live screenshot of a desktop. Describe what "
                "application is in focus and what the user appears to be "
                "doing. Then name one concrete UI element you would click to "
                "scroll the frontmost window, and where it is.",
                assets["screen"]),
            max_tokens=1000,
            note="The UI-action path: perceive, then propose an action.")

    if assets.get("design"):
        add("image_understanding", "image_reading",
            image_message(
                "Describe this image: its subject, palette, mood, and any "
                "text. Be concrete and brief.",
                assets["design"]),
            max_tokens=800)

    return tests


def gather_assets(shot_dir: Path) -> dict:
    a: dict = {}
    hw = REPO / "docs" / "source" / "handwritten-pages" / "1.jpeg"
    if hw.exists():
        a["handwriting"] = hw
    ui = REPO / "docs" / "design" / "ui-refs" / "island-expanded-instruments.png"
    if ui.exists():
        a["ui"] = ui
    dz = REPO / "docs" / "design" / "assets" / "wallpapers" / "thinking.png"
    if dz.exists():
        a["design"] = dz
    # A REAL screenshot, not a stored one: UI reading is worthless if it only
    # works on pictures chosen in advance.
    shot = shot_dir / "screen.png"
    shot_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["screencapture", "-x", "-t", "png", str(shot)],
                   capture_output=True, timeout=30)
    if shot.exists() and shot.stat().st_size > 0:
        a["screen"] = shot
    return a


def main(argv: list) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--base-url", default="http://127.0.0.1:8080")
    p.add_argument("--label", required=True,
                   help="what is being tested, e.g. qwen3vl-4b-thinking-q4km")
    p.add_argument("--out-dir", type=Path,
                   default=REPO / "docs" / "planning" / "spike-results")
    p.add_argument("--only", default=None, help="substring filter on test name")
    p.add_argument("--guard-interval", type=float, default=5.0)
    p.add_argument("--budget-scale", type=float, default=1.0,
                   help="multiply every token budget. A thinking model needs "
                        "roughly 3-4x an instruct model's, because the "
                        "reasoning is spent before the answer starts.")
    p.add_argument("--repeat", type=int, default=1,
                   help="repeat the whole suite N times (endurance)")
    a = p.parse_args(argv[1:])

    ep = Endpoint(a.base_url)
    props = ep.props()
    if "error" in props:
        print(f"REFUSED: no endpoint at {a.base_url}: {props['error']}",
              file=sys.stderr)
        print("A capability result with no server behind it is not a result.",
              file=sys.stderr)
        return 2

    modalities = props.get("modalities") or {}
    print(f"endpoint   {a.base_url}")
    print(f"model      {props.get('model_path')}")
    print(f"slots      {props.get('total_slots')}   modalities {modalities}")
    print("")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    assets = gather_assets(a.out_dir / "spike015-assets")
    print(f"assets     {{{', '.join(sorted(assets))}}}")
    if not modalities.get("vision"):
        print("           NOTE: endpoint reports vision=false. Image tests will")
        print("           be attempted anyway and are expected to fail -- an")
        print("           untried assumption is how the last one got missed.")
    print("")

    guard = HostGuard(interval=a.guard_interval)
    guard.start()
    results: list = []
    tests = suite(assets, a.budget_scale)
    if a.only:
        tests = [t for t in tests if a.only in t["name"]]

    try:
        for cycle in range(a.repeat):
            for t in tests:
                if guard.aborted:
                    break
                started = time.time()
                r = ep.chat(t["messages"], max_tokens=t["max_tokens"],
                            tools=t["tools"])
                verdict = why = None
                # BUDGET EXHAUSTION IS NOT A WRONG ANSWER. When the cap lands
                # mid-thought the server returns "length" with an empty answer.
                # Scoring that as a failed capability blames the model for the
                # harness's cap -- MEMORY.md 4h recorded this trap against a
                # live endpoint, and the first run of this file walked into it
                # on two tests and called them failures.
                budget_exhausted = (r.get("finish_reason") == "length"
                                    and not (r.get("text") or "").strip())
                if budget_exhausted:
                    verdict, why = None, (
                        f"BUDGET EXHAUSTED -- all {r.get('tokens_predicted')} "
                        "tokens went to reasoning, no answer emitted. Not a "
                        "capability result; raise --budget-scale.")
                elif t["check"] and "error" not in r:
                    try:
                        verdict, why = t["check"](r)
                    except Exception as e:
                        verdict, why = False, f"check raised {type(e).__name__}: {e}"
                think_chars = len(r.get("reasoning") or "")
                row = {
                    "cycle": cycle, "name": t["name"], "axis": t["axis"],
                    "note": t["note"],
                    "wall_seconds": round(r.get("wall_seconds") or 0, 2),
                    "ttft_visible_seconds": (round(r["ttft_visible_seconds"], 2)
                                             if r.get("ttft_visible_seconds") else None),
                    "ttft_any_seconds": (round(r["ttft_any_seconds"], 2)
                                         if r.get("ttft_any_seconds") else None),
                    "server_tokens_per_sec": r.get("server_tokens_per_sec"),
                    "tokens_predicted": r.get("tokens_predicted"),
                    "tokens_evaluated": r.get("tokens_evaluated"),
                    "reasoning_chars": think_chars,
                    "finish_reason": r.get("finish_reason"),
                    "verdict": verdict, "verdict_detail": why,
                    "budget_exhausted": budget_exhausted,
                    "error": r.get("error"),
                    "answer": r.get("text"),
                    "reasoning": r.get("reasoning"),
                    "host_at_end": guard.samples[-1] if guard.samples else None,
                }
                results.append(row)
                mark = ("ERROR" if r.get("error") else
                        "BUDGT" if budget_exhausted else
                        "  -  " if verdict is None else
                        " PASS" if verdict else " FAIL")
                tv = row["ttft_visible_seconds"]
                print(f"[{mark}] {t['name']:24} "
                      f"{row['wall_seconds']:6.1f}s wall  "
                      f"ttft_vis {tv if tv is not None else '   -':>5}  "
                      f"{(row['server_tokens_per_sec'] or 0):6.1f} tok/s  "
                      f"think {think_chars:5}ch  {(row['finish_reason'] or '-'):6}"
                      + (f"  [{why}]" if why else "")
                      + (f"  {r['error']}" if r.get("error") else ""))
                if guard.aborted:
                    break
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
    finally:
        guard.stop()

    host = guard.summary()
    report = {
        "schema_version": 1,
        "spike": "SPIKE-015",
        "label": a.label,
        "generated_at_utc": stamp,
        "endpoint": {"base_url": a.base_url,
                     "model_path": props.get("model_path"),
                     "total_slots": props.get("total_slots"),
                     "modalities": modalities,
                     "chat_template_has_tools": "tools" in str(props.get("chat_template", ""))},
        "assets": {k: str(v.relative_to(REPO)) if str(v).startswith(str(REPO))
                   else str(v) for k, v in assets.items()},
        "host": host,
        "results": results,
    }
    out = a.out_dir / f"SPIKE-015-{a.label}-{stamp}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("")
    print(f"  power          median {host['power_watts']['median']} W, "
          f"peak {host['power_watts']['peak']} W  (idle reference 5.1 W)")
    print(f"  battery temp   {host['battery_temp_c']['start']} -> "
          f"peak {host['battery_temp_c']['peak']} -> {host['battery_temp_c']['end']} C")
    print(f"  charge         {host['charge_percent']['start']} -> "
          f"{host['charge_percent']['end']} %  (used {host['charge_percent']['used']})")
    print(f"  memory band    {host['memory_band']['start']} -> "
          f"worst {host['memory_band']['worst']}")
    if host["aborted"]:
        print(f"  ABORTED: {host['aborted']}")
    print(f"\n  report  {out}")
    # An abort is a RESULT and must not look like a pass to a caller.
    return 3 if host["aborted"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
