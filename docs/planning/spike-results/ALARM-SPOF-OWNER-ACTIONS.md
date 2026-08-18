# The alarm's single point of failure — what is closed, what needs root

**Recorded 2026-08-18, after the watchdog was built and tested on node 2.**

The 09:00 alarm has been a detached process with no timer and no cron behind
it since it moved to node 2. This records exactly how much of that is now
covered, how much is not, and the three commands that close the rest.

## What the watchdog covers

`tools/ops/alarm_watchdog.py`, driven by a `systemd --user` timer every two
minutes, restores the primary if it is gone. It **never actuates** — there is
one firing path in the system at all times, which is what makes a double alarm
structurally impossible rather than merely unlikely.

Tested on node 2 on 2026-08-18, against the live 09:00 process and a fake
clock rather than at 09:00:

| Test | Result |
|---|---|
| No intent recorded | refuses, `no_intent` |
| Intent for a due that already completed | refuses, `already_completed` — keyed on the evidence file's own `due`, not its mtime |
| Intent for a due whose primary is alive | refuses, `primary_alive`, and correctly identified the real pid |
| Intent past due by more than 30 min | refuses, `intent_stale` |
| Intent for a due with **no** primary | **relaunches**, and the restored process was confirmed running, session-leader, reparented to init |
| Immediately re-checked after relaunching | refuses, `primary_alive` — no double launch |

**Covered: the primary crashing, being OOM-killed, being killed by accident, or
exiting early for any reason — while the user session is alive.**

## STATUS UPDATE — 2026-08-18 15:45, after the owner supplied root

Two of the three actions below are **done**, and one is deliberately not.

| Action | State | Evidence |
|---|---|---|
| `loginctl enable-linger csf` | **DONE** | `Linger=yes` read back |
| lightdm autologin | **NOT DONE — deliberately** | see below |
| mask the sleep targets | **NOT DONE — needs the owner's call** | it changes what the laptop does when the owner closes it |

**Autologin was not enabled, and the reason is not technical.** It removes the
laptop's login password: anyone who opens the lid gets a live session. That is
a security tradeoff about the owner's personal machine, and root access handed
over to close a reboot hole is not consent to make it. It is also very possibly
unnecessary — see the next paragraph.

**The audio path does not appear to need a graphical session.** Measured on
node 2 after lingering was enabled, from a `systemd-run --user` unit in its own
cgroup — the same shape a boot-time timer would have:

```
pactl info                 Server String: /run/user/1000/pulse/native   rc=0
pactl get-default-sink     alsa_output.pci-0000_00_1f.3.analog-stereo
pactl list sinks short     1 sink, analog-stereo, SUSPENDED
spd-say                    /usr/bin/spd-say
pipewire / pipewire-pulse / wireplumber      all `enabled` as user units
```

With `Linger=yes`, `systemd --user` starts at boot and those enabled units come
with it. So the expected post-reboot behaviour is: audio works, the watchdog
timer runs, and the alarm is restored — **with no autologin and no loss of the
login password.**

**That expectation is NOT verified, and the only thing that verifies it is a
reboot.** It was not run unattended: if node 2 came back without audio or
without networking while the owner was out, there would be no alarm and no way
to fix it remotely. It is a five-minute check with the owner present:

```sh
sudo reboot          # then, from node 1, once it answers on 22:
ssh csf@192.168.100.102 'systemctl --user is-active pipewire;   systemctl --user list-timers vesper-alarm-watchdog.timer --no-pager;   ps -eo pid,cmd | grep "[a]larm_night"'
```

All three must come back green. If audio is absent, autologin is the fix and
the tradeoff becomes worth making — but not before, and not without the owner
choosing it.

## CORRECTION — 2026-08-18 evening. Suspend does not fail gracefully; it hangs.

**Two things recorded earlier today were wrong, and the owner corrected both.**

A suspend/wake test was run at 16:23: the RTC register was set 3 minutes out,
read back correctly, and the machine was told to suspend. From node 1 it went
unreachable and stayed unreachable well past the wake time.

**What I wrote:** first that the RTC wake had failed, then — when the machine
answered again at 16:30 — that it had "come back on its own."

**What actually happened, per the owner at the keyboard:** the laptop *never
suspended*. The screen went black or dark grey and it **hung there**. It did not
enter S3, it did not power down, and it did not resume. The owner held the power
button to force it off, powered it back on, and logged in. The 16:30 recovery
was a **hard reset by a person**, not a wake by a machine.

Both of my readings were inferences from one bit of information — whether TCP/22
answered — and both were stated with more confidence than one bit can carry.
A host that is hung, a host that is suspended, and a host that is off are
indistinguishable from the other end of a network, and I twice treated the
absence of an answer as if it named a cause.

### What the test actually established

**Suspend on node 2 is broken in the worst available way.** Not "it sleeps and
cannot wake" — it *hangs on the way down* and needs a physical power cycle. The
RTC wake path is therefore untested rather than disproven: nothing ever got far
enough for the alarm to matter.

