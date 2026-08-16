#!/usr/bin/env python3
"""Energy and MAD cost of the A-029 endurance run, tracked live.

WHAT THIS IS AND IS NOT. This machine exposes no power sensor -- no battery, no
`Win32_PowerMeter`, no vendor sensor daemon -- so **nothing here is measured at
the wall**. Wattage is MODELLED from CPU utilisation against declared idle and
full-load figures, and every artifact this writes says `ESTIMATED` rather than
carrying a number that looks like a reading. The corpus already draws this line
in `core/config.py` (measured-vs-declared provenance); a cost report that
quietly presented a model as a measurement would be the same failure in a new
place.

To turn the estimate into a measurement, put a plug-in energy meter between the
PC and the socket and pass its reading to `--wall-watts`. That is the only thing
that makes this exact, and it costs about 100-200 MAD once.

TWO NUMBERS, AND CONFLATING THEM IS THE WHOLE TRAP. "What does the 24 h run
cost?" has two honest answers and they differ by four orders of magnitude:

  * The MARGINAL cost of the run -- what VESPER added. The process wakes once a
    minute and used 1.7 s of CPU in its first 1.78 h. This is effectively zero,
    and it is the number that answers "is this run expensive?"

  * The cost of the MACHINE BEING ON for 24 h -- which you would pay for any
    reason the PC is on, and which the run did not cause. The PC had already
    been up 13.2 h when the run started.

Both are reported. Presenting only the second would blame the run for the
desktop's existence; presenting only the first would hide the real electricity
bill.

    python tools/ops/power_cost.py --track      # sample until the run ends, then report
    python tools/ops/power_cost.py --report     # report on what has been sampled so far
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import psutil
except ImportError:                                    # pragma: no cover
    psutil = None

REPO = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------
# DECLARED INPUTS. Every one of these is a stated assumption, not a reading.
# --------------------------------------------------------------------------

# ONEE basse tension, usage domestique. Tranches are monthly kWh bands.
# Retrieved 2026-08-16 from https://kherba.com/tarifs, which lists them as
# TVA-inclusive. These five figures (0.9010 / 1.0732 / 1.1676 / 1.3817 /
# 1.5958) are the long-standing published ONEE band prices and two independent
# sources agree on them.
ONEE_BANDS = [
    (100, 0.9010),
    (200, 1.0732),
    (300, 1.1676),
    (500, 1.3817),
    (float("inf"), 1.5958),
]

# RECORDED CONFLICT, NOT RESOLVED. Sources disagree on the VAT actually applied
# to low-voltage electricity in 2026:
#   - Morocco's VAT reform (LF 2024) completed in 2026, leaving 20% and 10%
#     only; the 14% reduced rate was abolished and electricity was scheduled to
#     reach 20% on 2026-01-01.
#   - A June-2026 tariff page still describes the band prices above as
#     "TVA 18 % comprise".
# The band prices are therefore treated as the all-in price per kWh and NO
# further VAT is added -- adding 20% on top of a TVA-inclusive figure would
# double-count. The swing between readings is under 0.4 MAD on a 24 h run, so
# this is recorded rather than chased. YOUR BILL SETTLES IT: pass --mad-per-kwh
# with the effective rate from your last ONEE invoice and the estimate becomes
# exact on the tariff side.
TARIFF_NOTE = ("band prices treated as all-in per kWh; sources conflict on "
               "whether 18% or 20% VAT is embedded in them (Morocco's VAT "
               "reform completed in 2026). Pass --mad-per-kwh from your bill "
               "to remove the ambiguity.")

# System power model. Ryzen 5 5500 (65 W TDP) + Radeon RX 6650 XT + 16 GB +
# NVMe SSD, measured at the wall by nobody -- these are the declared figures.
# Idle is dominated by the discrete GPU and the PSU's own conversion loss.
P_IDLE_W = 65.0          # whole system at the wall, desktop idle, screen off
P_FULL_W = 250.0         # whole system at the wall, CPU and GPU both loaded
# Incremental wall watts while one core is fully busy. Used for the MARGINAL
# figure, which is what the A-029 process itself is responsible for.
W_PER_BUSY_CORE = 15.0

# The household's typical monthly consumption decides which band the run's kWh
# are actually billed at. A 24 h run does not start a new bill at 0 kWh -- it
# lands on top of whatever the house has already used this month, so the
# MARGINAL band is the right price. Default assumes a mid-sized household.
DEFAULT_MONTHLY_KWH = 250.0

STATUS_PATH = Path("C:/Projects/VESPER-endurance-2026-08-16/docs/planning/"
                   "spike-results/A-029-endurance-live.json")
SAMPLES_PATH = REPO / "docs" / "planning" / "spike-results" / "A-029-power-samples.jsonl"
REPORT_PATH = REPO / "docs" / "planning" / "spike-results" / "A-029-power-cost.json"


def marginal_band(monthly_kwh: float) -> tuple[float, str]:
    """The price the NEXT kWh is billed at, given the month's usage so far."""
    lower = 0.0
    for upper, price in ONEE_BANDS:
        if monthly_kwh < upper:
            label = f"{int(lower)}-{'500+' if upper == float('inf') else int(upper)} kWh/month"
            return price, label
        lower = upper
    return ONEE_BANDS[-1][1], ">500 kWh/month"


