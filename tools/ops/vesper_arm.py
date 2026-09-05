#!/usr/bin/env python3
"""Arm VESPER's autonomy by minting enable tokens it cannot mint for itself.

WHY AUTONOMY IS AN ON SWITCH THAT KEEPS FALLING OFF. `core/interlock.py` is a
dead-man's switch, not a stop button, and A-031.2 says why: a kill signal fails
OPEN. Cut the wire and the stop never arrives, so the thing runs forever. Cut
the wire on this and the tokens stop arriving, so it stops. Every failure --
crash, unplug, wedge, compromise -- fails toward stopped.

So autonomy runs only while a fresh token is present, and this is the process
that keeps handing them over. Stop this process and VESPER stops acting on its
own within one token lifetime, having been told nothing.

WHAT IS ACTUALLY ENFORCED, AND WHAT IS NOT. The design says the minting key is
"not reachable from the runtime". On a single machine where both run as the
same user, that is not enforceable by the operating system and it would be
dishonest to claim it is. What IS enforced, and what the threat model actually
needs:

  - `SafetyInterlock` has no mint method. Not a guarded one -- none. `mint_token`
    exists only to refuse, so there is no path to misconfigure.
  - The token directory is in VESPER's PROHIBITED tier (`SELF_DEFEATING_DIRS`),
    so `fs.write` and `fs.edit` refuse it at any level, including under an L5
    grant. A steered proposer cannot write itself a token.
  - Replay is refused by token_id, so a token captured off disk cannot extend
    autonomy a second time.

The adversary this defends against is a wrong or steered proposer inside
VESPER, not a person with a shell. A person with a shell can already do
anything; the interlock was never the thing standing between them and the
machine.

RUN IT UNDER LAUNCHD, NOT FROM A TERMINAL. A minter that dies with your shell
session arms VESPER for exactly as long as the window is open, which is the
opposite of a lifetime you chose. `--install` writes the LaunchAgent.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import secrets
import subprocess
import sys
import time

STATE = pathlib.Path.home() / "Library" / "Application Support" / "VESPER"
TOKEN_DIR = STATE / "interlock"
TOKEN_PATH = TOKEN_DIR / "enable_token.json"
KEY_PATH = pathlib.Path.home() / ".config" / "vesper" / "interlock.key"

LABEL = "ai.vesper.arm"
# What the bundle calls its minter. The one that should be running.
BUNDLE_LABEL = "ai.vesper.island.arm"
PLIST = pathlib.Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"

# How long one token is good for. Short enough that a dead minter stops VESPER
# promptly, long enough that a slow tick does not flap it off and on.
TTL_MS = 90_000
# How often a fresh one is written. Comfortably inside the TTL so an ordinary
# scheduling delay never leaves a gap.
MINT_EVERY_S = 30


def _key() -> str:
    """The minting secret, created once, 0600, outside the repo."""
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not KEY_PATH.exists():
        KEY_PATH.write_text(secrets.token_hex(32), encoding="utf-8")
        KEY_PATH.chmod(0o600)
    return KEY_PATH.read_text(encoding="utf-8").strip()


def mint(principal: str = "owner") -> dict:
    """One token, written where the runtime will find it.

    WRITTEN WHOLE, THEN MOVED. A runtime reading a half-written token sees
    malformed JSON, treats it as no token at all, and stops -- which is the
    safe direction but is also a stop nobody asked for. `os.replace` is atomic
    on this filesystem, so the runtime sees either the old token or the new one.
    """
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    import hashlib
    import hmac
    now = int(time.time() * 1000)
    tid = secrets.token_hex(8)
    body = f"{tid}.{now}.{TTL_MS}.{principal}"
    sig = hmac.new(_key().encode(), body.encode(), hashlib.sha256).hexdigest()
    token = {"token_id": tid, "issued_at_ms": now, "ttl_ms": TTL_MS,
             "issued_by": principal, "signature": sig}
    tmp = TOKEN_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(token), encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, TOKEN_PATH)
    return token


def _launch_argv() -> list:
    """What launchd should start: the bundle if there is one, else this script.

    THE MODE EXISTING IS NOT THE MODE RUNNING. `VESPER --arm` was added and the
    plist still named `python3 .../vesper_arm.py`, so the process actually
    keeping autonomy alive stayed outside the bundle -- the doctrinal fix
    committed, and reality unchanged. launchd restarts whatever this array says
    and nothing else, so this is the only place the switch can happen.

    IT FALLS BACK RATHER THAN FAILING. A checkout with no built app must still
    be able to arm itself; what it must not do is silently keep using the bare
    interpreter once a bundle exists.
    """
    here = pathlib.Path(__file__).resolve()
    cands = [here.parents[2] / "app" / "VESPER.app" / "Contents" / "MacOS" / "VESPER"]
    # AND FROM INSIDE THE BUNDLE. `build.sh` ships this file at
    # Contents/Resources/runtime/tools/ops/, where parents[2] is `runtime` and
    # the repo layout above finds nothing. Running `VESPER --arm --install`
    # therefore executed the BUNDLE's copy, fell through to the fallback, and
    # wrote a plist naming `python3 <bundle>/vesper_arm.py` -- moving the
    # minter further from the app rather than into it, while reporting success.
    for parent in here.parents:
        if parent.name == "Contents":
            cands.append(parent / "MacOS" / "VESPER")
            break
    for app in cands:
        if app.exists() and os.access(app, os.X_OK):
            return [str(app), "--arm", "--run"]
    return [sys.executable, str(here), "--run"]


def install() -> int:
    """REFUSES. The bundle owns the minter now.

    THERE WERE SEVEN MINTERS ON THIS MACHINE AT ONCE, every one of them
    presenting a token, and the log recorded a replay refusal for each. Two
    ways to install the same agent is how that happens: this function wrote
    `ai.vesper.arm` while `build.sh` wrote `ai.vesper.island.arm`, both
    RunAtLoad, both KeepAlive, neither aware of the other.

    The bundle's copy is the one that survives, for the reason every other
    helper became a mode of the app binary: a minter running outside the bundle
    whose autonomy it keeps alive is a second identity on the machine with a
    claim on VESPER's authority. `--run` and `--once` are untouched; it is only
    the second INSTALLER that is gone.
    """
    print("refused: the minter is installed by the app bundle, as "
          f"{BUNDLE_LABEL}, and re-registered on every build.")
    print("  install it:  bash app/island-macos/build.sh")
    print(f"  check it:    launchctl list | grep {BUNDLE_LABEL}")
    print("  this file still mints: --run (loop) and --once (single token).")
    if PLIST.exists():
        print(f"\nNOTE: a stale {LABEL} plist exists at {PLIST}.")
        print("  It is a second minter. Remove it:")
        print(f"    launchctl bootout gui/$(id -u)/{LABEL} 2>/dev/null")
        print(f"    rm {PLIST}")
    return 2


def _install_disabled() -> int:
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    argv = "".join(f"\n    <string>{a}</string>" for a in _launch_argv())
    PLIST.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key><array>{argv}
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{STATE / 'arm.out'}</string>
  <key>StandardErrorPath</key><string>{STATE / 'arm.err'}</string>
</dict></plist>
""", encoding="utf-8")
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"],
                   capture_output=True, check=False)
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(PLIST)],
                       capture_output=True, text=True, check=False)
    if r.returncode != 0:
        print(f"launchctl bootstrap failed: {r.stderr.strip()}")
        return 1
    print(f"armed: {LABEL} is loaded and minting every {MINT_EVERY_S}s")
    print("       stop it with:  launchctl bootout gui/%d/%s" % (uid, LABEL))
    return 0