The earlier suspicion still stands as the likely reason a wake would not have
worked anyway: `/proc/acpi/wakeup` exposes **no RTC line** on this ASUS
VivoBook, so the firmware most likely does not offer RTC alarm as a wake source.
That remains **unconfirmed** and should not be repeated as fact.

### The owner's ruling on masking

**Declined, 2026-08-18.** The sleep targets stay unmasked and the laptop keeps
its ability to suspend.

That makes the guidance a matter of discipline rather than of structure:
**do not suspend node 2**, because suspending it hangs it, and a hung node 2 is
an alarm that does not ring and cannot be recovered remotely. Closing the lid is
fine — `HandleLidSwitch=ignore` is verified live. Leaving it idle is fine —
`IdleAction=ignore` is verified live. The only unsafe act is an explicit
suspend, and nothing in the system now performs one.

### What the hard reset bought for free

The reboot check this document asks for at §STATUS UPDATE **has now happened**,
under harsher conditions than a clean `sudo reboot`:

```
boot                     16:30:15
systemd --user started   16:30:27   (12 s after boot)
watchdog first fired     16:32:15   -> relaunch, verified_running true, pid 4554
pipewire/wireplumber/pipewire-pulse   active
alarm process            alive, guarding 2026-08-19 09:00
```

`systemd --user` started **12 seconds after boot and ~7 minutes before the
graphical login at 16:37**, which is the specific thing `Linger=yes` was set to
buy. The watchdog then noticed the missing primary and restored it without
anyone asking.

**So the reboot hole is closed and measured, and autologin is confirmed
unnecessary** — the laptop keeps its login password. The recovery path survived
a power-loss-class event, which is a stronger result than the planned test would
have produced.

## What is NOT covered, and why

**Reboot and power-off.** Measured on node 2, 2026-08-18:

```
loginctl show-user csf -p Linger        Linger=no
/etc/lightdm/lightdm.conf               autologin-user commented out
sudo -n true                            a password is required
```

With no lingering and no autologin, a reboot leaves the machine at a login
screen: no user session, no PipeWire, no `systemd --user` timer. The watchdog
is not running, and there is nothing for it to restore into even if it were.

**This is not a gap the watchdog can close from userspace.** All three fixes
need root.

## The three commands, and what each buys

Run on node 2 (`ssh csf@192.168.100.102`). Each is independent.

**1. Let user services run without a login — closes the timer half.**

```sh
sudo loginctl enable-linger csf
```

**2. Log the desktop session in automatically at boot — closes the audio half.**

```sh
sudo sed -i 's/^#autologin-user=.*/autologin-user=csf/; s/^#autologin-user-timeout=.*/autologin-user-timeout=0/' /etc/lightdm/lightdm.conf
sudo grep -n '^autologin' /etc/lightdm/lightdm.conf
```

The second line prints what it changed — if it prints nothing, the keys were
formatted differently and the edit did not take. **Do not assume it worked.**
`csf` must also be in the `autologin` group on some builds:
`sudo groupadd -f autologin && sudo gpasswd -a csf autologin`.

> Both are needed together. Lingering alone gives a timer with no audio session
> to sound through; autologin alone restores audio but the timer still waits for
> a graphical login that has already happened, which is fine — but lingering is
> what makes it survive a login screen the owner never reaches.

**3. Optional — let the machine wake itself from suspend.**

Only worth doing if the laptop will ever be suspended. As configured it is not
supposed to suspend at all: `HandleLidSwitch=ignore`, `IdleAction=ignore` and
xfce presentation mode all hold it awake, and all three were verified live.
But `sleep.target` is `static`, not masked, so a manual suspend still works and
**no RTC wake is armed** — a suspended laptop will not ring.

```sh
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

Masking is the honest fix: it makes the machine unable to do the thing that
breaks the alarm, rather than adding a wake path that must itself be verified.
Reversible with `systemctl unmask`.

## The bug this exposed

`tools/ops/alarm_night.py`'s `arm` subcommand — the one whose entire job is to
schedule a self-wake — is **Windows-only**. It shells out to PowerShell and
calls `Register-ScheduledTask ... -WakeToRun`. Node 2 has neither `powershell`
nor `pwsh`.

So on the machine the alarm actually lives on, `arm` cannot run at all, and the
only usable path is `fire` launched detached — which is exactly the single
point of failure. The Linux driver's header states *"THIS NODE NEEDS NO WAKE
STEP … there is no rtcwake, no wake timer"*, and that is true **only while the
three stay-awake layers hold**. It is a design premise, not a guarantee, and
nothing was checking it.

Recommendation: either mask the sleep targets (option 3, which makes the
premise true by construction) or give `arm` a Linux branch. Masking is cheaper
and has no failure mode of its own.

## Until then

**Leave node 2 powered on and do not suspend it.** Closing the lid is fine;
leaving it idle is fine. Powering it off or suspending it is the one thing
that silently removes the alarm.
