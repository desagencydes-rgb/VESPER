"""Build the provider ladder from the governed supply table and live secrets.

WHAT WAS MISSING UNTIL THIS FILE EXISTED. `core/gateway.py` knew how to order,
retry and refuse; `core/quota.py` knew what was left; `contracts/policy/
provider_supply.toml` listed who exists. Nothing connected them, so every
provider in the tree was a test double and the ladder had never carried a real
request. A gateway with nothing plugged into it is a diagram.

THREE RULES DECIDE EVERY LINE HERE.

  RULE R6 -- EGRESS GATES BEFORE QUOTA. `for_egress` filters the ladder by what
  a task may be shown to, and it does so BEFORE any headroom is consulted. The
  two most generous free tiers available are both E2_PUBLIC, so a router that
  ranked on quota first would hand private content to exactly the wrong
  suppliers. Capacity never buys permission.

  INV-HW-2 -- MEASURED, NOT DECLARED. A row is registered only if the
  measurement file says it ANSWERED. `quota_published` is loaded as an
  unmeasured ceiling; the real one arrives the first time a provider refuses,
  because a refusal is a measurement and a docs page is not.

  INV-COST-5 -- metered_free_tier IS PAID unless a hard cap is provable, and
  the evidence travels with the claim. Every row carries `hard_cap_evidence`
  and registration refuses a row that sets the flag without it.

NO PROVIDER NAME IS BRANCHED ON. Identity -- url, model, credential name, wire
format -- arrives as data. A different vendor speaking a shape already
implemented is a row in a TOML file, not a patch to this module. That is
INV-HW-1's discipline applied to suppliers rather than to hardware.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.gateway import Provider
from core.quota import QuotaLedger

REPO = Path(__file__).resolve().parents[1]
SUPPLY = REPO / "contracts" / "policy" / "provider_supply.toml"
SECRETS = Path.home() / ".config" / "vesper" / "secrets.env"
RESULTS = REPO / "docs" / "planning" / "spike-results"

# See routing/http_completion.py: urllib's own default User-Agent is refused
# with 403 by at least one provider's WAF, and 403 classifies as auth_failed,
# which is TERMINAL. The library default is the one value that fails.
USER_AGENT = "vesper/1.0 (+https://github.com/desagencydes-rgb/VESPER)"

EGRESS_CLASSES = ("E1_PRIVATE", "E2_PUBLIC")


class SupplyRefused(Exception):
    """A row could not be registered. Fail-closed; never partially trusted."""


def read_secrets(path: Path | None = None) -> dict:
    """Read the owner's credential file. Values are returned, never logged.

    A value beginning with `$` is an alias to another variable in the same
    file and is resolved here -- the real file contains one, and treating it
    literally would send the string `$GEMINI_API_KEY` as a bearer token.
    """
    p = path or SECRETS
    out: dict[str, str] = {}
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*export\s+([A-Z0-9_]+)=(.*)", line)
        if not m:
            continue
        v = m.group(2).split("#", 1)[0].strip().strip('"').strip("'")
        if v.startswith("$"):
            v = out.get(v.lstrip("$"), "")
        out[m.group(1)] = v
    return out


def latest_measurement(results_dir: Path | None = None) -> dict:
    """The most recent remote-supply probe, keyed by provider id.

    NEWEST BY FILENAME, WHICH IS A UTC TIMESTAMP -- not by mtime. A file copied
    or checked out gets a fresh mtime and would silently become "the latest
    measurement" without anything having been measured.
    """
    d = results_dir or RESULTS
    files = sorted(d.glob("REMOTE-SUPPLY-*.json"))
    if not files:
        return {}
    raw = json.loads(files[-1].read_text(encoding="utf-8"))
    return {r["provider_id"]: r for r in raw.get("results", [])}


@dataclass(slots=True)
class SupplyRow:
    """One row of the governed table, joined to its measurement."""

    provider_id: str
    rung: int
    egress_class: str
    cost_class: str
    provable_hard_cap: bool
    hard_cap_evidence: str
    model: str
    wire: str
    profile_id: str
    measured_tokens_per_sec: float | None
    rate_is_measured: bool
    quota_unit: str
    quota_limit: int | None
    quota_window_seconds: int


def load_rows(*, secrets: dict | None = None,
              measurement: dict | None = None,
              supply_path: Path | None = None) -> tuple[list, list]:
    """Return (usable rows, skipped (id, reason)). Never raises on one bad row.

    A ROW IS SKIPPED, NEVER DOWNGRADED. There is no path here that registers a
    provider with a guess in place of a missing fact -- an absent credential, an
    unmeasured rate or a missing hard-cap evidence string each remove the row
    from the ladder and say why. The ladder is shorter and honest rather than
    longer and wrong.
    """
    secrets = read_secrets() if secrets is None else secrets
    measurement = latest_measurement() if measurement is None else measurement
    table = tomllib.loads((supply_path or SUPPLY).read_text(encoding="utf-8"))

    rows: list[SupplyRow] = []
    skipped: list[tuple[str, str]] = []
    for r in table.get("provider", []):
        pid = r["id"]

        if r["egress_class"] not in EGRESS_CLASSES:
            skipped.append((pid, f"unknown egress_class {r['egress_class']!r}"))
            continue

        # INV-COST-5, checked here rather than trusted from the file. A flag
        # with no evidence is somebody asserting a cap, not a provable one.
        if r.get("provable_hard_cap") and not (r.get("hard_cap_evidence") or "").strip():
            skipped.append((pid, "provable_hard_cap set with no hard_cap_evidence "
                                 "-- a flag is not a proof (INV-COST-5)"))
            continue

        if r["wire"] != "cli_subprocess" and not secrets.get(r.get("credential_env", "")):
            skipped.append((pid, f"no credential in {r.get('credential_env')}"))
            continue

        m = measurement.get(pid)
        if not m or not m.get("usable"):
            # INV-HW-2, fail-closed. Unmeasured is UNAVAILABLE, and so is
            # measured-and-did-not-answer.
            skipped.append((pid, "not present in the latest measurement, or it "
                                 "did not answer -- unmeasured is UNAVAILABLE"))
            continue

        # A measured rate is preferred; a derived one is accepted and FLAGGED,
        # because a provider reporting zeroed usage would otherwise be excluded
        # for a defect in its accounting rather than in its service.
        rate = m.get("measured_tokens_per_sec")
        rate_measured = bool(m.get("rate_is_measured"))
        if rate is None:
            rate = m.get("derived_tokens_per_sec")
        if rate is None:
            skipped.append((pid, "no rate, measured or derived -- the probe "
                                 "could not see throughput for this row"))
            continue

        published = r.get("quota_published") or 0
        rows.append(SupplyRow(
            provider_id=pid, rung=int(r["rung"]),
            egress_class=r["egress_class"], cost_class=r["cost_class"],
            provable_hard_cap=bool(r.get("provable_hard_cap")),
            hard_cap_evidence=r.get("hard_cap_evidence", ""),
            model=r["model"], wire=r["wire"],
            # The profile names a TIER and a CLASS, never a vendor.
            profile_id=f"remote-rung{r['rung']}-{r['egress_class'].lower()}",
            measured_tokens_per_sec=float(rate),
            rate_is_measured=rate_measured,
            quota_unit=r.get("quota_unit", "UNKNOWN"),
            # PUBLISHED ZERO MEANS "NOTHING WAS PUBLISHED", NOT "LIMIT ZERO".
            # A literal 0 here would be recorded as UNAVAILABLE_ON_TIER and
            # permanently retire a working rung -- the exact confusion
            # MULTI_ROUTE.md SS13.1 exists to prevent, arriving from the other
            # direction. None means "ceiling unknown", which the ledger plans
            # against conservatively.
            quota_limit=(int(published) if published else None),
            quota_window_seconds=int(r.get("quota_window_seconds", 86_400)),
        ))
    return rows, skipped


def for_egress(rows: list, egress_class: str) -> list:
    """RULE R6, and it runs BEFORE any headroom is consulted.

    `E1_PRIVATE` content may go only to E1 suppliers. `E2_PUBLIC` content may
    go anywhere -- a public prompt is not made unsafe by a provider that could
    also hold private data.

    Deliberately not expressed as a numeric ranking. A comparison invites a
    tie-break, and a tie-break on egress is a route that lets a big quota argue
    with a privacy boundary.
    """
    if egress_class not in EGRESS_CLASSES:
        raise SupplyRefused(f"unknown egress class {egress_class!r}")
    if egress_class == "E1_PRIVATE":
        return [r for r in rows if r.egress_class == "E1_PRIVATE"]
    return list(rows)


# ------------------------------------------------------------------ callers

def _http_call(row: SupplyRow, endpoint: str, key: str, account: str,
               timeout: float = 180.0):
    """One provider call, in whichever wire shape the row declares."""
    url = endpoint.replace("{model}", row.model).replace("{account}", account)
    if row.wire == "google_generate":
        hdr = {"x-goog-api-key": key}
    else:
        hdr = {"Authorization": f"Bearer {key}"}

    def call(prompt: str, options: dict) -> dict:
        budget = int(options.get("max_tokens") or options.get("n_predict") or 1024)
        if row.wire == "openai_chat":
            payload: dict[str, Any] = {
                "model": row.model, "max_tokens": budget,
                "messages": [{"role": "user", "content": prompt}]}
            if options.get("reasoning_effort"):
                payload["reasoning_effort"] = options["reasoning_effort"]
        elif row.wire == "cf_responses":
            payload = {"input": prompt, "max_output_tokens": budget}
        elif row.wire == "google_generate":
            payload = {"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"maxOutputTokens": budget}}
        else:
            raise SupplyRefused(f"unknown wire {row.wire!r}")

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json",
                     "User-Agent": USER_AGENT, **hdr})
        from routing.http_completion import EndpointError, _error_detail, _STATUS_CLASS
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            retry_ms, message, limit = _error_detail(e)
            err = EndpointError(
                f"{row.provider_id} returned {e.code}: {message[:200]}",
                _STATUS_CLASS.get(e.code, "server_error"), retry_ms)
            err.quota_limit = limit
            raise err
        except Exception as e:                      # noqa: BLE001
            raise EndpointError(f"{row.provider_id}: {type(e).__name__}: {e}",
                                "connection_error") from e
        return _normalise(row.wire, raw)

    return call


def _cli_call(row: SupplyRow, argv: list, config_env: str | None,
              config_dir: str | None, timeout: float = 300.0):
    """A subscription rung. The official CLI, headless, as a subprocess."""

    def call(prompt: str, options: dict) -> dict:
        from routing.http_completion import EndpointError
        env = dict(os.environ)
        if config_env and config_dir:
            env[config_env] = os.path.expanduser(config_dir)
        cmd = [row.model and argv[0] or argv[0]]
        cmd = [argv[0]] + [a.replace("{prompt}", prompt) for a in argv[1:]]
        try:
            cp = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=timeout, env=env, input="")
        except FileNotFoundError as e:
            raise EndpointError(f"{row.provider_id}: {argv[0]} not installed",
                                "auth_failed") from e
        except subprocess.TimeoutExpired as e:
            raise EndpointError(f"{row.provider_id}: timed out", "timeout") from e
        if cp.returncode != 0:
            raise EndpointError(
                f"{row.provider_id} exited {cp.returncode}: "
                f"{(cp.stderr or '')[:200]}", "server_error")
        return {"text": (cp.stdout or "").strip(), "stop_reason": "stop",
                "usage": {}}

    return call


def _normalise(wire: str, raw: dict) -> dict:
    """One response shape out of three, so the gateway sees one contract.

    `usage` IS PASSED THROUGH RATHER THAN DEFAULTED. One provider reports all
    zeros on calls that worked; the ledger must be able to tell "reported zero"
    from "reported nothing", and inventing a number here would erase exactly
    that distinction before it ever reached the ledger.
    """
    if wire == "openai_chat":
        c = (raw.get("choices") or [{}])[0]
        msg = c.get("message") or {}
        return {"text": msg.get("content"), "stop_reason": c.get("finish_reason"),
                "usage": raw.get("usage") or {}}
    if wire == "cf_responses":
        res = raw.get("result") or {}
        text = None
        for o in res.get("output") or []:
            if o.get("type") == "message":
                text = "".join(p.get("text", "") for p in o.get("content") or [])
        return {"text": text, "stop_reason": res.get("status") or "stop",
                "usage": res.get("usage") or {}}
    if wire == "google_generate":
        cand = (raw.get("candidates") or [{}])[0]
        text = "".join(p.get("text", "")
                       for p in (cand.get("content") or {}).get("parts") or [])
        return {"text": text, "stop_reason": cand.get("finishReason"),
                "usage": raw.get("usageMetadata") or {}}
    raise SupplyRefused(f"unknown wire {wire!r}")


def register(gateway, cost, ledger: QuotaLedger, *,
             egress_class: str = "E1_PRIVATE",
             secrets: dict | None = None,
             supply_path: Path | None = None) -> dict:
    """Register every usable row for this egress class. Returns a report.

    RUNG ORDER IS THE OUTER SORT AND IS NOT NEGOTIABLE. Within a rung the
    ledger ranks on remaining headroom, but a rung-2 subscription must never be
    reached ahead of a rung-1 free API: rung 1 costs quota that refills daily,
    rung 2 costs the owner's own 5-hour window.
    """
    secrets = read_secrets() if secrets is None else secrets
    rows, skipped = load_rows(secrets=secrets, supply_path=supply_path)
    permitted = for_egress(rows, egress_class)
    permitted.sort(key=lambda r: (r.rung, -(r.measured_tokens_per_sec or 0)))

    table = tomllib.loads((supply_path or SUPPLY).read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in table.get("provider", [])}

    registered = []
    for row in permitted:
        raw = by_id[row.provider_id]
        if row.wire == "cli_subprocess":
            call = _cli_call(row, raw.get("argv", []),
                             raw.get("config_dir_env"), raw.get("config_dir"))
        else:
            call = _http_call(row, raw["endpoint"],
                              secrets.get(raw.get("credential_env", ""), ""),
                              secrets.get(raw.get("account_env", ""), ""))
        cost.register_credential(
            row.provider_id, row.cost_class,
            provable_hard_cap=row.provable_hard_cap,
            hard_cap_evidence=row.hard_cap_evidence)
        gateway.register(Provider(row.provider_id, row.profile_id, call,
                                  model=row.model))
        e = ledger.entry(row.provider_id, row.model)
        e.unit = row.quota_unit
        e.limit = row.quota_limit
        e.limit_is_measured = False        # published, not measured
        e.window_seconds = row.quota_window_seconds
        e.source = f"contracts/policy/provider_supply.toml:{row.provider_id} (published)"
        registered.append(row)

    return {"egress_class": egress_class,
            "registered": [r.provider_id for r in registered],
            "profile_ids": sorted({r.profile_id for r in registered}),
            "skipped": skipped,
            "excluded_by_egress": [r.provider_id for r in rows
                                   if r not in permitted]}