def status() -> int:
    if not TOKEN_PATH.exists():
        print("no enable token: autonomy is STOPPED")
        return 0
    try:
        t = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    except Exception as exc:                        # noqa: BLE001
        print(f"the token is unreadable ({exc!r}): autonomy is STOPPED")
        return 0
    left = (t["issued_at_ms"] + t["ttl_ms"] - int(time.time() * 1000)) / 1000
    print(f"token {t['token_id']} from {t['issued_by']}: "
          f"{'FRESH' if left > 0 else 'EXPIRED'}, {left:.0f}s remaining")
    r = subprocess.run(["launchctl", "list", LABEL], capture_output=True,
                       text=True, check=False)
    print("minter:", "loaded" if r.returncode == 0 else "NOT LOADED")
    return 0


def run() -> int:
    while True:
        try:
            mint()
        except Exception as exc:                    # noqa: BLE001
            # A MINTER THAT DIES ON ONE BAD WRITE DISARMS VESPER SILENTLY, and
            # the whole point is that stopping is loud in the log even when it
            # is caused by nothing happening. Report and keep trying.
            print(f"mint failed: {exc!r}", flush=True)
        time.sleep(MINT_EVERY_S)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--install", action="store_true",
                    help="install and load the LaunchAgent that keeps VESPER armed")
    ap.add_argument("--run", action="store_true", help="mint forever (launchd uses this)")
    ap.add_argument("--once", action="store_true", help="mint a single token")
    a = ap.parse_args()
    if a.install:
        return install()
    if a.run:
        return run()
    if a.once:
        t = mint()
        print(f"minted {t['token_id']}, good for {t['ttl_ms'] // 1000}s")
        return 0
    return status()


if __name__ == "__main__":
    sys.exit(main())
