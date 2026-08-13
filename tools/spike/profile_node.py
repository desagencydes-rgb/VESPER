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

SCHEMA_VERSION = 2
LLAMA_SERVER_URL = os.environ.get("VESPER_LLAMA_SERVER", "http://127.0.0.1:8080")
REPORT_DIR = Path(__file__).resolve().parents[2] / "docs" / "planning" / "spike-results"

TIER_CONTEXT_TOKENS = {"draft": 256, "small": 1024, "standard": 4096}
BENCH_PROMPT = (
    "Write a detailed, technical explanation of how a persistent event bus "
    "with hybrid logical clocks orders writes across multiple unreliable "
    "network nodes, covering supersession, epoch fencing, and partition "
    "recovery. Be thorough and specific."
)


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


def _llama_generate(prompt: str, n_predict: int) -> dict:
    """POST /completion. llama-server returns a `timings` block carrying
    predicted_n and predicted_ms -- the generation-only figures. Prompt-eval
    time is reported separately and is deliberately NOT folded in: SPIKE-001
    §3.1 measures generation throughput."""
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
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read())


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


def _single_throughput_run(tier: str, minutes: float, checkpoints_min: list[float]) -> dict:
    ctx_tokens = TIER_CONTEXT_TOKENS.get(tier, 1024)

    try:
        _llama_generate(BENCH_PROMPT, n_predict=200)  # warm-up, discarded
    except (urllib.error.URLError, OSError) as e:
        return {"error": f"warm-up request failed: {e}"}

    start = time.monotonic()
    cumulative_tokens = 0
    cumulative_predict_ms = 0.0
    samples = []
    next_checkpoint_idx = 0
    deadline = start + minutes * 60
    # Interval accounting: each checkpoint reports the rate achieved SINCE the
    # previous one, so a hot minute-10 figure is not diluted by a cold minute-1.
    last_tokens = 0
    last_predict_ms = 0.0

    while time.monotonic() < deadline:
        try:
            resp = _llama_generate(BENCH_PROMPT, n_predict=min(ctx_tokens, 512))
        except (urllib.error.URLError, OSError) as e:
            return {"error": f"generation request failed: {e}", "partial_samples": samples}
        timings = resp.get("timings") or {}
        if "predicted_n" not in timings or "predicted_ms" not in timings:
            return {"error": "llama-server response carried no timings block", "partial_samples": samples}
        cumulative_tokens += timings["predicted_n"]
        cumulative_predict_ms += timings["predicted_ms"]
        elapsed_min = (time.monotonic() - start) / 60.0

        while next_checkpoint_idx < len(checkpoints_min) and elapsed_min >= checkpoints_min[next_checkpoint_idx]:
            d_tok = cumulative_tokens - last_tokens
            d_ms = cumulative_predict_ms - last_predict_ms
            samples.append({
                "minute": checkpoints_min[next_checkpoint_idx],
                "interval_tokens_per_sec": round(d_tok / (d_ms / 1000.0), 2) if d_ms > 0 else None,
                "cumulative_tokens_per_sec": (
                    round(cumulative_tokens / (cumulative_predict_ms / 1000.0), 2)
                    if cumulative_predict_ms > 0 else None
                ),
            })
            last_tokens, last_predict_ms = cumulative_tokens, cumulative_predict_ms
            next_checkpoint_idx += 1

    if cumulative_predict_ms <= 0:
        return {"error": "no generation time accumulated"}

    # SPIKE-001 §3.1: sustained := the LAST interval's rate (the machine as it is
    # once hot), not the cumulative average, which is flattered by the cold start.
    final_interval = next(
        (s["interval_tokens_per_sec"] for s in reversed(samples)
         if s.get("interval_tokens_per_sec") is not None), None,
    )
    return {
        "samples": samples,
        "sustained_tokens_per_sec": final_interval,
        "cumulative_tokens_per_sec": round(cumulative_tokens / (cumulative_predict_ms / 1000.0), 2),
        "total_tokens": cumulative_tokens,
        "wall_seconds": round(time.monotonic() - start, 1),
    }


def measure_throughput(runner: dict, tier: str, minutes: float, runs: int, concurrent: bool, quick: bool) -> dict:
    checkpoints = [1.0, 5.0, minutes] if minutes >= 5 else [minutes]
    checkpoints = sorted(set(c for c in checkpoints if c <= minutes))

    gpu_used, gpu_reason = _gpu_in_use(runner)
    run_results = []
    for _ in range(runs):
        if concurrent:
            with _BackgroundLoad():
                r = _single_throughput_run(tier, minutes, checkpoints)
        else:
            r = _single_throughput_run(tier, minutes, checkpoints)
        run_results.append(r)

    sustained_values = [
        r["sustained_tokens_per_sec"] for r in run_results
        if r.get("sustained_tokens_per_sec") is not None
    ]
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