def find_run_pid() -> int | None:
    """The A-029 process, found by what it is running rather than by a pid file."""
    if psutil is None:
        return None
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cl = " ".join(p.info.get("cmdline") or [])
            if "run_a029_endurance.py" in cl and "--launch" in cl:
                return p.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def track(args) -> int:
    """Sample until the run reaches a terminal state, then write the report."""
    global SAMPLES_PATH
    if args.samples:
        SAMPLES_PATH = Path(args.samples)
    if psutil is None:
        print("psutil is not installed; nothing can be sampled.")
        return 2

    pid = find_run_pid()
    proc = psutil.Process(pid) if pid else None
    print(f"  tracking A-029 pid={pid}  idle={args.idle_watts} W  "
          f"full={args.full_watts} W")
    print(f"  samples -> {SAMPLES_PATH}")

    SAMPLES_PATH.parent.mkdir(parents=True, exist_ok=True)
    psutil.cpu_percent(interval=None)                  # prime the counter
    t0 = time.monotonic()
    last_cpu_s = proc.cpu_times() if proc else None
    last_cpu_total = (last_cpu_s.user + last_cpu_s.system) if last_cpu_s else 0.0

    while True:
        time.sleep(args.interval)
        try:
            cpu_pct = psutil.cpu_percent(interval=None)
            now_cpu_total = 0.0
            if proc and proc.is_running():
                ct = proc.cpu_times()
                now_cpu_total = ct.user + ct.system
            proc_cpu_delta = max(0.0, now_cpu_total - last_cpu_total)
            last_cpu_total = now_cpu_total

            watts = args.idle_watts + (args.full_watts - args.idle_watts) * (cpu_pct / 100.0)
            if args.wall_watts:
                watts = args.wall_watts          # a real reading overrides the model
            sample = {
                "at_s": round(time.monotonic() - t0, 1),
                "wall_s": round(time.time(), 1),
                "system_cpu_pct": cpu_pct,
                "system_watts_estimated": round(watts, 2),
                "interval_s": args.interval,
                "a029_cpu_s_delta": round(proc_cpu_delta, 3),
                "a029_alive": bool(proc and proc.is_running()),
            }
            with SAMPLES_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(sample) + "\n")
        except Exception as e:                          # noqa: BLE001
            print(f"  sample error: {e}")
            continue

        # Stop when the run does, so the report "comes out with it".
        try:
            d = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
            if d.get("state") != "RUNNING":
                print(f"  A-029 reached {d.get('state')}; writing the cost report")
                report(args)
                return 0
        except Exception:                               # noqa: BLE001
            pass
        if proc and not proc.is_running():
            print("  A-029 process is gone; writing the cost report")
            report(args)
            return 0


