"""Where VESPER stops using each Claude account -- the owner's own number.

Owner, 2026-09-14: "i want it flexible, vesper stops itself when the limit i set
for it in settings is reached, for both accounts, and i can set it for both
anytime just from the settings".

WHY THE SOFT CAP ALREADY IN THE LEDGER COULD NOT BE THAT. `core/quota.py` holds
a share per rung -- 70% for the account the agents share, 40% for the advisor's
-- and binds it ONLY ON A MEASURED CEILING, because a share of an unknown number
is an unknown number (INV-HW-2). A subscription publishes no ceiling, so for
every Claude agent rung `limit is None` and that cap has never once bound.
Measured 2026-09-14: the research and language-model runs were not stopped by
VESPER at 70%. They were stopped by Claude's own "You've hit your monthly spend
limit", and the owner read VESPER's declared 70% as the thing that had fired.
A number that cannot bind is worse than no number: it reads as a working brake.

WHAT MAKES IT MEASURABLE. `claude -p --output-format stream-json --verbose`
emits a `rate_limit_event` before its result, carrying THE ACCOUNT'S OWN
utilisation -- the same percentage the owner sees on their account page:

    {"type": "rate_limit_event", "rate_limit_info": {
       "status": "allowed_warning", "rateLimitType": "seven_day",
       "utilization": 0.81, "isUsingOverage": false,
       "unifiedWindows": {"five_hour": {"utilization": 0.03, "resetsAt": ...},
                          "seven_day": {"utilization": 0.81, "resetsAt": ...}}}}

Measured 2026-09-14 23:35 on both accounts, and measured again WITH THE
PRODUCTION ARGV -- the persona and the tool refusals included -- because a flag
combination that only works on a bare probe is `_cli_call`'s own finding
repeating itself: the instrument and the production path disagreed and the
instrument was the one that got believed.

ONE CALL'S WORTH OF OVERSHOOT IS INHERENT, AND ACCEPTED. The reading arrives
WITH the answer, so VESPER learns it has crossed the owner's line by crossing
it. The alternative is a second call before every call, which spends the very
thing the limit exists to protect. So the rule is: the limit stops the NEXT
call, and the settings row says when the reading was taken.

A WINDOW THAT HAS ROLLED SAYS NOTHING ABOUT NOW. Each window carries its own
reset time, so a reading is only consulted while it is still about the window it
measured -- otherwise a Monday refusal would still be stopping VESPER on
Thursday, with no call allowed to discover otherwise.

PAID EXTRA USAGE IS NOT VESPER'S TO SPEND. When Claude reports the account has
rolled onto it, VESPER stops regardless of the percentage: past the plan, every
call is money, and the owner decides that at their account page, not here.
"""

from __future__ import annotations

import json
import os
import pathlib
import time
import tomllib
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[1]
SUPPLY = REPO / "contracts" / "policy" / "provider_supply.toml"
STATE = pathlib.Path.home() / "Library" / "Application Support" / "VESPER"
PATH = STATE / "claude-limits.json"

AGENTS, ADVISOR = "agents", "advisor"
ACCOUNTS = (AGENTS, ADVISOR)

# The owner's number, per account. Declared in `core/preferences.py`; named here
# so the schema and the enforcement cannot drift apart silently.
PREFERENCE_KEY = {AGENTS: "claude.agents_stop_at_percent",
                  ADVISOR: "claude.advisor_stop_at_percent"}

# WHICH ROW BELONGS TO WHICH ACCOUNT, AND THE ROWS SAY IT THEMSELVES. Two
# credential names exist on purpose, so advice cannot spend the subscription the
# agents do their ordinary work on -- `routing/supply.py:_cli_token` carries the
# same rule for the token. Read the credential, never the row's name: eight
# Claude rows declare no `config_dir` at all.
CREDENTIAL_ENV = {AGENTS: "VESPER_CLAUDE_CONFIG_DIR",
                  ADVISOR: "VESPER_CLAUDE_ADVISOR_CONFIG_DIR"}

