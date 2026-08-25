# Node 1 enrolment — a self-contained handoff

**You are a Claude Code session running on node 1, the VESPER desktop, under
Windows 11.** You have no memory of the conversation that produced this
document. Everything you need is here.

Your job: make this machine usable by VESPER **with nobody logged in**, then
enrol it so the router can measure it. Roughly 20 minutes.

---

## Before anything: the doctrine that governs this session

Read `CLAUDE.md` and `MEMORY.md` in the repo root before reasoning. Four rules
bind every step below, and they are checked mechanically, not by opinion:

- **An instrument's self-report is not evidence.** A launcher returning 0 is
  not a running process. A service marked `Running` is not a reachable port.
  **Re-read the world after acting**, every time.
- **`INV-HW-2` — throughput is measured, never declared.** `UNKNOWN` means
  `UNAVAILABLE`, fail-closed. Do not write a number you did not measure.
- **`INV-HW-1` — no product names in routing, resource or policy paths.**
  Anything you add under `core/`, `routing/`, `contracts/` names a *profile*,
  never a device. `CI-007` scans for this.
- **ICMP is blocked both ways on this network. Ping proves nothing.** Test
  TCP.

**Do not proceed past a step you have not verified.** Each step below states
its own verification. A step whose check fails is a stop, not a warning.

---

## Step 0 — establish where you are

```powershell
hostname                       # expect DESKTOP-F73BBDB
[System.Environment]::OSVersion.Version
Get-CimInstance Win32_Processor | Select-Object Name, NumberOfLogicalProcessors
```

Expected, from `MEMORY.md` §1: Ryzen 5 5500, 12 logical cores, 15.9 GB DDR4,
RX 6650 XT with **7.2 GB usable VRAM (measured)**, Windows 11.

**If the hostname does not match, stop and say so.** This document is written
for one machine and `INV-PLACE-3` means VESPER is not pinned to it — but an
enrolment record attributed to the wrong host is worse than none.

---

## Step 1 — the four services

The design decision this implements: **Windows services run as SYSTEM at boot,
before any user logs in.** That is what makes the login screen irrelevant to
VESPER and is why this machine needs no auto-login, no second profile and no
stored password. Do not propose those; they were considered and rejected.

### 1a. Tailscale — as a service, not a tray app

Install from `tailscale.com/download/windows`. During install choose the
**service** ("run unattended" / start at boot), not tray-only. Then:

```powershell
Get-Service Tailscale | Select-Object Name, Status, StartType
tailscale status
tailscale ip -4
```

**Verify:** `StartType` is `Automatic` and `Status` is `Running`. Record the
tailnet name and the IPv4 — the MacBook side needs both.

**Then, in the browser at `login.tailscale.com` → Machines → this device →
⋯ → Disable key expiry.** This is not optional and it is not cosmetic: node
keys expire after 180 days by default, after which the device drops off the
tailnet and demands an interactive browser re-login. On a machine that is off
for weeks at a time that guarantees the link is dead exactly when it is needed.
The owner has hit this before.

**Verify:** the Machines row shows no expiry date.