def report(args) -> int:
    global SAMPLES_PATH
    if args.samples:
        SAMPLES_PATH = Path(args.samples)
    if not SAMPLES_PATH.exists():
        print(f"  no samples at {SAMPLES_PATH}")
        return 1
    rows = [json.loads(l) for l in SAMPLES_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not rows:
        print("  no samples yet")
        return 1

    span_s = sum(r["interval_s"] for r in rows)
    # Energy is the integral of power over time; each sample stands for its own
    # interval rather than for an assumed-constant average.
    joules = sum(r["system_watts_estimated"] * r["interval_s"] for r in rows)
    kwh_system = joules / 3_600_000.0
    mean_w = joules / span_s if span_s else 0.0

    a029_cpu_s = sum(r["a029_cpu_s_delta"] for r in rows)
    kwh_a029 = (a029_cpu_s * args.core_watts) / 3_600_000.0

    price, band = marginal_band(args.monthly_kwh)
    if args.mad_per_kwh:
        price, band = args.mad_per_kwh, "from your ONEE bill"

    hours = span_s / 3600.0
    per24 = (24.0 / hours) if hours else 0.0

    print()
    print(f"  sampled {len(rows)} intervals over {hours:.2f} h"
          + ("  [WALL-METER READING]" if args.wall_watts else "  [ESTIMATED, not measured]"))
    print(f"  mean system draw     {mean_w:.1f} W")
    print(f"  marginal band        {price:.4f} MAD/kWh  ({band})")
    print()
    print(f"  THE MACHINE BEING ON")
    print(f"    energy so far      {kwh_system:.3f} kWh   = {kwh_system * price:.2f} MAD")
    print(f"    projected 24 h     {kwh_system * per24:.2f} kWh   = "
          f"{kwh_system * per24 * price:.2f} MAD")
    print(f"    if left on 30 d    {kwh_system * per24 * 30:.0f} kWh  = "
          f"{kwh_system * per24 * 30 * price:.0f} MAD")
    print()
    print(f"  THE A-029 RUN ITSELF (marginal)")
    print(f"    cpu consumed       {a029_cpu_s:.1f} s over {hours:.2f} h")
    print(f"    energy so far      {kwh_a029:.6f} kWh = {kwh_a029 * price:.4f} MAD")
    print(f"    projected 24 h     {kwh_a029 * per24:.6f} kWh = "
          f"{kwh_a029 * per24 * price:.4f} MAD")
    print()
    print("  The run did not cause the machine to be on: it had been up 13.2 h")
    print("  when the run started. The marginal figure is what VESPER added.")

    payload = {
        "schema_version": 1,
        "provenance": "MEASURED" if args.wall_watts else "ESTIMATED",
        "note": ("wattage is modelled from CPU utilisation against declared "
                 "idle/full figures; this machine exposes no power sensor. Pass "
                 "--wall-watts from a plug-in energy meter to make it measured."
                 if not args.wall_watts else
                 "wattage supplied from a wall meter reading"),
        "declared": {
            "idle_watts": args.idle_watts, "full_watts": args.full_watts,
            "watts_per_busy_core": args.core_watts,
            "household_monthly_kwh": args.monthly_kwh,
            "tariff_bands_mad_per_kwh": [
                {"up_to_kwh_month": (None if u == float("inf") else u), "mad": p}
                for u, p in ONEE_BANDS],
            "tariff_source": "https://kherba.com/tarifs (retrieved 2026-08-16)",
            "tariff_note": TARIFF_NOTE,
            "marginal_band": band, "marginal_mad_per_kwh": price,
        },
        "observed": {
            "samples": len(rows), "hours": round(hours, 3),
            "mean_system_watts": round(mean_w, 2),
            "a029_cpu_seconds": round(a029_cpu_s, 2),
        },
        "machine_being_on": {
            "kwh_so_far": round(kwh_system, 4),
            "mad_so_far": round(kwh_system * price, 3),
            "kwh_per_24h": round(kwh_system * per24, 3),
            "mad_per_24h": round(kwh_system * per24 * price, 2),
            "mad_per_30d": round(kwh_system * per24 * 30 * price, 1),
        },
        "a029_run_marginal": {
            "kwh_so_far": round(kwh_a029, 8),
            "mad_so_far": round(kwh_a029 * price, 6),
            "kwh_per_24h": round(kwh_a029 * per24, 8),
            "mad_per_24h": round(kwh_a029 * per24 * price, 6),
        },
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"  wrote {REPORT_PATH}")
    return 0


# --------------------------------------------------------------------------
# Scenario projection — what VESPER costs in each mode, from measured data
# --------------------------------------------------------------------------

# Declared wall power per operating profile. These are the weakest numbers in
# this file and are labelled as such.
#
# WHY THE CONCLUSION SURVIVES THEM ANYWAY: cost per token is
# (watts / tokens_per_second), and the tiers differ by 20x in MEASURED
# throughput while their power profiles differ by well under 2x. The ranking
# and the rough ratios are therefore driven by the measurement, not by the
# estimate -- a 40% error in the wattage below moves the per-token figures by
# 40% and changes no ordering.
POWER_PROFILES = {
    "gpu_resident": (175.0,
                     "model fully offloaded (-ngl 99, Vulkan); the RX 6650 XT "
                     "does the work and is the dominant draw"),
    "cpu_paging": (145.0,
                   "not fully offloaded; CPU-bound with heavy paging (the "
                   "2026-08-15 measurement recorded 660 pages/s and 0.27 GB "
                   "free RAM for the MoE 30B), so the GPU is near idle while "
                   "the CPU and SSD carry it"),
    "idle": (P_IDLE_W, "desktop idle, no model resident"),
}

SPIKE_DIR = REPO / "docs" / "planning" / "spike-results"


def _measured_tiers() -> list[dict]:
    """Read tier throughput from the SPIKE-001 artifacts. Nothing hardcoded.

    The power profile is DERIVED from each artifact's own launch command: a run
    with `-ngl 99` put the model on the GPU, one without did not. That is the
    single fact that decides which profile applies, and it is recorded in the
    measurement rather than assumed here.
    """
    out = []
    for p in sorted(SPIKE_DIR.glob("SPIKE-001-3.1*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:                               # noqa: BLE001
            continue
        t = d.get("throughput") or {}
        tps = t.get("median_effective_tokens_per_sec")
        if not t.get("tier") or not tps:
            continue
        if t.get("concurrent_load"):
            continue                                    # the idle figure is the tier's own rate
        if "kali" in p.name:
            continue                                    # node 2, different hardware
        lc = (d.get("runner") or {}).get("launch_command", "")
        profile = "gpu_resident" if "-ngl 99" in lc else "cpu_paging"
        out.append({
            "artifact": p.name, "tier": t["tier"],
            "model": Path(t.get("model_path", "")).name,
            "tokens_per_s": tps, "profile": profile,
            "profile_basis": "-ngl 99 present" if profile == "gpu_resident"
                             else "-ngl 99 absent",
        })
    return out


def scenarios(args) -> int:
    price, band = marginal_band(args.monthly_kwh)
    if args.mad_per_kwh:
        price, band = args.mad_per_kwh, "from your ONEE bill"

    tiers = _measured_tiers()
    rows = []
    for t in tiers:
        watts, basis = POWER_PROFILES[t["profile"]]
        # Power ABOVE idle is what running the model actually adds; the desktop
        # would be drawing the idle figure regardless.
        marginal_w = watts - P_IDLE_W
        hours_per_mtok = (1_000_000 / t["tokens_per_s"]) / 3600.0
        kwh_total = watts * hours_per_mtok / 1000.0
        kwh_marginal = marginal_w * hours_per_mtok / 1000.0
        rows.append({**t, "watts": watts, "power_basis": basis,
                     "hours_per_million_tokens": round(hours_per_mtok, 2),
                     "mad_per_million_tokens_total": round(kwh_total * price, 2),
                     "mad_per_million_tokens_marginal": round(kwh_marginal * price, 2),
                     "mad_per_hour_marginal": round(marginal_w / 1000.0 * price, 3)})

    rows.sort(key=lambda r: r["mad_per_million_tokens_marginal"])
    print(f"\n  ELECTRICITY COST BY TIER  (marginal band {price:.4f} MAD/kWh, {band})")
    print("  throughput is MEASURED (SPIKE-001); wattage is DECLARED; the ratios")
    print("  are driven by the measurement, so they survive a large error in the watts.\n")
    print(f"  {'tier':9} {'model':28} {'tok/s':>7} {'profile':13} "
          f"{'h/Mtok':>7} {'MAD/Mtok':>9} {'MAD/h':>7}")
    for r in rows:
        print(f"  {r['tier']:9} {r['model'][:28]:28} {r['tokens_per_s']:7.2f} "
              f"{r['profile']:13} {r['hours_per_million_tokens']:7.1f} "
              f"{r['mad_per_million_tokens_marginal']:9.2f} "
              f"{r['mad_per_hour_marginal']:7.3f}")

    best = rows[0]
    worst = rows[-1]
    ratio = (worst["mad_per_million_tokens_marginal"]
             / max(best["mad_per_million_tokens_marginal"], 1e-9))
    print(f"\n  {worst['tier']} ({worst['model'][:24]}) costs {ratio:.0f}x more per token")
    print(f"  than {best['tier']} ({best['model'][:24]}) -- almost entirely because it is")
    print(f"  {worst['tokens_per_s']:.1f} tok/s against {best['tokens_per_s']:.1f}, not because it draws more.")

    # A day of realistic VESPER operation, rather than a tier in isolation.
    idle_kwh_day = P_IDLE_W * 24 / 1000.0
    print(f"\n  A DAY OF OPERATION (24 h)")
    print(f"    machine on, nothing running   {idle_kwh_day:5.2f} kWh  "
          f"{idle_kwh_day * price:6.2f} MAD")
    for hrs in (1, 4):
        for t in ("standard", "strong"):
            cand = [r for r in rows if r["tier"] == t]
            if not cand:
                continue
            r = min(cand, key=lambda x: x["mad_per_million_tokens_marginal"])
            kwh = idle_kwh_day + (r["watts"] - P_IDLE_W) * hrs / 1000.0
            toks = r["tokens_per_s"] * hrs * 3600 / 1e6
            print(f"    + {hrs} h of {t:9} {kwh:5.2f} kWh  {kwh * price:6.2f} MAD"
                  f"   ({toks:.2f} M tokens generated)")

    payload = {
        "schema_version": 1, "provenance": "MIXED",
        "throughput": "MEASURED -- SPIKE-001 artifacts, median effective tok/s, idle runs",
        "wattage": "DECLARED -- no power sensor on this machine; see power_profiles",
        "marginal_mad_per_kwh": price, "band": band,
        "power_profiles": {k: {"watts": v[0], "basis": v[1]}
                           for k, v in POWER_PROFILES.items()},
        "tiers": rows,
        "headline": (f"{worst['tier']} costs ~{ratio:.0f}x more electricity per token "
                     f"than {best['tier']}, driven by measured throughput "
                     f"({worst['tokens_per_s']:.1f} vs {best['tokens_per_s']:.1f} tok/s), "
                     "not by power draw."),
    }
    out = SPIKE_DIR / "A-029-power-scenarios.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n  wrote {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--scenarios", action="store_true",
                    help="project cost per tier from the SPIKE-001 measurements")
    ap.add_argument("--interval", type=float, default=60.0)
    ap.add_argument("--samples", help="where the raw sample stream is written; "
                    "defaults into the repo, but a live run should point it "
                    "elsewhere so an append-per-minute does not churn the tree")
    ap.add_argument("--idle-watts", type=float, default=P_IDLE_W)
    ap.add_argument("--full-watts", type=float, default=P_FULL_W)
    ap.add_argument("--core-watts", type=float, default=W_PER_BUSY_CORE)
    ap.add_argument("--monthly-kwh", type=float, default=DEFAULT_MONTHLY_KWH)
    ap.add_argument("--mad-per-kwh", type=float,
                    help="effective rate from your ONEE bill; overrides the bands")
    ap.add_argument("--wall-watts", type=float,
                    help="a real reading from a plug-in energy meter. Supplying "
                         "this changes the artifact's provenance to MEASURED.")
    args = ap.parse_args()
    if args.scenarios:
        return scenarios(args)
    if args.track:
        return track(args)
    return report(args)


if __name__ == "__main__":
    raise SystemExit(main())
