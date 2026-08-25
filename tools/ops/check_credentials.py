#!/usr/bin/env python3
"""Report which provider credentials are present. NEVER prints a value.

WHY IT PRINTS LENGTHS AND NOT VALUES. This file's whole job is to be safe to
run with someone watching, in a terminal that scrolls into a transcript. A
checker that echoes a key to prove it found one has leaked it to every place
that output travels. Length and prefix-shape are enough to catch the real
failure -- a truncated paste, or a value that is still the placeholder.
"""
from __future__ import annotations
import os, re, sys, pathlib

SECRETS = pathlib.Path.home() / ".config" / "vesper" / "secrets.env"

# (var, label, egress after the privacy step, privacy action still required)
SPEC = [
    ("CLOUDFLARE_ACCOUNT_ID", "Cloudflare account", "E1-PRIVATE", None),
    ("CLOUDFLARE_API_TOKEN",  "Cloudflare token",   "E1-PRIVATE", None),
    ("GROQ_API_KEY",          "Groq",               "E1-PRIVATE", "Zero Data Retention"),
    ("OLLAMA_API_KEY",        "Ollama Cloud",       "E1-PRIVATE", None),
    ("MISTRAL_API_KEY",       "Mistral",            "E1-PRIVATE", "training opt-out"),
    ("NVIDIA_NIM_API_KEY",    "NVIDIA NIM",         "E2-PUBLIC (terms unconfirmed)", None),
    ("OPENROUTER_API_KEY",    "OpenRouter",         "E2-PUBLIC (structural)", None),
    ("GOOGLE_API_KEY",        "Google AI Studio",   "E2-PUBLIC (structural)", None),
]

def load() -> dict:
    if not SECRETS.exists():
        return {}
    out = {}
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        m = re.match(r'\s*export\s+([A-Z0-9_]+)=(.*)', line)
        if m:
            v = m.group(2)
            # STRIP THE TRAILING COMMENT BEFORE MEASURING. Without this the
            # reported length includes '   # alias to the line above', and the
            # checker reports a 15-char alias as 64 characters of key. A
            # measurement tool that is wrong about what it measured is worse
            # than no tool -- it launders a guess into a number.
            if '#' in v:
                v = v.split('#', 1)[0]
            out[m.group(1)] = v.strip().strip('"').strip("'")
    return out

def main() -> int:
    if not SECRETS.exists():
        print(f"MISSING: {SECRETS}"); return 1
    mode = SECRETS.stat().st_mode & 0o777
    print(f"file: {SECRETS}")
    print(f"perms: {oct(mode)}" + ("" if mode == 0o600 else "  <-- SHOULD BE 0600"))
    print()
    env, blockers_missing = load(), []
    for var, label, egress, privacy in SPEC:
        v = env.get(var, "")
        if not v:
            state = "-- not set"
        elif len(v) < 12:
            state = f"?? set but only {len(v)} chars -- truncated paste?"
        else:
            state = f"OK set ({len(v)} chars)"
        note = f"  [{egress}]"
        if privacy:
            note += f"  requires: {privacy}"
        print(f"  {label:<20} {state}{note}")
        if var in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "GROQ_API_KEY") and not v:
            blockers_missing.append(var)
    print()
    if blockers_missing:
        print("BLOCKED: rung 1 needs " + ", ".join(blockers_missing))
        return 1
    print("Rung 1 is credentialed. Privacy actions above are per-account and")
    print("cannot be verified from here -- they live in each provider's console.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