### 1b. OpenSSH Server — built in, just enable it

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd
```

**Verify from the MacBook, not from here** — a service reporting `Running` is
a self-report:

```bash
nc -z -G 5 <tailscale-ip> 22 && echo "OPEN"
```

### 1c. `llama-server` as a service — build `b10405` ONLY

> **There are two `llama-server.exe` on this machine and only one is
> comparable.** Use `C:\Projects\VESPER-runtime\llama.cpp\llama-server.exe` —
> the ~9 KB launcher, build `b10405-e79e4bf66`, Vulkan. **Not** the ~14 MB one
> in `C:\Tools`. A figure without its build tag is not a measurement, and a
> figure from the wrong build is a wrong measurement that looks right.

Confirm which you have before wrapping anything:

```powershell
(Get-Item "C:\Projects\VESPER-runtime\llama.cpp\llama-server.exe").Length
& "C:\Projects\VESPER-runtime\llama.cpp\llama-server.exe" --version
```

**Verify:** the version string contains `b10405`. If it does not, **stop** and
report what it does contain.

Wrap it as an auto-start service (`sc.exe create`, or NSSM if present). Bind
it to the Tailscale interface or to localhost — **not to `0.0.0.0`**.
`contracts/policy/admission_baseline.toml` grades this node on
`no_unexpected_external_listeners`, and a service on `0.0.0.0` works directly
against its own admission.

**Verify** by asking the server what it is, which is also the liveness check:

```powershell
curl.exe -s http://127.0.0.1:8080/props
```

The response carries `build_info`. That is the attributable identity
`routing/http_completion.py` records; a provider that cannot say which build
answered produces unauditable numbers.

### 1d. VESPER node agent

**Not yet written.** If `tools/ops/node_agent_win.py` does not exist in the
repo, skip this step and say so in your report — do not improvise one. Its
job (presence, health, quota reporting) is stage 9 of
`docs/planning/MULTI_ROUTE.md` and it is being built on the MacBook.

---

## Step 2 — Wi-Fi profile for all users

**The trap this avoids:** a per-user Wi-Fi profile connects only *after*
someone signs in. Nobody will be signing in. The machine boots on schedule,
sits with no network, and presents as "powered on but unreachable" — the least
diagnosable failure available.

```powershell
netsh wlan show profiles
netsh wlan set profileparameter name="<SSID>" connectionmode=auto
netsh wlan show profiles name="<SSID>"
```

**Verify:** the profile reports *All User Profile*, and connection mode is
"Connect automatically". If it shows a current-user profile, delete and
re-add it with `netsh wlan add profile ... user=all`.

**Then verify it for real:** sign out (do not shut down), wait for the login
screen, and from the MacBook confirm TCP/22 still answers. A machine reachable
only while someone is logged in has failed this step while appearing to pass it.

---

## Step 3 — hibernate, not shutdown

**Why this and not a BIOS schedule.** Wake timers work from **S4 hibernate**
and do **not** work from S5 full shutdown — in S5 Task Scheduler is not
running to fire anything. S4 is powered-down, not sleep, and draws essentially
what a full shutdown draws. So hibernate gives the wake path for free and the
BIOS is off the critical path.

```powershell
powercfg /hibernate on
powercfg /a                          # confirm Hibernate is listed as available
```

Wake timers must be permitted on the active scheme:

```powershell
powercfg -setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
powercfg -setactive SCHEME_CURRENT
```

`tools/ops/alarm_night.py` already builds the scheduled task with
`New-ScheduledTaskSettingsSet -WakeToRun` and **reads the flag back** to
confirm it took — reuse it rather than writing a second mechanism. Two
mechanisms writing the same wake state is the failure mode
`tools/ops/alarm_wake_linux.py` was written to avoid; its header explains why.

**Verify, and this one must be a live rehearsal, not a flag read.** Arm a task
5 minutes out, `shutdown /h`, and watch whether the machine rises and the task
runs. `powercfg -lastwake` afterwards says what woke it. **A scheduled task
that exists is not a wake that happened** — the alarm work on this fabric
produced five rehearsals and five silences on exactly this kind of assumption.

**Optional while you are here:** BIOS → *Advanced → Wake Up Event Setup* →
enable *Resume by RTC Alarm*. It buys recovery from a true power-off after a
power cut. Nothing depends on it.

---

## Step 4 — enrol the node

```powershell
python tools/spike/probe_host_facts.py
```

That returns facts with the command that produced each. **Do not fill in
`security_baseline` yourself.** `contracts/policy/admission_baseline.toml`
grades; the probe measures; the split is deliberate — ADR-007 D2 forbids a node
deciding its own passing grade, and a probe that graded itself would be a node
raising its own ceiling.

Note that `admission_baseline.toml` requires `disk_encryption` and
`kernel_integrity_protection`. **If this machine reports either as absent, say
so plainly and stop** — do not propose working around an admission requirement.
That is a decision for the owner, and it is exactly the requirement that
decides whether this node may hold VESPER's state.

Then measure throughput. **Do not copy a number from any document, including
this one.** `INV-HW-2`: measured at enrolment, never declared.

---

## Step 5 — report back

Write `docs/planning/spike-results/NODE1-ENROLMENT-<UTC timestamp>.json` and
state plainly:

- each step: verified / failed / skipped, **with the command output that shows
  it** — not your summary of it
- the Tailscale tailnet name and IPv4
- `llama-server` build string, read from `/props`
- the hibernate rehearsal: did the machine actually rise, and what
  `powercfg -lastwake` said
- the probe's raw facts, ungraded
- anything you could not verify

**A step you skipped is a fact, not a gap to smooth over.** The most useful
thing you can hand back is an accurate account of what is *not* done.

Do **not** write to `contracts/policy/capability_profiles.toml`. Promotion into
a contract is a separate reviewed act and there is deliberately no write path
to it from a probe.

---

## Things that will look like bugs and are not

- **Panels stay dark on a timer wake, so nothing is audible.** Known and
  recorded: five rehearsals, five silences. `ES_DISPLAY_REQUIRED` does not wake
  a sleeping panel. **This does not matter here** — VESPER needs compute from
  this machine, not sound. The alarm lives on node 2 for this reason. Do not
  try to fix it.
- **`CONSOLELOCK` does nothing on this machine.** Windows Hello is enabled and
  its policy wins; the legacy value is ignored, which is also why the setting is
  absent from Settings. Setting it to 0 changed nothing. Do not retry it.
- **Ping fails between the machines.** ICMP is blocked both ways here. TCP
  works. This is not a network fault.
- **CRLF.** Many files in this repo are CRLF. Python patch scripts silently
  rewrite them to LF. Check `file` before editing and `git diff --stat` before
  committing — a whitespace-only diff across a whole file means you converted it.
- **`python3` is not the right Python.** Gates need ≥3.11 for `tomllib`. On the
  MacBook that is `python3.13`; check what this machine has before running any
  gate, and check the *version*, not the exit code — `checks.py` has been
  observed exiting 0 while failing on the import.
