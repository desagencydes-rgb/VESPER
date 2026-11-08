# Installing VESPER on your own machine

This guide takes you from `git clone` to a running VESPER that uses **your**
accounts, **your** keys and **your** grants. Nothing in the repository is wired
to the original author's machine or accounts.

> **Honest scope.** Until now VESPER has been installed by one person, on one
> MacBook. These steps are taken from the build scripts and the code, not from
> a second installation. If a step fails for you, that is a real finding: open
> an issue with the command and its output.

---

## 0. What runs where, today

| Platform | What you get |
|---|---|
| **macOS 13+, Apple Silicon** | Everything: the Python core, every gate, and the native surfaces — the **island** (welded to the notch), the **home** (VESPER's own Desktop ground), the **showcase** window, the wake word and the globe-key summon |
| **macOS, Intel** | The core and gates. `build.sh` targets `arm64` only; change `-target` to try an Intel build |
| **Windows / Linux** | The Python core, the routing ladder and every gate. The F0–F6 acceptance suites were run on a Windows desktop and a Linux laptop. **There is no visual shell yet**: the decided frontend for everything except the island is Tauri, and nobody has built it |

---

## 1. Prerequisites

- **Python ≥ 3.11** (3.13 recommended). The system `python3` on macOS is 3.9,
  and **every gate fails on it while still exiting 0**. Install 3.13 from
  python.org, Homebrew or `uv`, then confirm:
  ```sh
  python3.13 --version
  ```
  The app looks for it at `~/.local/bin/python3.13`,
  `/opt/homebrew/bin/python3.13` or `/usr/local/bin/python3.13`.
- **macOS only: Swift.** `xcode-select --install` is enough. Full Xcode is not
  needed: the app is built with plain `swiftc`, with no package manager and no
  dependencies.
- **Optional CLIs for the subscription rungs:** `claude` (Claude Code) and/or
  `codex` (OpenAI Codex CLI). See §4.

The core has **no third-party Python dependencies**. `tools/` and
`verification/` are stdlib only, by rule.

---

## 2. Clone and prove the corpus is healthy

```sh
git clone https://github.com/desagencydes-rgb/VESPER.git
cd VESPER
python3.13 tools/ci/checks.py all
python3.13 tools/traceability_lint.py
python3.13 tools/reference_lint.py
```

Read the **summary line**, not the exit code. Measured in a fresh clone on
2026-11-08: **201/203**. The two reds are expected:
`wake-word-listens-locally-and-starts-once` needs the built `app/VESPER.app`
(§5), and `speech-is-egress-and-says-so` is a known open bug
(`VESPER_OPEN_WORK.md` §2.2).

The acceptance runners are slower, and each one is self-contained:

```sh
python3.13 verification/run_f0_acceptance.py     # … through run_f6_acceptance.py
python3.13 verification/stress_placement.py      # 160,000 property assertions
python3.13 verification/stress_fabric.py         # 180,000 property assertions
```

---

## 3. Your configuration folder

Everything that belongs to you lives **outside the repository**, in
`~/.config/vesper/`:

```sh
mkdir -p ~/.config/vesper
touch ~/.config/vesper/secrets.env
chmod 600 ~/.config/vesper/secrets.env
```

`secrets.env` is plain `NAME=value` lines. [`.env.example`](../.env.example)
lists the names. **Copy the names, never paste values into the repo.**

Check what VESPER can see. This prints lengths and shapes, never values:

```sh
python3.13 tools/ops/check_credentials.py
```

### 3.1 Provider keys — bring any subset

VESPER routes every model call through a ladder of **rungs**
(`contracts/policy/provider_supply.toml`). A rung whose credential is absent
simply does not exist. **You need at least one** for VESPER to think and talk;
with none, it runs, draws and listens, but cannot decide anything.

| Provider | Variable(s) | Privacy step before it may see private data | Egress class |
|---|---|---|---|
| Cloudflare Workers AI | `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | none | `E1-PRIVATE` |
| Groq | `GROQ_API_KEY` | enable Zero Data Retention | `E1` after the step |
| Ollama Cloud | `OLLAMA_API_KEY` | none | `E1-PRIVATE` |
| Mistral | `MISTRAL_API_KEY` | take the training opt-out | `E1` after the step |
| NVIDIA NIM | `NVIDIA_NIM_API_KEY` | terms unconfirmed | `E2-PUBLIC` |
| OpenRouter (free) | `OPENROUTER_API_KEY` | cannot be fixed | `E2-PUBLIC` only |
| Google AI Studio | `GOOGLE_API_KEY_A1` … `_A4` | cannot be fixed | `E2-PUBLIC` only |
| ElevenLabs (voice) | `ELEVENLABS_API_KEY` | — | speech |

**Egress class decides what a provider may see, before quota does.**
`E2-PUBLIC` providers never receive your private content. The full reasoning
and the step-by-step privacy settings are in
[`docs/planning/CREDENTIALS.md`](planning/CREDENTIALS.md) §3 and
[`docs/planning/PROVIDER_SUPPLY.md`](planning/PROVIDER_SUPPLY.md).

**More than one account of the same provider:** add numbered siblings
(`GROQ_API_KEY_2`, `_3`, …). `core/rung_credentials.py` turns each into its own
rung with the same policy. No code change is needed. Role-specific variables in
the contract (`GROQ_API_KEY_CHOOSER`, `MISTRAL_API_KEY_ARBITER`, …) let you put
a role on its own account; they are optional.

---

## 4. Claude and Codex accounts (subscription rungs)

VESPER can use a Claude or ChatGPT **subscription** through the official CLIs
in headless mode. This is **not** MCP, and it does not involve the desktop apps:
the apps are MCP *clients*, and VESPER needs something that answers a prompt
(`docs/planning/CREDENTIALS.md` §4.0).

**The rule that matters: VESPER gets its own account, never yours.** Each CLI
keeps its login per config directory, so VESPER's directory must be separate
from your personal one. If the variable below is unset, VESPER **does not**
fall back to `~/.claude`. That fallback once let VESPER spend its owner's
personal quota while every comment said it could not.

```sh
# in ~/.config/vesper/secrets.env
VESPER_CLAUDE_CONFIG_DIR=~/.config/vesper/claude-vesper          # VESPER's agents
VESPER_CLAUDE_ADVISOR_CONFIG_DIR=~/.config/vesper/claude-advisor # a second account for advice (optional)
VESPER_CODEX_HOME=~/.config/vesper/codex                         # Codex (optional) ...
VESPER_CODEX_CONFIG_DIR=~/.config/vesper/codex                   # ... the same folder: the contract names both
```

Log the agents' directory in as **VESPER's** account and verify which account
it bound to. The browser will happily reuse whichever login it already holds:

```sh
VESPER_OWNER_EMAIL=you@your-personal-account.com tools/ops/claude_rung2_login.sh
```

The script clears the isolated credential, walks you through the login, and
refuses the result if it came back as `VESPER_OWNER_EMAIL`. For a headless
token instead of a login, set `VESPER_CLAUDE_TOKEN` (or
`VESPER_CLAUDE_ADVISOR_TOKEN`, `VESPER_CODEX_TOKEN`). A per-account token
always wins over a shared `CLAUDE_CODE_OAUTH_TOKEN`.

**Spending limits are yours to set.** VESPER reads each account's 5-hour and
7-day utilisation on every call and stops at the percentages you choose in the
home's Settings. It never changes billing or account settings.

### MCP servers

`core/mcp.py` is a bounded MCP **client**. Every tool a server declares arrives
as **untrusted data** and starts at the highest authority level (ask first),
whatever the server says about itself. A tool runs at a lower level only if
you level it in a contract.

---

## 5. macOS: build the app

```sh
./app/island-macos/build.sh
```

This produces `app/VESPER.app`: one binary that is the island, the home and
every helper mode. The bundle carries a copy of the Python runtime and records
your checkout's path in `Contents/Resources/runtime/place.toml`, so **rebuild
after moving the repo**.

The bundle is **ad-hoc signed**, and that is a measured trade-off (see the
comment at the end of `build.sh`). A Developer ID certificate would give both a
stable permission identity and a working login item. Without one, macOS may
call it an unidentified developer the first time:
right-click → *Open*.

### 5.1 The grant trip — after your last build

macOS grants are keyed to the app's signature, and an ad-hoc rebuild can wipe
Microphone, Screen Recording and Speech. So build first, then grant.

```sh
open -n app/VESPER.app --args --request-grants   # asks for each one
open -n app/VESPER.app --args --grants           # reads back what it holds
```

**Always use `open -n`, never run the binary from a shell.** A request from a
terminal is attributed to the terminal, so it can come back "granted" with no
dialog, or crash. **Accessibility** has no prompt: tick VESPER in System
Settings → Privacy & Security → Accessibility. The globe-key summon does
nothing without it.

| Grant | What it is for |
|---|---|
| Accessibility | Globe-key summon; reading and driving windows (`ui.view`, `ui.act`) |
| Screen Recording | Seeing the screen; following your display in the showcase |
| Microphone + Speech | The wake word. On-device for `en-US`; other locales go to Apple's servers, which is egress and is labelled as such |
| Camera | Presence, carried as a flag rather than as images |
| Automation, Calendars | Notes and agenda bridges |

### 5.2 Run it

```sh
tools/install_island_agent.sh        # start now, at every login, and after a crash
```

On first start the home also registers the **globe watcher** and the **wake
listener** as their own login agents. Then:

- **Press the globe (fn) key three times** to call VESPER onto the Desktop you
  are on.
- Or switch to an **empty Desktop**: VESPER only *takes* a Desktop with none of
  your windows on it. That is a rule, not a bug (`VESPER_OPEN_WORK.md` §4.1).
- Stop and remove: `tools/install_island_agent.sh --uninstall`.

Logs are in `~/Library/Application Support/VESPER/` (`island.out`,
`fnwatch.out`, `arm.out`, `ground-log.txt`).

---

## 6. The runtime on its own (any platform)

```sh
python3.13 tools/ops/vesper_runtime.py --status
python3.13 tools/ops/vesper_runtime.py --say "what can you do right now?"
```

`VESPER_NODE_ID` names this node in the fabric and `VESPER_DATA_DIR` chooses
where its state lives. `core/config.py` documents both and what happens when
one is unset.

---

## 7. Onboarding checklist

- [ ] `python3.13 --version` prints 3.11 or newer
- [ ] `checks.py all` summary read, not just its exit code
- [ ] `~/.config/vesper/secrets.env` exists with mode `0600`
- [ ] At least one provider key, with its privacy step done (§3.1)
- [ ] `check_credentials.py` shows the keys you expect, with no placeholders
- [ ] If you use Claude/Codex: VESPER's own config dir, verified **not** your account (§4)
- [ ] macOS: built, **then** granted, both via `open -n` (§5.1)
- [ ] Accessibility ticked by hand
- [ ] Login agent installed; globe ×3 brings VESPER to your Desktop
- [ ] You have read `VESPER_OPEN_WORK.md` §2 for the bugs you are about to meet

## 8. Removing everything

```sh
tools/install_island_agent.sh --uninstall
launchctl bootout gui/$(id -u)/ai.vesper.island.fnwatch 2>/dev/null
launchctl bootout gui/$(id -u)/ai.vesper.island.wake 2>/dev/null
tccutil reset All ai.vesper.island
rm -rf ~/Library/Application\ Support/VESPER ~/.config/vesper
```
