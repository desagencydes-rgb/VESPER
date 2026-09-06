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
import pathlib
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


# The keychain service every VESPER credential is filed under. One service,
# one account per variable name, so `security` can find a value without being
# told anything the file does not already say.
KEYCHAIN_SERVICE = "ai.vesper.credentials"

# A keychain read that has not returned in this long is treated as absent. The
# only realistic cause is an access prompt, and a prompt is a hang: this runs
# unattended at three in the morning, and a runtime blocked on a dialog nobody
# is there to answer is worse than one that falls back to the file it already
# reads.
_KEYCHAIN_TIMEOUT_S = 3.0


def keychain_secret(name: str, *, service: str | None = None) -> str:
    """One credential out of the login keychain, or "" if it is not there.

    NEVER RAISES AND NEVER LOGS. A missing item, a locked keychain, a machine
    without `security` and a denied prompt all mean the same thing to the
    caller -- no value here, try the file -- and distinguishing them in a log
    line is how the name of a credential ends up in a transcript.
    """
    if not name:
        return ""
    # RESOLVED AT CALL TIME, NOT BOUND AS A DEFAULT. `service: str =
    # KEYCHAIN_SERVICE` evaluates the constant once, when the function is
    # defined, so the service can never afterwards be varied -- not by a test,
    # and not by anything that wanted a second store. It looks identical and it
    # silently ignores the module constant it appears to read.
    service = service or KEYCHAIN_SERVICE
    try:
        out = subprocess.run(
            ["/usr/bin/security", "find-generic-password",
             "-a", name, "-s", service, "-w"],
            capture_output=True, text=True, check=False,
            timeout=_KEYCHAIN_TIMEOUT_S)
    except Exception:                                # noqa: BLE001
        return ""
    if out.returncode != 0:
        return ""
    return (out.stdout or "").strip()


def keychain_names(*, service: str | None = None) -> list:
    """Which variable names have a keychain entry. Names only, never values."""
    service = service or KEYCHAIN_SERVICE
    try:
        out = subprocess.run(
            ["/usr/bin/security", "dump-keychain"],
            capture_output=True, text=True, check=False,
            timeout=_KEYCHAIN_TIMEOUT_S * 3)
    except Exception:                                # noqa: BLE001
        return []
    names, svc_seen = [], False
    for line in (out.stdout or "").splitlines():
        line = line.strip()
        if f'"{service}"' in line and '"svce"' in line:
            svc_seen = True
        elif svc_seen and '"acct"' in line:
            got = line.rsplit('="', 1)
            if len(got) == 2:
                names.append(got[1].rstrip('"'))
            svc_seen = False
    return sorted(set(names))


