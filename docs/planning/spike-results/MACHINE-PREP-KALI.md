# Kali laptop — machine preparation log

**2026-08-14. Owner authorised cleanup and optimisation of this machine for VESPER**
(onboarding doc §3, and again in session: *"nothing on it is important, you can clean whatever
you want, as long as it doesn't destroy it"*). This file is the record the authorisation asked
for — *a number is not a record*, so what was removed is listed by name, not just totalled.

The authorisation's one limit was honoured throughout: **nothing was removed that could lock
the owner out of the machine or an account, and nothing was removed that could not be
identified.** No SSH/GPG keys, no `~/.ssh` or `~/.gnupg`, no credential or token store, no
cloud/CLI auth, no browser *profiles* (only their regenerable caches), no network/VPN config,
no Wi-Fi driver trees.

---

## 1. Keep-awake — the owner's explicit request

In session: *"if the laptop is risking going to sleep alone, try to not make it go to sleep,
because I won't be here to wake it back."* This is also the configuration the always-on
control-plane role needs, so it is both an answered request and a step toward the node's role.

On this machine **xfce4-power-manager owns every sleep/lid/blank event** — it holds a `block`
inhibitor on `handle-lid-switch`, `handle-power-key`, `handle-suspend-key`, so systemd-logind
does not act on the lid; xfce does. That means the fix is xfce settings (per-user, no sudo),
not `logind.conf` (which would need the owner's password). All of the following were set and
verified:

| Setting (xfconf `xfce4-power-manager`) | Value | Effect |
|---|---|---|
| `presentation-mode` | `true` | master "never blank, never sleep" |
| `dpms-enabled` | `false` | display power management off |
| `blank-on-ac` / `blank-on-battery` | `0` | no screen blank |
| `dpms-on-ac-*` / `dpms-on-battery-*` | `0` | no display power-off/standby |
| `inactivity-on-ac` / `inactivity-on-battery` | `0` | no idle auto-suspend |
| **`lid-action-on-ac` / `lid-action-on-battery`** | **`0` (do nothing)** | **closing the lid does not suspend** |
| `xfce4-screensaver` `/saver/*` idle activation | `false` | no idle screen blanking |

These persist across reboot (stored in `~/.config/xfce4/xfconf/`). The X-session screensaver
and DPMS were also disabled live (`xset s off`, `xset -dpms`) — verified: screensaver timeout
now `0`, `DPMS is Disabled`.

**Active backstop:** a detached `systemd-inhibit --what=sleep:idle:handle-lid-switch
--mode=block` lock is held (`WHO=VESPER`, verified in `systemd-inhibit --list`). This blocks
*any* suspend through logind for as long as it runs, independent of the xfce settings.

**The one honest gap:** making this bulletproof *across a reboot at the logind layer* would
need one line in `/etc/systemd/logind.conf` (`HandleLidSwitch=ignore`), which needs the
owner's sudo password and was not done. It is not required while xfce4-power-manager is the
running session's power daemon (it is), because xfce owns the events — but if the machine is
ever rebooted into a session without xfce, the logind default (`suspend` on lid) would return.
Recorded so it is a known condition, not a surprise.

---

## 2. Cleanup — what was removed, by name

Method: inventory first (`du` per directory), delete only the regenerable, measure reclaim
with `df` before/after.

| Removed | Size | Why it was safe |
|---|---|---|
| `~/.cache/pip` | 3.27 GB | pip's download cache; regenerated on demand |
| `~/.cache/opera` | 1.16 GB | browser **cache** (not the profile) |
| `~/.cache/mozilla` | 1.07 GB | browser **cache** (not the profile) |
| `~/.cache/ms-playwright-go` | 126 MB | Playwright browser-binary cache |
| `~/.cache/google-chrome` | 14 MB | browser cache |
| `~/.local/share/Trash/*` | 2.62 GB | already-discarded files (see below) |

**Total reclaimed: 8.26 GB** (df avail 69 468 MB → 77 730 MB on `/`).

The emptied trash was, by name, all discarded installers and archives — e.g. a 1.4 GB
`iPhone_14_Pro_Max_Clone_*.rar` firmware dump, `google-chrome`/`opera` `.deb`s, two
`expressvpn-*.run` installers, `apache-tomcat` tarballs, a couple of images/PDFs. All were in
the Trash, i.e. the owner had already thrown them away; emptying it only makes that permanent.

---

## 3. Deliberately NOT removed — needs an owner call

The authorisation says delete what you don't need; the limit says never delete what you can't
identify or what isn't yours to judge. These are **identified** but are the owner's tools,
projects, or documents, so they are listed for a decision rather than removed:

| Path | Size | What it is | Recommendation |
|---|---|---|---|
| `~/Desktop` | 1.9 GB | the owner's desktop files | leave — owner content |
| `~/eclipse` + `~/eclipse-workspace` | 1.6 GB | Eclipse IDE + its workspace | remove only if Java dev is done with |
| `~/mtkvenv` + `~/mtkclient` | 1.05 GB | MediaTek flashing tool + its venv | owner tool; leave unless retired |
| `~/Downloads` | 616 MB | downloads | owner should skim before any delete |
| `~/Projects` | 428 MB | the owner's projects | leave — owner content |
| **`~/rtw88`, `~/rtl8821ce`** | 261 MB | **Wi-Fi driver source trees** | **do not remove** — network-related; may be what makes Wi-Fi work |
| `~/Evil-Droid`, `~/FuzzyAI` | 151 MB | pentest / AI tooling | owner tools; leave unless retired |
| `~/apache-tomcat-11.0.18` | 21 MB | Tomcat server | leave unless retired |

Reclaimable with the owner's `sudo` but not attempted here (no passwordless sudo): the apt
archive cache (`sudo apt-get clean`, ~577 MB) and `sudo apt-get autoremove` (a few packages
including `firmware-marvell-prestera`, which is switch-ASIC firmware irrelevant to a laptop —
but firmware removal sits close to the network-config line, so it is left to the owner).

To run those yourself, in this session:

```
! sudo apt-get clean && sudo apt-get autoremove
```
</content>
