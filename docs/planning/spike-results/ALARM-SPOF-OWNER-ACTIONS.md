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