def credential_mismatches(path: Path | None = None) -> list:
    """Variables whose file value and keychain value DISAGREE. Names only.

    THE TRAP THIS EXISTS FOR. `read_secrets` lets the keychain overlay the
    file, which is what makes migrating a credential a single step. The cost is
    that once a variable has been migrated, editing it in `secrets.env` has no
    effect -- the keychain keeps winning, silently, and VESPER goes on using
    the old value.

    That is exactly what a rotated key looks like: the owner pastes the new one
    into the file, because that is where credentials have always gone, and
    nothing changes. A disagreement between the two stores is therefore not an
    edge case to tolerate; it is the signature of the mistake, and the only
    moment it is cheap to catch.

    NAMES AND LENGTHS ONLY. A finding never carries the value it found -- the
    same rule `core/redact.py` follows, for the same reason: a report that
    quotes a credential has leaked it to everywhere the report travels.
    """
    p = path or SECRETS
    out = []
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*(?:export\s+)?([A-Z0-9_]+)\s*=(.*)", line)
        if not m:
            continue
        name = m.group(1)
        v = m.group(2).split("#", 1)[0].strip().strip('"').strip("'")
        if not v or v.startswith("$"):
            continue
        kc = keychain_secret(name)
        if kc and kc != v:
            out.append({"name": name, "file_len": len(v), "keychain_len": len(kc),
                        "note": ("the keychain value is the one in use; the file "
                                 "has been edited since this was migrated")})
    return out


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
        # `export` IS OPTIONAL, AND MAKING IT MANDATORY WAS A SILENT TRAP.
        # A line reading `MISTRAL_API_KEY_CHOOSER=sk-...` is a valid, obvious
        # way to write a credential, and this regex skipped it without a word --
        # so seventeen keys the owner had pasted correctly were invisible to the
        # runtime on 2026-08-31 and every row naming them was dropped as "no
        # credential". A credential file is edited by hand under time pressure;
        # the parser is the wrong place to be strict about shell syntax.
        m = re.match(r"\s*(?:export\s+)?([A-Z0-9_]+)\s*=(.*)", line)
        if not m:
            continue
        v = m.group(2).split("#", 1)[0].strip().strip('"').strip("'")
        if v.startswith("$"):
            v = out.get(v.lstrip("$"), "")
        out[m.group(1)] = v

    # THE KEYCHAIN OVERLAYS THE FILE, and that direction is the migration path.
    # A credential moved into the keychain wins even if a stale copy is still
    # in `secrets.env`, so migrating one is a single step rather than an
    # edit-both-and-hope. The file remains the fallback, because a keychain
    # that cannot be read must not take VESPER's models away from it -- this
    # runs unattended, and no credential at all is a worse failure here than a
    # credential in a mode-0600 file.
    #
    # Only names the file already knows are looked up. Enumerating the keychain
    # to discover credentials would make this function's behaviour depend on
    # what else the owner keeps in it.
    for name in list(out):
        got = keychain_secret(name)
        if got:
            out[name] = got
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
    # WHICH SHARED POOL, AND WHAT FOR. Several rows can name one account and
    # draw a single budget; `purpose` is what a reservation floor is declared
    # against so a batch job cannot spend the day before the owner asks a
    # question.
    account: str = ""
    purpose: str = "text"
    # WHICH DIFFICULTIES MAY ROUTE HERE. Declared in the governed table, never
    # parsed from the provider id: an id is a label and a renamed row would
    # otherwise silently change what it is trusted to answer.
    tier: str = "standard"
    # Wall clock for the enrolment probe's one call. Seeds the live latency
    # estimate so the FIRST request to a profile is not the one that discovers
    # a slow rung. See `load_rows` for why it is not a throughput figure.
    probe_elapsed_s: float | None = None
    # Optional request parameters this endpoint accepts. EMPTY BY DEFAULT:
    # sending a parameter a provider does not know is a 400, and a 400 is
    # `bad_request`, which is TERMINAL -- so one unsupported field silently
    # retires a working rung.
    supports: tuple = ()
    # CARRIED SO AN ESCALATION CAN NAME IT. core/repair.py writes the owner a
    # guide, and "replace the value of its environment variable" is not a
    # guide -- it makes the reader go and look up the thing the system already
    # knew. The variable NAME is not a secret; only its value is.
    credential_env: str = ""


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

        if r.get("purpose") == "image":
            # AN IMAGE ROW HAS NO TOKEN RATE, and demanding one would skip a
            # provider that answered perfectly well -- the instrument would be
            # measuring the wrong quantity and then refusing the row for not
            # producing it. What is observable, and what actually matters for
            # scheduling, is TIME PER IMAGE. Recorded in the same field so the
            # ranking has a number, with the unit stated in the profile id.
            secs = m.get("elapsed_s")
            if not secs:
                skipped.append((pid, "no elapsed time recorded -- an image row "
                                     "is measured in seconds per image"))
                continue
            rate = 1.0 / float(secs)
            rate_measured = True
        elif rate is None:
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
            # THE PROFILE NAMES A CAPABILITY, NOT A SUPPLIER. Rows sharing a
            # tier, purpose, rung and egress class share a profile, and the
            # gateway then picks between them on remaining headroom. A profile
            # per provider would make the router choose the vendor, which is
            # exactly the product-shaped routing INV-HW-1 refuses.
            profile_id=(f"remote-{r.get('tier','standard')}"
                        f"-{r.get('purpose','text')}-rung{r['rung']}"
                        f"-{r['egress_class'].lower()}"),
            measured_tokens_per_sec=float(rate),
            rate_is_measured=rate_measured,
            # THE SWEEP'S OWN WALL CLOCK, carried through rather than left in
            # the JSON. It is the SAME QUANTITY a live observation is -- seconds
            # from asking to having an answer, queueing included -- which
            # throughput is not, and core/router.py was deriving a cold estimate
            # from throughput while this measurement sat unread two fields away.
            # Measured 2026-08-26: the first request to a profile took 13.3 s
            # because the derived estimate ranked the slow rung first, and the
            # number that would have prevented it was in the file being read.
            #
            # IT IS NOT THE SAME PROMPT as a conversational turn -- the sweep
            # asks for ~300 words -- so it OVERSTATES a short turn, uniformly,
            # across every row. Overstating everything by a similar factor
            # preserves the ordering, which is all a cold start needs, and the
            # first real call replaces it.
            probe_elapsed_s=(float(m["elapsed_s"]) if m.get("elapsed_s") else None),
            quota_unit=r.get("quota_unit", "UNKNOWN"),
            # PUBLISHED ZERO MEANS "NOTHING WAS PUBLISHED", NOT "LIMIT ZERO".
            # A literal 0 here would be recorded as UNAVAILABLE_ON_TIER and
            # permanently retire a working rung -- the exact confusion
            # MULTI_ROUTE.md SS13.1 exists to prevent, arriving from the other
            # direction. None means "ceiling unknown", which the ledger plans
            # against conservatively.
            quota_limit=(int(published) if published else None),
            quota_window_seconds=int(r.get("quota_window_seconds", 86_400)),
            credential_env=r.get("credential_env", ""),
            account=r.get("account", ""),
            purpose=r.get("purpose", "text"),
            tier=r.get("tier", "standard"),
            supports=tuple(r.get("supports") or ()),
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
        # THE PERSONA'S ONLY ROUTE TO THE WIRE. Until 2026-08-26 no branch below
        # carried one, so `core/persona.py` could compose a preamble that
        # nothing sent -- built-and-unreached, the failure mode this corpus
        # keeps rediscovering. Each wire spells it differently and there is no
        # shared field to lean on, which is exactly why it has to be written
        # out per branch rather than merged into the prompt string once: a
        # system turn folded into the user turn is a user turn, and the model
        # weights it as one.
        system = (options.get("system") or "").strip() or None
        # THE CONVERSATION SO FAR. A list of {"role", "content"} the caller has
        # already budgeted -- this layer renders it and never decides what is
        # in it. Empty is the normal case for a first turn and for every
        # non-conversational caller.
        #
        # AS TURNS, NOT AS PROSE, wherever the wire has turns. Folding the
        # history into the prompt string makes the whole conversation one user
        # message: the model loses who said what, and the last thing anybody
        # said blurs into the thing being asked. Two wires here have real turn
        # arrays and both are used.
        history = options.get("history") or []
        if row.wire == "openai_chat":
            msgs: list[dict] = []
            if system:
                msgs.append({"role": "system", "content": system})
            for h in history:
                r = "assistant" if h.get("role") == "assistant" else "user"
                msgs.append({"role": r, "content": str(h.get("content") or "")})
            msgs.append({"role": "user", "content": prompt})
            payload: dict[str, Any] = {
                "model": row.model, "max_tokens": budget, "messages": msgs}
            # SENT ONLY WHERE THE ROW SAYS IT IS ACCEPTED. See SupplyRow.supports.
            if (options.get("reasoning_effort")
                    and "reasoning_effort" in row.supports):
                payload["reasoning_effort"] = options["reasoning_effort"]
        elif row.wire == "cf_responses":
            # The Responses shape takes `input` as either a string or a list of
            # turns. Verified against this endpoint rather than assumed from the
            # OpenAI docs it resembles -- see the `instructions` note below for
            # why that distinction has already cost once here.
            if history:
                items = [{"role": ("assistant" if h.get("role") == "assistant"
                                   else "user"),
                          "content": str(h.get("content") or "")}
                         for h in history]
                items.append({"role": "user", "content": prompt})
                payload = {"input": items, "max_output_tokens": budget}
            else:
                payload = {"input": prompt, "max_output_tokens": budget}
            if system:
                # The Responses shape carries it as `instructions`, beside the
                # input rather than inside it. Verified against this endpoint
                # on 2026-08-26 rather than assumed from the OpenAI docs it
                # resembles -- `reasoning_effort` on Mistral is the standing
                # reminder that "OpenAI-compatible" is a family resemblance and
                # not a parameter set.
                payload["instructions"] = system
        elif row.wire == "cf_image":
            # STEPS ARE A COST LEVER, NOT A QUALITY DIAL ONLY. The measured
            # formula bills tiles*4.80 + tiles*steps*9.60, so every extra step
            # costs 9.60 per tile -- 38.4 on a 1024x1024. The default is the
            # model's own recommended minimum.
            # NO SYSTEM TURN. An image request has no system role to carry
            # one, and prepending the persona to the image prompt would put
            # "address the owner as sir" into the picture.
            payload = {"prompt": prompt,
                       "steps": int(options.get("steps") or 4)}
        elif row.wire == "google_generate":
            # `model` IS GOOGLE'S SPELLING OF `assistant`. Sending "assistant"
            # is a 400, and sending nothing makes every past turn look like the
            # owner talking to themselves.
            contents = [{"role": ("model" if h.get("role") == "assistant"
                                  else "user"),
                         "parts": [{"text": str(h.get("content") or "")}]}
                        for h in history]
            contents.append({"role": "user", "parts": [{"text": prompt}]})
            payload = {"contents": contents,
                       "generationConfig": {"maxOutputTokens": budget}}
            if system:
                payload["systemInstruction"] = {"parts": [{"text": system}]}
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