# THE ONE ARGUMENT THAT MAKES THE ACCOUNT'S USAGE VISIBLE. Named once, used by
# both callers (`core/agents.py` and the supply wire), so a check can assert the
# argv that actually runs rather than a contract's description of it.
STREAM_FLAGS = ("--output-format", "stream-json", "--verbose")

# Plain names for the windows Claude reports. A settings row is read by the
# owner, and "seven_day" is not a sentence.
WINDOW_NAMES = {"five_hour": "its 5-hour session", "seven_day": "its week"}

WHOSE = {AGENTS: "the agents'", ADVISOR: "the advisor's"}
# The same two names the settings controls carry, so the reading above a control
# and the control's own label are plainly the same account.
SHORT = {AGENTS: "agents' account", ADVISOR: "advice account"}


def is_claude(binary: str) -> bool:
    """Whether this command is the Claude CLI, by the name it runs under."""
    return os.path.basename(str(binary or "")).lower().startswith("claude")


def _plain(window: str) -> str:
    return WINDOW_NAMES.get(window, str(window).replace("_", " "))


def _when(epoch_s: float) -> str:
    """"Wed 16 Sep at 19:00" -- in the owner's timezone, because they read it."""
    return time.strftime("%a %d %b at %H:%M", time.localtime(epoch_s))


