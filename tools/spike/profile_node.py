#!/usr/bin/env python3
"""SPIKE-001 measurement harness.

Implements the protocol in docs/spikes/SPIKE-001-node-capability-profiles.md
on whichever machine it is run on: throughput (3.1), memory headroom (3.2),
storage (3.3). Stdlib only, no pip install, so it runs unmodified on every
candidate compute node (Windows desktop, Kali laptop) without a setup step.

HARD RULE, mirrored from contracts/policy/capability_profiles.toml: this
script NEVER writes an enforced contract file. It only ever produces a dated
JSON report under docs/planning/spike-results/. Transcribing a MEASURED
figure into capability_profiles.toml is a separate, reviewed step -- CI-034
guards that file, and this script has no path to it, deliberately.

Every figure this script cannot actually measure is recorded as null with a
"reason" string. Never guessed. Never carried over from a different run or a
different machine. A --quick run is explicitly marked non-conclusive and must
never be transcribed as a SPIKE-001 result.

RUNNER: llama.cpp's llama-server over HTTP (schema_version 2). Ollama was the
original target and was removed from the fabric on 2026-08-13 -- it does not
accelerate properly on this node's AMD card, and llama.cpp's Vulkan backend is
what actually runs there.

This harness does NOT start the server, deliberately. The launch flags -- -ngl,
-fa, --cache-type-k/v, --parallel, context size -- ARE the configuration under
test, so they belong to the operator and are recorded verbatim via
--launch-command. A throughput number without them is not reproducible.

    llama-server.exe -m <model.gguf> -ngl 99 -fa --port 8080
    python profile_node.py throughput --launch-command "<that exact line>"

Set VESPER_LLAMA_SERVER to point at a non-default address.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

# 3 (2026-08-14): throughput switched to a STREAMING request with ignore_eos, so
# checkpoints fire on the wall clock instead of on request returns. Reports at
# schema_version 2 and 3 are NOT directly comparable at `strong`, where the old
# sampling aliased; at `draft`/`standard`, where requests returned every few
# seconds, they are. See docs/planning/spike-results/README.md Finding 4.
#
# 4 (2026-08-14): the two headline aggregates are now taken over the SAME window.
# v3 reported minute-10 generation against a whole-run-average wall rate; see
# Finding 6. UNLIKE the 2->3 bump, v3 and v4 ARE comparable: the measurement
# method is identical and only the aggregation changed, so a v3 report can be
# re-aggregated from its own run_results without re-measuring. That is what was
# done rather than spending another six hours on the matrix.
SCHEMA_VERSION = 4
LLAMA_SERVER_URL = os.environ.get("VESPER_LLAMA_SERVER", "http://127.0.0.1:8080")
REPORT_DIR = Path(__file__).resolve().parents[2] / "docs" / "planning" / "spike-results"

# The four tiers of contracts/entities/model_profile.schema.json capability_tier.
# `strong` is the one SR-009 routes to for hard work; SPIKE-001 3.1 omitted it, so
# it could never leave UNKNOWN. Values are the tier's expected generation length
# per request, NOT the model -- the tier-representative model is the operator's
# choice and is recorded through --launch-command.
TIER_CONTEXT_TOKENS = {"draft": 256, "small": 1024, "standard": 4096, "strong": 8192}
BENCH_PROMPT = (
    "Write a detailed, technical explanation of how a persistent event bus "
    "with hybrid logical clocks orders writes across multiple unreliable "
    "network nodes, covering supersession, epoch fencing, and partition "
    "recovery. Be thorough and specific."
)
# Deliberately generous. Used only to reserve prompt room when checking a tier's
# generation length against the server's -c, so erring high fails safe.
_BENCH_PROMPT_TOKENS_EST = 128


# --------------------------------------------------------------------------- system facts


def _ram_gb() -> tuple[float | None, str | None]:
    system = platform.system()
    if system == "Windows":
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return None, "GlobalMemoryStatusEx failed"
            return round(stat.ullTotalPhys / (1024**3), 2), None
        except Exception as e:  # noqa: BLE001
            return None, f"ctypes RAM query failed: {e}"
    elif system == "Linux":
        try:
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return round(kb / (1024**2), 2), None
        except Exception as e:  # noqa: BLE001
            return None, f"/proc/meminfo read failed: {e}"
        return None, "MemTotal not found in /proc/meminfo"
    elif system == "Darwin":
        try:
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, check=True)
            return round(int(out.stdout.strip()) / (1024**3), 2), None
        except Exception as e:  # noqa: BLE001
            return None, f"sysctl hw.memsize failed: {e}"
    return None, f"unsupported platform: {system}"


def _ram_available_gb() -> tuple[float | None, str | None]:
    system = platform.system()
    if system == "Windows":
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return None, "GlobalMemoryStatusEx failed"
            return round(stat.ullAvailPhys / (1024**3), 2), None
        except Exception as e:  # noqa: BLE001
            return None, f"ctypes RAM query failed: {e}"
    elif system == "Linux":
        try:
            fields = {}
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    k, _, v = line.partition(":")
                    fields[k.strip()] = v.strip()
            if "MemAvailable" in fields:
                kb = int(fields["MemAvailable"].split()[0])
                return round(kb / (1024**2), 2), None
            return None, "MemAvailable not present (old kernel)"
        except Exception as e:  # noqa: BLE001
            return None, f"/proc/meminfo read failed: {e}"
    return None, f"unsupported platform: {system}"


def _swap_active() -> tuple[bool | None, str | None]:
    """Best-effort: is the system actively swapping right now (a point-in-time read,
    not a during-test monitor -- see NOTE in measure_storage)."""
    system = platform.system()
    if system == "Linux":
        try:
            out = subprocess.run(["vmstat", "1", "2"], capture_output=True, text=True, timeout=5, check=True)
            last = out.stdout.strip().splitlines()[-1].split()
            si, so = int(last[6]), int(last[7])
            return (si > 0 or so > 0), None
        except Exception as e:  # noqa: BLE001
            return None, f"vmstat unavailable: {e}"
    if system == "Windows":
        try:
            ps = (
                "(Get-Counter '\\Paging File(_Total)\\% Usage').CounterSamples.CookedValue"
            )
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, timeout=10, check=True,
            )
            pct = float(out.stdout.strip())
            return (pct > 5.0), None
        except Exception as e:  # noqa: BLE001
            return None, f"Get-Counter paging file unavailable: {e}"
    return None, f"unsupported platform: {system}"


def _gpu_name() -> tuple[str | None, str | None]:
    """Hardware NAME for our own bookkeeping in this report only. Never write a
    product name into an enforced contract (INV-HW-1, CI-007) -- this field
    exists so a human reads the report and knows what ran, nothing more."""
    system = platform.system()
    try:
        if system == "Windows":
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_VideoController | Select-Object -First 1 -ExpandProperty Name)"],
                capture_output=True, text=True, timeout=10, check=True,
            )
            name = out.stdout.strip()
            return (name or None), None
        elif system == "Linux":
            out = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5, check=True)
            for line in out.stdout.splitlines():
                if "VGA" in line or "3D controller" in line:
                    return line.split(":", 2)[-1].strip(), None
            return None, "no VGA/3D controller line in lspci"
    except Exception as e:  # noqa: BLE001
        return None, f"GPU query failed: {e}"
    return None, f"unsupported platform: {system}"


def detect_system() -> dict:
    ram_gb, ram_err = _ram_gb()
    disk_total, disk_free = shutil.disk_usage(Path.cwd())[0], shutil.disk_usage(Path.cwd())[2]
    gpu_name, gpu_err = _gpu_name()
    return {
        "os_family": platform.system(),
        "os_version": platform.version(),
        "hostname_hint": platform.node(),
        "cpu_cores_logical": os.cpu_count(),
        "ram_gb": ram_gb,
        "ram_gb_error": ram_err,
        "disk_total_gb": round(disk_total / (1024**3), 1),
        "disk_free_gb": round(disk_free / (1024**3), 1),
        "gpu_name_hint": gpu_name,
        "gpu_name_error": gpu_err,
        "python_version": platform.python_version(),
    }


# --------------------------------------------------------------------------- model runner


def detect_runner() -> dict:
    """Probe a RUNNING llama-server. This harness deliberately does NOT start the
    server: the launch flags (-ngl, -fa, --cache-type-k/v, --parallel, context
    size) ARE the configuration under test, so they belong to the operator and
    get recorded in the report rather than being invented here."""
    info: dict = {"backend": "llama.cpp/llama-server", "url": LLAMA_SERVER_URL}
    try:
        req = urllib.request.Request(f"{LLAMA_SERVER_URL}/health")
        with urllib.request.urlopen(req, timeout=3) as resp:
            health = json.loads(resp.read() or b"{}")
    except (urllib.error.URLError, OSError) as e:
        info.update({
            "available": False,
            "reason": (
                f"no llama-server reachable at {LLAMA_SERVER_URL}: {e}. "
                "Start it first; set VESPER_LLAMA_SERVER to override the address."
            ),
        })
        return info

    info["available"] = True
    info["health"] = health
    try:
        req = urllib.request.Request(f"{LLAMA_SERVER_URL}/props")
        with urllib.request.urlopen(req, timeout=5) as resp:
            props = json.loads(resp.read())
        gen = props.get("default_generation_settings", {}) or {}
        info["model_path"] = props.get("model_path")
        info["build_info"] = props.get("build_info")
        info["n_ctx"] = gen.get("n_ctx") or props.get("n_ctx")
        info["total_slots"] = props.get("total_slots")
        info["server_props"] = props
    except (urllib.error.URLError, OSError, ValueError) as e:
        info["props_error"] = f"/props unavailable: {e}"
    return info


def _llama_generate(prompt: str, n_predict: int, timeout: float = 600) -> dict:
    """POST /completion, non-streaming. Retained for the warm-up only.

    NOT used for measurement any more. See _llama_stream and the note on
    _single_throughput_run: a non-streaming request advances the token count
    only when it RETURNS, which makes every derived rate a function of where
    request boundaries happen to fall."""
    body = json.dumps({
        "prompt": prompt,
        "n_predict": n_predict,
        "stream": False,
        "cache_prompt": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{LLAMA_SERVER_URL}/completion", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _llama_stream(prompt: str, n_predict: int, timeout: float):
    """POST /completion with stream=true, yielding one item per token as it
    arrives. This is what makes wall-clock sampling possible at all.

    TWO REASONS THIS REPLACED THE NON-STREAMING PATH, both found on 2026-08-14
    by asking why the `strong` tier's spread was three times every other tier's:

    1. SAMPLING. A non-streaming request advances the token count only when it
       returns. At `strong` one request runs 625-1137 s -- longer than the whole
       10-minute window -- so a single return crossed two or three checkpoint
       boundaries and every interval collapsed into whichever one it landed on.
       The three published MoE figures came from three DIFFERENT checkpoints,
       and one of them was the MINUTE-1 value, which is the single figure §3.1
       names and forbids. Streaming advances the count continuously, so a
       checkpoint fires on the clock rather than on a request boundary.

    2. GENERATION TIME WITHOUT PROMPT EVAL. Accumulating inter-token intervals
       gives generation-only time directly, and does so for an ABORTED request
       too. The old path could only read `timings` from a completed response,
       so a request still running at the deadline contributed nothing -- which
       at `strong`, where a full request outlasts the window, is every request.

    `ignore_eos` is sent so a request lasts the tier's declared length instead
    of however long the model chooses to talk. Without it, no `strong` run ever
    reached n_predict: the dense candidate stopped at 2064-2520 tokens against a
    declared 8192, so the tier measured the model's natural answer length rather
    than the tier's."""
    body = json.dumps({
        "prompt": prompt,
        "n_predict": n_predict,
        "stream": True,
        "cache_prompt": False,
        # SPIKE-001 §3.1 fixes the GENERATION LENGTH per tier. A model that
        # stops early makes the tier argument inert -- the same defect class as
        # the 512-token cap removed on 2026-08-13, arriving by a different road.
        "ignore_eos": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{LLAMA_SERVER_URL}/completion", data=body,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                yield json.loads(payload)
            except json.JSONDecodeError:
                continue


def _gpu_in_use(runner: dict) -> tuple[bool | None, str | None]:
    """Did generation actually run on the accelerator? llama-server exposes no
    endpoint that reports the CPU/GPU layer split, so this CANNOT be determined
    over HTTP. Returns None with a reason rather than inferring it from the
    presence of a GPU -- INV-HW-2 forbids declaring what was not measured.

    The operator resolves it by recording the launch flags (-ngl) and the
    server's own startup log, both of which state the offload explicitly."""
    del runner  # no HTTP path to this fact; kept for signature stability
    return None, (
        "llama-server exposes no CPU/GPU split over HTTP. Verify from the "
        "server startup log ('load_tensors: offloaded N/N layers to GPU') and "
        "record the -ngl flag used, in runner.launch_command."
    )


# --------------------------------------------------------------------------- concurrent load


class _BackgroundLoad:
    """Synthetic concurrent load standing in for the resource governor, world
    model and persistence layer running alongside inference (SPIKE-001 §3.1,
    'concurrent-load variant, mandatory'). CPU-bound busy work plus a held
    memory allocation that is actually touched, so it cannot be optimised away
    and cannot be satisfied from cache alone."""

    def __init__(self, n_threads: int | None = None, hold_mb: int = 512):
        self._stop = threading.Event()
        self._threads = [threading.Thread(target=self._burn, daemon=True)
                          for _ in range(n_threads or max(1, (os.cpu_count() or 2) // 2))]
        self._hold_mb = hold_mb
        self._buf = None

    def _burn(self):
        x = 0.0001
        while not self._stop.is_set():
            for _ in range(200_000):
                x = (x * 1.0000001 + 1) % 999983

    def __enter__(self):
        self._buf = bytearray(self._hold_mb * 1024 * 1024)
        for i in range(0, len(self._buf), 4096):
            self._buf[i] = 1
        for t in self._threads:
            t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2)
        self._buf = None


# --------------------------------------------------------------------------- throughput


def _single_throughput_run(tier: str, minutes: float, checkpoints_min: list[float],
                           server_n_ctx: int | None = None) -> dict:
    ctx_tokens = TIER_CONTEXT_TOKENS.get(tier, 1024)

    # SPIKE-001 3.1 step 3: generate "at the tier's expected context length". An
    # earlier version capped every request at min(ctx_tokens, 512), which made the
    # tier argument inert above 256 -- `small` and `standard` produced byte-identical
    # request shapes and differed only by which model the operator had loaded. The
    # cap is gone; the constraint it was hiding is now checked and reported instead.
    if server_n_ctx is not None:
        headroom = server_n_ctx - _BENCH_PROMPT_TOKENS_EST
        if ctx_tokens > headroom:
            return {
                "error": (
                    f"tier '{tier}' asks for {ctx_tokens} generated tokens but the server "
                    f"was launched with -c {server_n_ctx}, leaving ~{headroom} after the "
                    f"benchmark prompt. Relaunch llama-server with a larger -c. Refusing to "
                    f"measure a truncated run and report it as a sustained figure."
                ),
                "required_min_n_ctx": ctx_tokens + _BENCH_PROMPT_TOKENS_EST,
            }

    try:
        _llama_generate(BENCH_PROMPT, n_predict=200)  # warm-up, discarded
    except (urllib.error.URLError, OSError) as e:
        return {"error": f"warm-up request failed: {e}"}

    start = time.monotonic()
    cumulative_tokens = 0
    # Generation-only seconds, accumulated as the sum of INTER-TOKEN intervals.
    # The gap before a request's first token carries prompt eval and connection
    # setup and is deliberately excluded, which is the same boundary the old
    # `timings.predicted_ms` drew -- but computed continuously, so an aborted
    # request contributes its real generation time instead of nothing.
    cumulative_gen_s = 0.0
    prompt_gaps_s = []
    samples = []
    requests_started = 0
    requests_completed = 0
    next_checkpoint_idx = 0
    deadline = start + minutes * 60
    # Interval accounting: each checkpoint reports the rate achieved SINCE the
    # previous one, so a hot minute-10 figure is not diluted by a cold minute-1.
    last_tokens = 0
    last_gen_s = 0.0
    last_wall = 0.0

    # Per-request timeout scales with ctx_tokens rather than sitting at a fixed
    # 600 s: `strong`'s 8192-token requests need ~775 s at this node's ~10.5
    # tok/s, which is exactly what silently dropped 2 of 3 runs on the first
    # strong-tier pass. Floor of 2 tok/s, generously below anything observed.
    req_timeout = max(600.0, ctx_tokens / 2.0 + 60.0)

    def _fire_checkpoints(now: float) -> None:
        """Fire every checkpoint whose wall-clock time has passed. Called after
        EVERY token, so a checkpoint lands within one token of its true time
        rather than whenever a request happens to return."""
        nonlocal next_checkpoint_idx, last_tokens, last_gen_s, last_wall
        elapsed_min = (now - start) / 60.0
        while (next_checkpoint_idx < len(checkpoints_min)
               and elapsed_min >= checkpoints_min[next_checkpoint_idx]):
            d_tok = cumulative_tokens - last_tokens
            d_gen = cumulative_gen_s - last_gen_s
            d_wall = (now - start) - last_wall
            samples.append({
                "minute": checkpoints_min[next_checkpoint_idx],
                # Generation-time rate -- the figure §3.1 names.
                "interval_tokens_per_sec": round(d_tok / d_gen, 2) if d_gen > 0 else None,
                # Wall-clock rate -- the figure the router must use.
                "interval_effective_tokens_per_sec": (
                    round(d_tok / d_wall, 2) if d_wall > 0 else None),
                "cumulative_tokens_per_sec": (
                    round(cumulative_tokens / cumulative_gen_s, 2)
                    if cumulative_gen_s > 0 else None),
                "interval_tokens": d_tok,
            })
            last_tokens = cumulative_tokens
            last_gen_s = cumulative_gen_s
            last_wall = now - start
            next_checkpoint_idx += 1

    while time.monotonic() < deadline:
        requests_started += 1
        req_start = time.monotonic()
        prev_tok_t = None
        aborted = False
        try:
            for chunk in _llama_stream(BENCH_PROMPT, ctx_tokens, req_timeout):
                now = time.monotonic()
                if chunk.get("content"):
                    if prev_tok_t is None:
                        # First token: the interval since req_start is prompt
                        # eval, not generation. Recorded separately, never
                        # folded into the generation figure.
                        prompt_gaps_s.append(now - req_start)
                    else:
                        cumulative_gen_s += now - prev_tok_t
                    prev_tok_t = now
                    cumulative_tokens += 1
                    _fire_checkpoints(now)
                if chunk.get("stop"):
                    requests_completed += 1
                    break
                if now >= deadline:
                    # Abort mid-request. The window is 10 minutes of measurement,
                    # and at `strong` a full request outlasts it -- so honouring
                    # the window means cutting the request, not the reverse.
                    aborted = True
                    break
        except (urllib.error.URLError, OSError) as e:
            return {"error": f"generation request failed: {e}", "partial_samples": samples}
        if aborted:
            break

    # Any checkpoint not reached by real elapsed time is still emitted, so the
    # sample array's shape does not depend on how fast the machine was.
    _fire_checkpoints(time.monotonic())

    if cumulative_gen_s <= 0:
        return {"error": "no generation time accumulated"}

    # SPIKE-001 §3.1: sustained := the LAST interval's rate (the machine as it is
    # once hot), not the cumulative average, which is flattered by the cold start.
    #
    # The final checkpoint is now guaranteed non-empty, because checkpoints fire
    # on the clock rather than on request returns. Before 2026-08-14 an interval
    # could contain zero returned requests and yield None, and `sustained` then
    # silently fell back to an EARLIER checkpoint -- which is how a published
    # `strong` figure came to be the minute-1 value that §3.1 explicitly forbids.
    final_interval = next(
        (s["interval_tokens_per_sec"] for s in reversed(samples)
         if s.get("interval_tokens_per_sec") is not None), None,
    )
    final_effective = next(
        (s["interval_effective_tokens_per_sec"] for s in reversed(samples)
         if s.get("interval_effective_tokens_per_sec") is not None), None,
    )
    # Which checkpoint did `sustained` actually come from? Recorded, not assumed.
    # If this is ever not the last checkpoint, the figure is not the minute-N
    # value its name implies, and the reader must be able to see that.
    sustained_from = next(
        (s["minute"] for s in reversed(samples)
         if s.get("interval_tokens_per_sec") is not None), None,
    )
    wall = time.monotonic() - start
    return {
        "samples": samples,
        "sustained_tokens_per_sec": final_interval,
        "sustained_from_checkpoint_minute": sustained_from,
        "sustained_is_final_checkpoint": (
            bool(samples) and sustained_from == samples[-1]["minute"]),
        "cumulative_tokens_per_sec": round(cumulative_tokens / cumulative_gen_s, 2),
        # Tokens delivered per second of WALL CLOCK, not per second of server-side
        # generation time. The difference is everything the machine spends outside
        # the accelerator -- scheduling, HTTP, tokenisation, client overhead -- and
        # that is precisely what the concurrent-load variant exists to detect.
        # Measured 2026-08-13: under concurrent load, sustained_tokens_per_sec moved
        # -0.29% while this figure moved -11.05%. Reporting only the first would
        # have said contention costs nothing, which is false.
        "effective_tokens_per_sec": round(cumulative_tokens / wall, 2) if wall > 0 else None,
        "sustained_effective_tokens_per_sec": final_effective,
        "total_tokens": cumulative_tokens,
        "wall_seconds": round(wall, 1),
        "generation_seconds": round(cumulative_gen_s, 1),
        # Prompt-eval and connection setup, excluded from the generation figure
        # and reported so the exclusion is visible rather than merely asserted.
        "prompt_eval_seconds_per_request": [round(g, 3) for g in prompt_gaps_s],
        "requests_started": requests_started,
        "requests_completed": requests_completed,
        # At `strong` a full 8192-token request outlasts the 10-minute window, so
        # requests_completed = 0 is the CORRECT outcome, not a failure. Recorded
        # because a reader comparing tiers needs to know the difference.
        "final_request_aborted_at_deadline": requests_started > requests_completed,
        "ignore_eos": True,
        "tier_generation_length": ctx_tokens,
    }


def measure_throughput(runner: dict, tier: str, minutes: float, runs: int, concurrent: bool, quick: bool) -> dict:
    checkpoints = [1.0, 5.0, minutes] if minutes >= 5 else [minutes]
    checkpoints = sorted(set(c for c in checkpoints if c <= minutes))

    gpu_used, gpu_reason = _gpu_in_use(runner)
    run_results = []
    for _ in range(runs):
        if concurrent:
            with _BackgroundLoad():
                r = _single_throughput_run(tier, minutes, checkpoints, runner.get("n_ctx"))
        else:
            r = _single_throughput_run(tier, minutes, checkpoints, runner.get("n_ctx"))
        run_results.append(r)

    # THE TWO HEADLINE FIGURES MUST BE TAKEN OVER THE SAME WINDOW. Schema v3
    # aggregated the minute-10 generation rate against the WHOLE-RUN average
    # wall rate, so the two columns of the published matrix described different
    # windows. On a flat config that is invisible (they agreed within 1%); on
    # the MoE, which loses ~45% across a run, the reported wall figure came out
    # 27% above the settled rate -- 8.63 tok/s against a true 6.79. Both are
    # aggregated at minute 10 now, and the whole-run average is kept under a
    # name that says what it is.
    def _vals(key):
        return [r[key] for r in run_results if r.get(key) is not None]

    sustained_values = _vals("sustained_tokens_per_sec")            # minute 10, generation clock
    effective_values = _vals("sustained_effective_tokens_per_sec")  # minute 10, wall clock
    whole_run_values = _vals("effective_tokens_per_sec")            # entire run, wall clock

    result = {
        "tier": tier,
        "model_path": runner.get("model_path"),
        "build_info": runner.get("build_info"),
        "server_n_ctx": runner.get("n_ctx"),
        "minutes_per_run": minutes,
        "runs": runs,
        "concurrent_load": concurrent,
        "quick_mode": quick,
        "gpu_in_use": gpu_used,
        "gpu_in_use_reason": gpu_reason,
        "run_results": run_results,
    }
    if sustained_values:
        result["median_sustained_tokens_per_sec"] = round(statistics.median(sustained_values), 2)
        result["spread_tokens_per_sec"] = {
            "min": round(min(sustained_values), 2),
            "max": round(max(sustained_values), 2),
            "values": sustained_values,
        }
    if effective_values:
        result["median_effective_tokens_per_sec"] = round(statistics.median(effective_values), 2)
        result["spread_effective_tokens_per_sec"] = {
            "min": round(min(effective_values), 2),
            "max": round(max(effective_values), 2),
            "values": effective_values,
        }
        result["effective_window"] = (
            "minute 10 -- the same window as median_sustained_tokens_per_sec, so the "
            "two are comparable to each other."
        )
        result["router_should_use"] = (
            "median_effective_tokens_per_sec — it is wall-clock and therefore sees "
            "contention that median_sustained_tokens_per_sec, being generation-time "
            "only, is blind to."
        )
    if whole_run_values:
        # Kept because it is the honest answer to "how many tokens did the node
        # actually produce in ten minutes", which is a different question from
        # "what rate had it settled to". For a decaying model the two diverge,
        # and a router that plans capacity wants the settled one.
        result["median_whole_run_effective_tokens_per_sec"] = round(
            statistics.median(whole_run_values), 2)
        result["spread_whole_run_effective_tokens_per_sec"] = {
            "min": round(min(whole_run_values), 2),
            "max": round(max(whole_run_values), 2),
            "values": whole_run_values,
        }
        result["whole_run_vs_settled_note"] = (
            "median_whole_run_effective_tokens_per_sec averages the entire run, "
            "including the fast early minutes. It is ABOVE the settled rate by "
            "however much the model decays. Do not quote it as a sustained figure."
        )
    else:
        result["median_sustained_tokens_per_sec"] = None
        result["reason"] = "no run produced a sustained figure -- see run_results errors"
    return result


# --------------------------------------------------------------------------- memory / storage


def measure_memory() -> dict:
    total, total_err = _ram_gb()
    avail, avail_err = _ram_available_gb()
    return {
        "total_gb": total, "total_gb_error": total_err,
        "available_gb_now": avail, "available_gb_error": avail_err,
        "note": (
            "'available_gb_now' is a point-in-time OS reading, not the SPIKE-001 "
            "protocol figure. The protocol wants headroom measured WITH the "
            "owner's real working set loaded (browser, editor, whatever they "
            "actually run) -- run this again while that is actually open, and "
            "record both."
        ),
    }


def measure_storage(path: str, size_mb: int = 512) -> dict:
    target_dir = Path(path)
    target_dir.mkdir(parents=True, exist_ok=True)
    test_file = target_dir / ".vesper_spike001_storage_test.bin"
    chunk = os.urandom(1024 * 1024)

    swap_before, swap_before_err = _swap_active()

    t0 = time.monotonic()
    with open(test_file, "wb") as f:
        for _ in range(size_mb):
            f.write(chunk)
        f.flush()
        os.fsync(f.fileno())
    seq_write_s = time.monotonic() - t0
    seq_mbps = size_mb / seq_write_s if seq_write_s > 0 else None

    t0 = time.monotonic()
    n_random = 2000
    block = os.urandom(4096)
    with open(test_file, "r+b") as f:
        file_size = size_mb * 1024 * 1024
        for i in range(n_random):
            off = (i * 7919) % max(1, file_size - 4096)
            f.seek(off)
            f.write(block)
        f.flush()
        os.fsync(f.fileno())
    rand_write_s = time.monotonic() - t0
    rand_iops = n_random / rand_write_s if rand_write_s > 0 else None

    swap_after, swap_after_err = _swap_active()

    try:
        test_file.unlink()
    except OSError:
        pass

    total, free = shutil.disk_usage(target_dir)[0], shutil.disk_usage(target_dir)[2]

    return {
        "path": str(target_dir),
        "disk_total_gb": round(total / (1024**3), 1),
        "disk_free_gb": round(free / (1024**3), 1),
        "sequential_write_mbps": round(seq_mbps, 1) if seq_mbps else None,
        "random_4k_write_iops": round(rand_iops, 1) if rand_iops else None,
        "swap_active_before": swap_before, "swap_active_before_error": swap_before_err,
        "swap_active_after": swap_after, "swap_active_after_error": swap_after_err,
        "note": (
            "swap_active is a point-in-time sample immediately before/after, not "
            "a continuous monitor across the full 10-minute run the protocol "
            "asks for. Treat a positive reading as meaningful; treat a negative "
            "reading as inconclusive, not as proof of zero swap activity."
        ),
    }


# --------------------------------------------------------------------------- report


def write_report(report: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    host = report.get("system", {}).get("hostname_hint", "node").replace(" ", "_")
    out = REPORT_DIR / f"{host}-{stamp}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out


# --------------------------------------------------------------------------- CLI


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["system", "runner", "throughput", "memory", "storage", "full"])
    p.add_argument("--launch-command", default=None,
                    help="the exact llama-server command line under test. Recorded verbatim in "
                         "the report -- the -ngl/-fa/--cache-type flags ARE the configuration "
                         "being measured, and a throughput figure without them is unreproducible.")
    p.add_argument("--tier", default="small", choices=list(TIER_CONTEXT_TOKENS))
    p.add_argument("--minutes", type=float, default=10.0)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--concurrent", action="store_true")
    p.add_argument("--quick", action="store_true",
                    help="short pilot run to validate the harness. NEVER a SPIKE-001 result.")
    p.add_argument("--storage-path", default=".")
    p.add_argument("--out", default=None, help="write JSON report to this path instead of the default location")
    args = p.parse_args()

    if args.quick:
        args.minutes = min(args.minutes, 1.0)
        args.runs = min(args.runs, 1)

    report: dict = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "spike": "SPIKE-001",
        "quick_mode": args.quick,
        "system": detect_system(),
    }

    def _runner() -> dict:
        r = detect_runner()
        if args.launch_command:
            r["launch_command"] = args.launch_command
        else:
            r["launch_command"] = None
            r["launch_command_warning"] = (
                "--launch-command not given. The server's -ngl/-fa/--cache-type flags are "
                "the configuration under test; without them this figure is not reproducible "
                "and MUST NOT be transcribed into capability_profiles.toml."
            )
        return r

    if args.command == "system":
        pass
    elif args.command == "runner":
        report["runner"] = _runner()
    elif args.command == "memory":
        report["memory"] = measure_memory()
    elif args.command == "storage":
        report["storage"] = measure_storage(args.storage_path)
    elif args.command == "throughput":
        runner = _runner()
        report["runner"] = runner
        if not runner["available"]:
            report["throughput"] = {"median_sustained_tokens_per_sec": None, "reason": runner["reason"]}
        else:
            report["throughput"] = measure_throughput(
                runner, args.tier, args.minutes, args.runs, args.concurrent, args.quick,
            )
    elif args.command == "full":
        runner = _runner()
        report["runner"] = runner
        report["memory"] = measure_memory()
        report["storage"] = measure_storage(args.storage_path)
        if runner["available"]:
            report["throughput_idle"] = measure_throughput(
                runner, args.tier, args.minutes, args.runs, concurrent=False, quick=args.quick,
            )
            report["throughput_concurrent"] = measure_throughput(
                runner, args.tier, args.minutes, args.runs, concurrent=True, quick=args.quick,
            )
        else:
            report["throughput_idle"] = {
                "median_sustained_tokens_per_sec": None,
                "reason": runner["reason"],
            }

    if args.quick and any(k.startswith("throughput") for k in report):
        report["QUICK_MODE_WARNING"] = (
            "This run used --quick. Figures here are for validating the harness "
            "only and MUST NOT be transcribed into capability_profiles.toml. "
            "SPIKE-001 requires the full 10-minute x 3-run protocol."
        )

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    else:
        out_path = write_report(report)
    print(json.dumps(report, indent=2))
    print(f"\nReport written to: {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