def _resolve_binary(binary: str) -> str:
    """An absolute path to `binary`, or `binary` unchanged if it cannot be found.

    LAUNCHD DOES NOT GIVE A JOB THE OWNER'S PATH. It hands out
    `/usr/bin:/bin:/usr/sbin:/sbin` and nothing else -- no `~/.local/bin`, no
    `/opt/homebrew/bin`, no `/usr/local/bin`. Every CLI rung in
    `provider_supply.toml` therefore worked when a person ran VESPER from a
    terminal and failed the moment launchd started it, which is how it actually
    runs.

    MEASURED 2026-09-05, and it had been costing the owner for days. `claude`
    lives at `~/.local/bin/claude`; the advisor rung raised `FileNotFoundError`,
    which this module classifies TERMINAL as `bad_request` -- "this call was
    malformed" -- so triage filed VESPER'S OWN DEFECT, the repairer proposed a
    patch to a wire format that was never wrong, and the workbench showed the
    owner `claude-advisor -- bad_request 0.00s` on every action. The 0.00s was
    the tell: no subprocess ever started.

    `shutil.which` FIRST, so a machine that does have it on PATH is unchanged.
    The fallbacks are the three places a per-user tool actually installs on
    macOS, plus the Homebrew pair. Returning `binary` unchanged when nothing
    matches preserves the existing error rather than inventing a new one.
    """
    import shutil
    found = shutil.which(binary)
    if found:
        return found
    if "/" in binary:                    # already a path; let it fail as given
        return binary
    home = pathlib.Path.home()
    for cand in (home / ".local" / "bin" / binary,
                 home / "bin" / binary,
                 pathlib.Path("/opt/homebrew/bin") / binary,
                 pathlib.Path("/usr/local/bin") / binary):
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return binary


