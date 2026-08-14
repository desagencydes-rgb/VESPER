# Desktop prep plan — making the site-A desktop VESPER's best node

**Status: MOSTLY DONE, checked 2026-08-13 later the same day.** Everything below §0 was a read-only inventory. Nearly all of it has since been executed (by hand, outside this doc's tracking) — this update just re-verifies current state against the plan so the record stays honest.

**Verified done:** Clawdbot (task + `.clawdbot\` both gone) · Ollama (binary gone) · llama.cpp canonicalized to VESPER's own copy at `VESPER-runtime\llama.cpp\`, the other three sibling-project copies no longer present · `Downloads` cleaned (58.73 GB → 0.13 GB) · disk free 35.1 GB → 150.1 GB · AnyDesk uninstalled · Docker Desktop service present but `Stopped`/`Manual` (not autostarting) · Rainmeter/Copilot not found autostarting · `profile_node.py` already ported off Ollama to llama-server (commit `a162042`) · **Opera Air autostart removed** (`HKCU\...\Run` entry deleted this session — Opera itself still installed, just no longer launches at login).

**Still open, deliberately not touched:** §3 power plan (`High performance` unchanged) — owner asked to defer this alongside the wake/remote-power work.

Not in the normative/enforced set (`docs/planning/` is outside `NORMATIVE_ROOTS`), so nothing here is CI-checked. It's a working note.

---

## 0. Snapshot, as observed today

| | |
|---|---|
| CPU / RAM | Ryzen 5 5500, 12 threads, 15.9 GB |
| GPU | AMD RX 6650 XT (8 GB VRAM) |
| Disk free (C:) | **35.1 GB**, up from 22.3 GB earlier today — your cleanup is already working |
| Power plan | **High performance** (active now) |
| `Downloads` folder | **58.73 GB** — the single largest reclaimable chunk found |
| SysMain (Superfetch) | Running, Automatic |
| Memory compression status | Couldn't read — `Get-MMAgent` needs an elevated (Admin) PowerShell |
| Biggest RAM consumer, live | **Opera Air** — dozens of processes, several hundred MB each, several **GB** combined. By far the largest lever available |

---

## 1. CONFIRMED — you already decided these, no further discussion needed tomorrow

### Remove Clawdbot entirely
Found as a **Scheduled Task**, not a normal install:
- Task name: `Clawdbot Gateway`, state `Ready`, author `ULTRA PC`, last ran 2026-08-11
- Points at: `C:\Users\ULTRA PC\.clawdbot\gateway.cmd`

**Removal steps (tomorrow):**
1. `Unregister-ScheduledTask -TaskName "Clawdbot Gateway" -Confirm:$false`
2. Delete `C:\Users\ULTRA PC\.clawdbot\` entirely
3. Re-search for any other copy (services, other scheduled tasks, other install folders, other user profiles) — today's search only checked the obvious places once; do a clean second pass before calling it done, since you said **all copies**

### Remove Ollama entirely — keep only llama.cpp + Vulkan
You confirmed: Ollama doesn't do GPU acceleration properly on this AMD card; llama.cpp's Vulkan build is what actually works, and it's already installed. Ollama goes.

**What's actually here:**
- Binary: `C:\Users\ULTRA PC\AppData\Local\Programs\Ollama\ollama.exe`
- Startup shortcut: `start-ollama-hidden.vbs` in your Startup folder, which runs `C:\Projects\HyperOrch\start-ollama-gpu.bat`
- Models directory: `~\.ollama\models` — **0 GB, empty**. It was never actually used here, consistent with it not working.

**Removal steps (tomorrow):**
1. Uninstall Ollama properly if it's in Add/Remove Programs; otherwise delete the `Programs\Ollama\` folder directly
2. Delete `start-ollama-hidden.vbs` from the Startup folder
3. Delete `~\.ollama\` (empty, but remove for cleanliness)
4. `HyperOrch\start-ollama-gpu.bat` references Ollama — **that's a different project's file, not VESPER's; flag it to yourself, don't touch it as part of VESPER cleanup** unless you want me to
5. Confirm nothing else references port `11434` or `ollama.exe` afterward

**llama.cpp — needs one decision from you tomorrow, not a removal:** there are at least **four copies** already on this machine, in three different sibling projects:
- `aegis\AEGIS\external\llama-cpp\` (llama-cli + llama-server)
- `aegis\NUMEN\bin\vulkan\llama-server.exe`
- `ARCHONEC\...\llama_bin\llama-server.exe`
- `ARCHONEC\...\temp_llama_vulkan\` (the folder name suggests this one's a throwaway test copy)

**Question for tomorrow:** which one is your trusted, working Vulkan build? VESPER's own tooling (`tools/spike/profile_node.py`) needs to point at one specific binary rather than borrow from another project's folder — either you tell me which copy is canonical, or we get VESPER its own dedicated copy so nothing depends on another project's directory surviving untouched.

---

## 2. RAM — what actually helps, and one common misconception to avoid

**The real lever: Opera Air.** It's not close — it dwarfs every other process combined. For "leave more RAM free when VESPER is running and nobody's at the keyboard," the highest-value single action is **closing Opera** (or at minimum stopping it autostarting) when the machine is unattended. Everything else is secondary.

**A misconception worth naming honestly, since this whole project runs on not fooling ourselves with numbers:** disabling **SysMain** is a common "free up RAM" tip, but it's mostly not true. SysMain's cached data sits in the **Standby** list, which Windows already reclaims instantly the moment something else actually needs that memory — it isn't memory that's unavailable. Disabling it mainly removes a *speed* benefit (apps you reopen load slower) without reliably freeing usable RAM. I'd leave it alone rather than "fix" something that isn't actually broken.

**Concrete idle-RAM proposal for tomorrow:**
- Stop Opera Air autostarting (it's in your Startup list); close it when the machine is meant to be VESPER-only
- Leave SysMain as-is
- Revisit Docker Desktop's autostart (see §4 — not decided yet, your call)

---

## 3. Power — reduce draw when VESPER runs unattended

Right now the active plan is **High performance**, which is the wrong plan for an unattended machine — it disables several OS-level power-saving behaviors (aggressive USB suspend, PCIe link power management, display timeout tuning) that cost nothing when no one's looking at the screen.

**What VESPER needs to stay true to, though:** the machine must **stay awake and reachable** — no full sleep — since VESPER is meant to keep running. So the target isn't "sleep the PC," it's "cut everything that only matters when a human is looking at the screen."

**Proposal:**
- Switch to a custom or **Balanced** plan when the machine is VESPER-only: display off quickly, disk/USB power-saving on, CPU never forced to max clock at idle
- **Never** allow automatic sleep/hibernate while VESPER is meant to be running
- Real automation (VESPER itself detecting "no one's here, drop to power-saving mode") is a genuine future capability, not something to fake with a fragile script today — for now this is a manual plan switch, done properly once, revisited when VESPER can actually reason about presence

---

## 4. NOT yet decided — your call tomorrow, item by item

These are candidates I found, not conclusions. I'm listing them because they're real, not because I've decided any of them should go.

| Item | What it is | Why it's here |
|---|---|---|
| **Docker Desktop** | 3.1 GB install, autostarts | Heavy for something that may not run daily. Keep autostart, disable autostart-but-keep-installed, or leave as-is — your call |
| **Two VPN clients autostarting** | NordVPN **and** ExpressVPN both launch at login | Unusual to run both; worth knowing since we're separately designing our **own** WireGuard mesh (SPIKE-009) — two more VPN stacks in the mix is worth being deliberate about, not accidental |
| **Rainmeter** | Desktop widget engine, autostart | Cosmetic only; small but free resource if you don't need it |
| **Microsoft Copilot autostart** | Autostarts in the background | Another AI assistant quietly running alongside VESPER — worth a conscious decision either way |
| **AnyDesk** | Remote-desktop tool, autostarts system-wide (Common Startup) | Not touching this without asking — it may be your existing way of reaching this machine remotely, which is directly relevant to what we're building |
| **`Downloads` — 58.73 GB** | Never fully enumerated (the scan got cut off) | Needs a proper pass tomorrow: list largest files, you decide what goes — **no blanket delete**, this is exactly the kind of folder that quietly holds something you needed |
| **Edge autostart** | Launches at login | Minor; your call |

---

## 5. Outstanding from today's investigation (got cut off, redo tomorrow)

Two PowerShell calls hit a timeout while walking large directories — not a failure, just an expensive read-only search colliding with the exact large model folders you're mid-way through relocating. Harmless, but these need a clean re-run:
- Full top-10-largest-files list for `Downloads`
- Whether Docker Desktop is actually running right now, or just installed
- `Get-MMAgent` (memory compression status) — needs an elevated PowerShell session

---

## 6. Engineering follow-up this surfaced (not a machine change — a code change, later)

`tools/spike/profile_node.py`, written today for SPIKE-001, currently only knows how to talk to **Ollama**. Since Ollama is leaving and llama.cpp/Vulkan is the real runner, the harness needs a llama.cpp backend (via `llama-server`'s HTTP API, which is what actually runs the sustained-throughput measurement) before any real SPIKE-001 numbers can be collected on this machine. This is normal engineering follow-up, not urgent tonight — noted here so it isn't lost.

---

## 7. Suggested order for tomorrow

1. Remove Clawdbot (task + directory + second sweep for other copies)
2. Remove Ollama (binary + startup script + empty models dir)
3. You tell me which llama.cpp copy is canonical, or we give VESPER its own
4. Decide the §4 candidates (Docker, dual VPN, Rainmeter, Copilot, AnyDesk, Edge)
5. Stop Opera autostarting; switch to a power-saving plan for VESPER-only time
6. Clean pass on `Downloads` (list first, delete only what you confirm)
7. Re-run the three cut-off checks from §5
8. Update `tools/spike/profile_node.py` to target llama.cpp instead of Ollama
9. Then, and only then, run the real SPIKE-001 measurement on this machine
