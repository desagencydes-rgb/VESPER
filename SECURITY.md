# Security

VESPER acts on a real machine: it reads the screen, drives windows, runs
commands and spends model quota on accounts you give it. Treat a security
report about it accordingly.

## Reporting a vulnerability

**Do not open a public issue.** Use GitHub's private reporting instead:
*Security* tab → *Report a vulnerability*. Include what you ran, what you
expected, what happened, and the commit you ran it on.

There is no paid bounty and no guaranteed response time — the original author
has stepped back from day-to-day work (see the README). Reports still matter:
they are kept private until a fix or a written mitigation exists.

## What is in scope

- A path by which a key in `~/.config/vesper/secrets.env` reaches a log, a
  telemetry record, a published artifact, a prompt or any file VESPER writes.
  (`L-006` asserts a canary key appears in none of them; a way round it is a
  real finding.)
- Private content reaching a provider whose egress class is `E2_PUBLIC`
  (see `docs/planning/PROVIDER_SUPPLY.md`).
- An action that runs above the authority level its contract grants, or text
  arriving from outside (a web page, an MCP tool description, a file) raising
  the authority of an action (`INV-ACT-3`).
- The stop not stopping, or the stop going through the runtime (`INV-STOP-2`).
- VESPER spending one Claude account's quota while configured to use another.

## What you are responsible for

- **Your keys live outside the repository**, in `~/.config/vesper/secrets.env`
  with mode `0600`. `.gitignore` refuses `.env`, `.env.*`, `*.pem` and `*.key`,
  but nothing stops a key pasted into a tracked file. Never commit one; if you
  do, rotate it — deleting the commit does not un-publish it.
- **macOS grants** (Accessibility, Screen Recording, Microphone, Camera,
  Speech, Automation, Calendars) are given to the `VESPER.app` bundle you build.
  `open -n app/VESPER.app --args --grants` lists what it holds; the home's
  *Revoke every grant* action resets them all.

## Test values in this repository

`tools/ci/checks.py` contains strings shaped like credentials
(`AKIAIOSFODNN7EXAMPLE`, `sk-proj-…`, `ghp_…`, a PEM header). They are
deliberate fixtures for the redaction and leak checks and are not live keys.
A scan of the full history before publication found no real credentials.