def _cli_call(row: SupplyRow, binary: str, argv: list, config_env: str | None,
              config_dir: str | None, timeout: float = 300.0,
              oauth_token: str = ""):
    """A subscription rung. The official CLI, headless, as a subprocess.

    `binary` IS SEPARATE FROM `argv` BECAUSE IT WAS BEING TAKEN FROM IT. This
    function built its command as `[argv[0]] + argv[1:]`, and the contract's
    argv for that rung is `["-p", "{prompt}"]` -- so it executed `-p` and got
    FileNotFoundError, which the handler below reported as `auth_failed`.
    `auth_failed` is in `gateway.TERMINAL`, so a rung that was merely wired
    wrong retired itself permanently, on the first attempt, quietly.

    THE SWEEP DID NOT CATCH IT, and that is the more useful half. The
    2026-08-25 supply measurement recorded this rung usable at 15.28 s, because
    the measurement script assembles its own command rather than calling this
    function. The instrument and the production path disagreed and the
    instrument was the one that got believed -- the ladder has been carrying a
    rung nothing could ever actually call, with a green measurement beside it.
    """

    def call(prompt: str, options: dict) -> dict:
        from routing.http_completion import EndpointError
        env = dict(os.environ)
        if config_env and config_dir:
            env[config_env] = os.path.expanduser(config_dir)
        # THE CREDENTIAL DOES NOT LIVE IN THE CONFIG DIRECTORY. It lives in the
        # login KEYCHAIN, and a launchd job cannot read it: the keychain item's
        # ACL names the binaries allowed to read it without prompting, VESPER is
        # not one of them, and a background job has no way to answer a prompt.
        #
        # MEASURED 2026-09-06 by running the advisor with the runtime's exact
        # environment, read off the live process: it answers "Not logged in ·
        # Please run /login". From an interactive shell the same command
        # succeeds, which is why this looked healthy every time it was tested by
        # hand -- the instrument and the production path disagreed and the
        # instrument was the one that got believed. That is the same sentence
        # `_cli_call`'s own docstring already had to write about this rung.
        #
        # `claude setup-token` exists for exactly this: a long-lived token for
        # headless use, passed in the environment, no keychain involved. When
        # `secrets.env` carries one it is used; when it does not, the rung fails
        # the way it does today and says why.
        if oauth_token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token
        # A SUBSCRIPTION CLI HAS NO SYSTEM ARGUMENT WE CAN RELY ON. `claude`
        # takes `--append-system-prompt` and `codex exec` takes nothing of the
        # kind, and the argv template lives in the contract where a per-vendor
        # flag would have to be encoded per row. So the preamble is prepended
        # to the prompt with an explicit boundary instead.
        #
        # THIS IS WEAKER THAN A SYSTEM TURN AND IS LABELLED AS SUCH. A folded
        # preamble is a user turn: the model can be argued out of it by the
        # rest of the same message in a way a real system turn resists. It is
        # recorded here rather than smoothed over because the two rungs are not
        # equivalent and a reader comparing behaviour across the ladder needs
        # to know which one they are on.
        system = (options.get("system") or "").strip()
        # NO TURN ARRAY ON A CLI, so the conversation is folded in with speaker
        # labels -- weaker than real turns for the same reason the preamble is
        # weaker here, and labelled rather than smoothed over. A reader
        # comparing behaviour across the ladder needs to know which rung they
        # are on.
        convo = ""
        for h in options.get("history") or []:
            who = "VESPER" if h.get("role") == "assistant" else "Owner"
            convo += f"{who}: {str(h.get('content') or '')}\n"
        parts = [p for p in (system, convo.strip(), prompt) if p]
        text = "\n\n---\n\n".join(parts)
        cmd = [_resolve_binary(binary)] + [a.replace("{prompt}", text)
                                           for a in argv]
        try:
            cp = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=timeout, env=env, input="")
        except FileNotFoundError as e:
            # NOT `auth_failed`. A missing binary and a rejected credential are
            # both terminal and are not the same fact: one is fixed by
            # installing something and the other by signing in, and triage
            # reads this string to decide which. `bad_request` is the terminal
            # class that says "this call was malformed", which a command naming
            # a binary that is not here is.
            raise EndpointError(
                f"{row.provider_id}: {binary!r} is not on PATH -- the rung is "
                "installed in the contract and not on this machine",
                "bad_request") from e
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
    if wire == "cf_image":
        res = raw.get("result") or {}
        # The IMAGE is returned base64 in `image`; it is deliberately NOT
        # decoded here. `text` carries a short receipt so the gateway's
        # empty-content guard sees a real answer, and the bytes travel
        # separately -- a 265 KB blob in the field that telemetry copies
        # verbatim would end up in every event, checkpoint and evidence record.
        img = res.get("image") or ""
        return {"text": (f"image/jpeg base64 {len(img)} chars" if img else ""),
                "image_b64": img, "stop_reason": "stop",
                "usage": res.get("usage") or {}}

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
            call = _cli_call(row, raw["endpoint"], raw.get("argv", []),
                             raw.get("config_dir_env"), raw.get("config_dir"),
                             oauth_token=secrets.get("CLAUDE_CODE_OAUTH_TOKEN", ""))
        else:
            call = _http_call(row, raw["endpoint"],
                              secrets.get(raw.get("credential_env", ""), ""),
                              secrets.get(raw.get("account_env", ""), ""))
        cost.register_credential(
            row.provider_id, row.cost_class,
            provable_hard_cap=row.provable_hard_cap,
            hard_cap_evidence=row.hard_cap_evidence)
        # THE PROVIDER CARRIES ITS OWN EGRESS CLASS TO THE CHOKE POINT.
        # Filtering at registration is necessary and was never sufficient: it
        # decides which ladder gets built, and says nothing about what may then
        # be sent down it.
        gateway.register(Provider(row.provider_id, row.profile_id, call,
                                  model=row.model,
                                  egress_class=row.egress_class))
        e = ledger.entry(row.provider_id, row.model)
        if row.account:
            # ONE POOL PER ACCOUNT, declared before the entry joins it, so a
            # second modality cannot arrive believing the ceiling is its own.
            ledger.declare_pool(row.account, float(row.quota_limit or 0))
            e.account = row.account
        e.purpose = row.purpose
        e.unit = row.quota_unit
        e.limit = row.quota_limit
        e.limit_is_measured = False        # published, not measured
        e.window_seconds = row.quota_window_seconds
        e.source = f"contracts/policy/provider_supply.toml:{row.provider_id} (published)"
        # SEED THE GATEWAY'S LATENCY VIEW TOO, for the same reason the router's
        # is seeded: three rungs share one profile and are not equally fast --
        # measured 2026-08-26 at 1.50s, 2.66s and 3.85s on the same probe. Left
        # cold, the gateway ranks them on quota headroom on the first request,
        # which is the axis unrelated to time that INV-PERF-2 exists about.
        #
        # SEEDED, NOT ASSERTED: it enters `_observed` as an ordinary sample, so
        # the first real call updates it like any other and a rung that has
        # since got slower is not held to an enrolment-day figure.
        if row.probe_elapsed_s:
            gateway.seed_observation(row.provider_id, row.probe_elapsed_s)
        registered.append(row)

    return {"egress_class": egress_class,
            "registered": [r.provider_id for r in registered],
            "profile_ids": sorted({r.profile_id for r in registered}),
            "skipped": skipped,
            "excluded_by_egress": [r.provider_id for r in rows
                                   if r not in permitted]}