class ClaudeLimits:
    """The owner's ceiling per account, and the readings it is compared against.

    Every path is an argument. The check that drives this must never write the
    real readings file or the real preferences, and a constructor that defaults
    quietly is how that happens by accident.
    """

    def __init__(self, *, state_path: Any = None, preferences_path: Any = None,
                 supply_path: Any = None) -> None:
        self.state_path = pathlib.Path(state_path) if state_path else PATH
        # None means core/preferences.py's own default, which is what the
        # runtime wants and what a test must not get.
        self.preferences_path = (pathlib.Path(preferences_path)
                                 if preferences_path else None)
        self.supply_path = pathlib.Path(supply_path) if supply_path else SUPPLY

    # ---- the two accounts -------------------------------------------------

    def config_dir(self, account: str) -> str | None:
        """Where this account's Claude configuration lives.

        THE SECRET FIRST, THE CONTRACT SECOND, AND NEVER NONE. Measured
        2026-09-14: `VESPER_CLAUDE_CONFIG_DIR` is not in `secrets.env` on this
        machine, so `workflows._agents_config_dir()` returned None -- and None is
        not "no account", it is the CLI's DEFAULT account, which is the owner's
        own personal one. VESPER's agents were spending the owner's subscription
        while every comment in this corpus said they must not, and nothing could
        see it because the fallback looked like an absence.
        """
        env = CREDENTIAL_ENV.get(account)
        if not env:
            return None
        try:
            from routing.supply import read_secrets
            v = read_secrets().get(env)
            if v:
                return str(v)
        except Exception:                                  # noqa: BLE001
            pass
        for raw in self._rows():
            if str(raw.get("credential_env") or "") == env and raw.get("config_dir"):
                return str(raw["config_dir"])
        return None

    def account_for(self, config_dir: str | None) -> str:
        """Which of the two accounts a config directory is.

        None is the agents' account and NOT the machine's default: an agent run
        that names no directory is still VESPER's work, and the owner's own
        account is not where VESPER's work goes.
        """
        if not config_dir:
            return AGENTS
        here = os.path.normpath(os.path.expanduser(str(config_dir)))
        for account in ACCOUNTS:
            declared = self.config_dir(account)
            if declared and os.path.normpath(os.path.expanduser(declared)) == here:
                return account
        return ADVISOR if ADVISOR in os.path.basename(here).lower() else AGENTS

    def account_for_row(self, raw: dict) -> str:
        """Which account a supply row runs on, from the credential it declares."""
        cred = str((raw or {}).get("credential_env") or "")
        return ADVISOR if cred == CREDENTIAL_ENV[ADVISOR] else AGENTS

    def token(self, account: str) -> str:
        """This account's headless token, or "" when it has none.

        THE CREDENTIAL DOES NOT LIVE IN THE CONFIG DIRECTORY -- it lives in the
        login keychain, which a launchd job cannot read (measured 2026-09-06:
        the same command answers "Please run /login" under the runtime's
        environment and succeeds from a shell). The token is the headless way in,
        and it is derived from the row's own credential name so two accounts
        cannot collapse into one. Both tokens were verified to answer on
        2026-09-14.
        """
        env = CREDENTIAL_ENV.get(account)
        if not env:
            return ""
        name = env.replace("_CONFIG_DIR", "") + "_TOKEN"
        try:
            from routing.supply import read_secrets
            return str(read_secrets().get(name, "") or "")
        except Exception:                                  # noqa: BLE001
            return ""

    def environment(self, env: dict, account: str,
                    config_dir: str | None = None) -> dict:
        """`env` with this account's directory and token, and no other's.

        THE INHERITED TOKEN IS CLEARED WHEN THIS ACCOUNT HAS ONE OF ITS OWN,
        for the reason the supply wire clears it: a token picked up from the
        surrounding environment would win for a rung whose account is
        deliberately different, and the separate directories exist precisely to
        stop that.
        """
        out = dict(env)
        where = config_dir or self.config_dir(account)
        if where:
            out["CLAUDE_CONFIG_DIR"] = os.path.expanduser(str(where))
        token = self.token(account)
        if token:
            out["CLAUDE_CODE_OAUTH_TOKEN"] = token
        else:
            out.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        return out

    # ---- what Claude says about itself ------------------------------------

    @staticmethod
    def parse_stream(stdout: str) -> dict:
        """What one run said: its answer, the account's usage, what it cost.

        TOLERANT OF NOT BEING JSON AT ALL, deliberately. The fixtures print
        plain text, an older CLI prints plain text, and a warning line arrives
        on stdout ahead of the stream. `json` says which shape was read, so a
        caller can fall back to the whole output rather than to nothing --
        turning every agent into a silent failure is a worse bug than the one
        this function exists for.
        """
        text = info = cost = error = None
        json_seen = False
        for line in str(stdout or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(ev, dict) or "type" not in ev:
                continue
            json_seen = True
            kind = ev.get("type")
            if kind == "rate_limit_event" and isinstance(ev.get("rate_limit_info"), dict):
                info = ev["rate_limit_info"]
            elif kind == "result":
                said = ev.get("result")
                if ev.get("is_error") or ev.get("subtype") not in (None, "success"):
                    # THE CLI'S OWN WORDS FOR ITS OWN FAILURE. A quota notice
                    # arrives here as a successful process with an error result,
                    # and passing it on as an answer is the exact confusion
                    # `_exhaustion` was written for.
                    error = str(said or ev.get("subtype") or "the run did not finish")
                else:
                    text = str(said or "")
                if isinstance(ev.get("total_cost_usd"), (int, float)):
                    cost = float(ev["total_cost_usd"])
        return {"json": json_seen, "text": text, "info": info,
                "cost": cost, "error": error}

    @staticmethod
    def reading_from(info: dict) -> dict:
        """The windows, the status, and whether the account is on paid usage."""
        info = info if isinstance(info, dict) else {}
        windows: dict = {}
        unified = info.get("unifiedWindows")
        if isinstance(unified, dict):
            for name, w in unified.items():
                if isinstance(w, dict) and isinstance(w.get("utilization"), (int, float)):
                    windows[str(name)] = {
                        "used": float(w["utilization"]),
                        "resets_at_s": float(w.get("resetsAt") or 0.0)}
        if not windows and isinstance(info.get("utilization"), (int, float)):
            # ONE WINDOW AND NO BREAKDOWN: the binding window is at the top
            # level. Recorded under the name the event gives it rather than
            # invented, so a later shape change is visible instead of silent.
            windows[str(info.get("rateLimitType") or "window")] = {
                "used": float(info["utilization"]),
                "resets_at_s": float(info.get("resetsAt") or 0.0)}
        return {"windows": windows,
                "status": str(info.get("status") or ""),
                "paid_extra": bool(info.get("isUsingOverage")),
                "at_ms": int(time.time() * 1000)}

    def record(self, account: str, info: dict) -> dict:
        """Keep what Claude just said about this account."""
        reading = self.reading_from(info)
        if not reading["windows"]:
            return reading
        state = self._read_state()
        state[account] = reading
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_name(f"{self.state_path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
        tmp.replace(self.state_path)
        return reading

    def reading(self, account: str) -> dict:
        rec = self._read_state().get(account)
        return rec if isinstance(rec, dict) else {}

    # ---- the owner's number, and what it decides ---------------------------

    def limit_percent(self, account: str) -> float:
        from core import preferences as P
        key = PREFERENCE_KEY[account]
        vals = P.read(self.preferences_path)
        try:
            return float(vals.get(key, P.SCHEMA[key][1]))
        except (TypeError, ValueError):
            return float(P.SCHEMA[key][1])

    def refusal(self, account: str, *, now_s: float | None = None) -> str | None:
        """The owner's own sentence for "not this account, not now" -- or None.

        NOTHING MEASURED YET IS NOT A REFUSAL. The first call is what produces
        the reading; refusing without one would stop VESPER on an account it has
        never looked at, with no way to ever look.
        """
        now = time.time() if now_s is None else float(now_s)
        rec = self.reading(account)
        whose = WHOSE.get(account, "this")
        if rec.get("paid_extra"):
            return (f"{whose} Claude account has moved onto paid extra usage, "
                    "which VESPER does not spend. It stopped there; that one is "
                    "yours to decide at your account page.")
        limit = self.limit_percent(account)
        live = [(name, w) for name, w in (rec.get("windows") or {}).items()
                # A window that has already rolled says nothing about now, and a
                # stale refusal nothing may call to refresh is a dead end.
                if float((w or {}).get("resets_at_s") or 0.0) > now]
        if not live:
            return None
        name, w = max(live, key=lambda kv: float(kv[1].get("used") or 0.0))
        used = float(w.get("used") or 0.0) * 100.0
        if used < limit:
            return None
        return (f"{whose} Claude account has used {used:.0f}% of {_plain(name)} "
                f"and your limit for it is {limit:.0f}%, so VESPER stopped using "
                f"it. Raise the limit in Settings -> Claude limits, or wait until "
                f"it resets {_when(float(w.get('resets_at_s') or 0.0))}.")

    def says(self, account: str) -> str:
        """One line for the settings row: the owner's number and the live one."""
        limit = self.limit_percent(account)
        rec = self.reading(account)
        windows = rec.get("windows") or {}
        who = SHORT.get(account, account)
        if not windows:
            return f"{who}: stops at {limit:.0f}%, nothing read from it yet"
        name, w = max(windows.items(), key=lambda kv: float(kv[1].get("used") or 0.0))
        used = float(w.get("used") or 0.0) * 100.0
        seen = time.strftime("%H:%M", time.localtime(float(rec.get("at_ms") or 0) / 1000.0))
        state = "stopped" if self.refusal(account) else "running"
        return (f"{who}: stops at {limit:.0f}%, {used:.0f}% of {_plain(name)} "
                f"used at {seen}, {state}")

    # ---- files -------------------------------------------------------------

    def _read_state(self) -> dict:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _rows(self) -> list:
        try:
            doc = tomllib.loads(self.supply_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return []
        rows = doc.get("provider")
        return rows if isinstance(rows, list) else []


_DEFAULT: ClaudeLimits | None = None


def default() -> ClaudeLimits:
    """The one VESPER itself uses: the real readings, the real preferences."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = ClaudeLimits()
    return _DEFAULT
