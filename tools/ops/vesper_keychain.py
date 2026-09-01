#!/usr/bin/env python3
"""Move VESPER's credentials out of a plaintext file and into the Keychain.

WHY THIS EXISTS. `~/.config/vesper/secrets.env` is mode 0600 and readable by
anything running as the owner -- which is every process on this machine,
including VESPER itself and anything that ever talks it into reading a file.
That is the one exact match between this system and OpenClaw's documented
compromise, and it has been the top of the open-defects list since the
landscape survey.

THE ORDER IS DELIBERATE AND SO IS THE FALLBACK. `read_secrets` reads the file
first and lets the keychain overlay it, so a credential moved here wins even
while a stale copy remains in the file -- one step, not edit-both-and-hope. If
the keychain cannot be read the file still answers, because VESPER runs
unattended and no credential at all is a worse failure than a credential in a
0600 file.

NOTHING HERE PRINTS A VALUE. `--status` reports names and lengths, which is
enough to catch a truncated paste and not enough to leak anything, and the
whole tool is meant to be safe to run in a terminal that scrolls into a
transcript. That is the same rule `check_credentials.py` follows.

MIGRATION DOES NOT DELETE THE FILE. Removing the owner's only copy of a
credential on their behalf, unattended, is not a decision this tool gets to
make. It prints what to remove and leaves the removal to a person.
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from routing.supply import (KEYCHAIN_SERVICE, SECRETS,  # noqa: E402
                            keychain_secret, read_secrets)

SECURITY = "/usr/bin/security"


def _file_only() -> dict:
    """The file's own contents, with no keychain overlay.

    `read_secrets` overlays, which is right for the runtime and wrong here: a
    migration tool comparing the overlaid view against the keychain would
    report every already-migrated key as "still in the file".
    """
    out: dict[str, str] = {}
    import re
    if not SECRETS.exists():
        return out
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*(?:export\s+)?([A-Z0-9_]+)\s*=(.*)", line)
        if not m:
            continue
        v = m.group(2).split("#", 1)[0].strip().strip('"').strip("'")
        if v.startswith("$"):
            v = out.get(v.lstrip("$"), "")
        out[m.group(1)] = v
    return out


def status() -> int:
    infile = _file_only()
    if not infile:
        print(f"no credentials found in {SECRETS}")
        return 0
    print(f"{'variable':34} {'file':>6} {'keychain':>9}  state")
    print("-" * 74)
    both = migrated = filed = 0
    for name in sorted(infile):
        fv = infile.get(name) or ""
        kv = keychain_secret(name)
        if kv and fv:
            state, _ = "in both -- safe to remove from the file", both
            both += 1
        elif kv:
            state = "keychain only"
            migrated += 1
        else:
            state = "PLAINTEXT ONLY"
            filed += 1
        print(f"{name:34} {len(fv):>6} {len(kv):>9}  {state}")
    print("-" * 74)
    print(f"{migrated} in the keychain only, {both} in both, {filed} still "
          "plaintext only")
    if both:
        print("\nThe ones marked 'in both' are already served from the "
              "keychain.\nRemoving those lines from the file is a person's "
              "decision, not this tool's.")
    return 0


def migrate(names: list, dry_run: bool) -> int:
    infile = _file_only()
    targets = [n for n in (names or sorted(infile)) if infile.get(n)]
    if not targets:
        print("nothing to migrate")
        return 1
    for name in targets:
        value = infile[name]
        if keychain_secret(name) == value:
            print(f"  {name:34} already there, unchanged")
            continue
        if dry_run:
            print(f"  {name:34} would add {len(value)} characters")
            continue
        # `-U` updates an existing item rather than creating a duplicate, and
        # the value goes in as an argument to `security` rather than through a
        # shell, so it never reaches a shell history.
        r = subprocess.run(
            [SECURITY, "add-generic-password", "-a", name,
             "-s", KEYCHAIN_SERVICE, "-w", value, "-U"],
            capture_output=True, text=True, check=False, timeout=15)
        if r.returncode != 0:
            # The stderr of `security` does not contain the value; it names the
            # item. Printed because a silent failure here would look like a
            # successful migration.
            print(f"  {name:34} FAILED: {r.stderr.strip()[:70]}")
            continue
        back = keychain_secret(name)
        # READ THE WORLD BACK. `security` exiting 0 is not the credential being
        # retrievable, and this tool's whole value is that afterwards the
        # keychain answers.
        print(f"  {name:34} stored and read back: "
              f"{'OK' if back == value else 'MISMATCH'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--status", action="store_true",
                    help="which credentials are where. Never prints a value.")
    ap.add_argument("--migrate", action="store_true",
                    help="copy credentials from the file into the keychain")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("names", nargs="*", help="specific variables, or all")
    a = ap.parse_args()
    if a.migrate:
        return migrate(a.names, a.dry_run)
    return status()


if __name__ == "__main__":
    sys.exit(main())