def measured_profiles(rows: list, *, purpose: str = "text") -> list:
    """Turn supply rows into router profiles, one per distinct capability.

    WHY THE ROUTER COULD NOT REACH A REMOTE PROVIDER UNTIL NOW. `Router` loaded
    six profiles, all local, all from SPIKE-001 -- and `register` above built
    provider ids the router had never heard of. So `Router.select(difficulty)`
    could never return a remote profile, and the live acceptance run passed only
    because it named the profile directly and bypassed the router entirely.

    That is the same shape as the defect the gateway had until 2026-08-24:
    `Provider.profile_id` existed and nothing read it, so registration order was
    the real routing rule while A-022 stayed green. A decision that cannot reach
    the thing it decides is not a decision.

    ONE PROFILE PER CAPABILITY, NOT PER SUPPLIER. Several rows collapse onto one
    profile id and the gateway ranks between them on headroom. A profile per
    provider would put the vendor's name in the router's decision, which is what
    INV-HW-1 exists to refuse.

    THE RATE IS THE SLOWEST MEMBER, not the mean and not the fastest. The
    router's estimate must hold for whichever member actually answers, and a
    mean describes a call nobody makes. Erring slow makes the estimate
    pessimistic, which defers work; erring fast promises a latency the profile
    cannot keep.
    """
    from core.router import MeasuredProfile

    # PURPOSE FILTERS BEFORE TIER, and leaving it out was a real defect caught
    # the moment these profiles were first printed. The image row is
    # `tier = standard`, and `core/router.py` selects on TIER ALONE -- it has no
    # concept of modality. So a moderate-difficulty TEXT task would have been
    # routed to an image generator, which would have answered, with a picture.
    #
    # The router is not the place to fix that. Teaching it about modality would
    # put a second axis into a component whose whole contract is difficulty ->
    # capability. Instead each modality gets its own router populated with its
    # own profiles, which is what MULTI_ROUTE.md SS4 meant by "their own routing
    # systems" -- separate policy, one shared ledger underneath.
    by_profile: dict[str, list] = {}
    for r in rows:
        if r.purpose != purpose:
            continue
        by_profile.setdefault(r.profile_id, []).append(r)

    out = []
    for pid, members in sorted(by_profile.items()):
        rates = [m.measured_tokens_per_sec for m in members
                 if m.measured_tokens_per_sec]
        if not rates:
            continue                      # INV-HW-2: unmeasured is UNAVAILABLE
        # THE PROFILE'S COLD LATENCY IS ITS FASTEST MEMBER, where the rate above
        # is its SLOWEST. That looks inconsistent and is not: the rate has to
        # hold for whichever member answers, so erring slow is honest. The
        # latency estimate is used to CHOOSE, and the gateway will hand the
        # request to the best member inside the profile -- so the number the
        # router needs is what this profile can do, not what its worst member
        # would do. Ranking a three-rung profile by its slowest member would
        # reject it for a rung that never gets asked.
        probes = [m.probe_elapsed_s for m in members if m.probe_elapsed_s]
        out.append(MeasuredProfile(
            probe_seconds=(min(probes) if probes else None),
            profile_id=pid,
            tier=members[0].tier,
            node_class="remote",
            wall_tokens_per_sec=min(rates),
            wall_tokens_per_sec_idle=max(rates),
            measured=True,
            source=("routing/supply.py from the latest REMOTE-SUPPLY probe; "
                    f"{len(members)} member(s): "
                    + ", ".join(sorted(m.provider_id for m in members))
                    + "; rate is the SLOWEST member, which is the one the "
                      "estimate has to hold for"),
        ))
    return out
