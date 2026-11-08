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

**Reboot-proof layer — now closed** (see §4). Initially this needed the owner's sudo and was
left open, meaning a reboot into a session without xfce would have restored the logind default
(`suspend` on lid). The owner then supplied the password and a logind drop-in
(`HandleLidSwitch=ignore`) was installed, verified live over D-Bus. So there are now three
independent layers: the live `systemd-inhibit` lock, the xfce settings, and logind itself.

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

## 2b. Second cleanup round — owner-selected, 2026-08-14

After the first round the owner asked to remove more apps/tools/files and chose from a
presented list. Removed (home dirs + the one apt package), with the owner keeping Code-OSS and
their active `.pyenv` Python:

| Removed | Size | What it was |
|---|---|---|
| `~/eclipse` + `~/eclipse-workspace` + `~/.eclipse` | ~1.57 GB | Eclipse IDE, dormant since Feb 2026 |
| `antigravity` (apt) + `~/.antigravity` + `~/.config/Antigravity` | ~1.66 GB | Google AI IDE + data, dormant since Dec 2025 |
| `~/mtkvenv` + `~/mtkclient` | ~1.05 GB | MediaTek flashing tool + venv (mtkclient held root-owned `.pyc` from past sudo runs; cleared with sudo) |
| `~/Evil-Droid` + `~/FuzzyAI` | ~151 MB | Android pentest builder + AI fuzzing tool |
| `~/.ollama` | ~941 MB | Ollama models (qwen2.5-coder) — VESPER uses llama.cpp, not Ollama; re-pullable |
| `~/.insightface` | ~881 MB | face-recognition model cache; auto-redownloads if needed |
| `~/.npm`, `~/tmp_pip_build`, thumbnail cache | ~108 MB | regenerable caches |
| `linux-image-6.12.38+kali-amd64` (apt) | ~107 MB | superseded kernel (running kernel is 6.16.8) |

**Kept at owner's choice:** Code-OSS (2.5 GB, still used) and `~/.pyenv` (5.8 GB) — the latter
is the machine's **active** Python interpreter with the owner's AI libraries; deleting it would
break their Python projects.

**Session total reclaimed: ~14 GB** (`/` availability 68 GB → 82 GB). System verified intact
afterward: Python works, Code-OSS present, network connected, internet reachable, VESPER gates
11/11, keep-awake inhibitor still active.

## 3. Deliberately NOT removed — needs an owner call

The authorisation says delete what you don't need; the limit says never delete what you can't
identify or what isn't yours to judge. What still remains after both rounds, and why it was
left:

| Path | Size | What it is | Why left |
|---|---|---|---|
| `~/Desktop` | 1.9 GB | the owner's desktop files | owner content — not mine to judge |
| `~/vesper-runtime` | 1.1 GB | llama.cpp binary + Qwen3-1.7B model | created this session; kept for later spikes |
| `~/Downloads` | 616 MB | downloads | owner content — skim before deleting |
| `~/Projects` | 428 MB | the owner's projects | owner content |
| **`~/rtw88`, `~/rtl8821ce`** | 261 MB | **Wi-Fi driver source trees** | **network-related — do not remove**; may be what makes Wi-Fi work |
| `~/.pyenv` | 5.8 GB | the **active** Python + AI libraries | owner kept it; removing breaks Python projects |
| Code-OSS | 2.5 GB | VS Code (OSS) | owner kept it |
| `/opt/expressvpn` | 236 MB | ExpressVPN app | VPN — left per the standing prohibition unless owner says otherwise |
| `~/apache-tomcat-11.0.18` | 21 MB | Tomcat server | tiny; owner tool, left unless retired |

## 4. Root tasks completed (owner supplied sudo password in-session)

- `apt-get clean` + `apt-get autoremove` — removed `cpp-14`, `firmware-marvell-prestera`,
  `libgpgmepp6t64`, `libsimdutf27`, and the superseded kernel `linux-image-6.12.38`.
- **Lid-close suspend disabled at the logind layer, across reboot:**
  `/etc/systemd/logind.conf.d/10-vesper-nosleep.conf` sets `HandleLidSwitch=ignore` (+ external
  power/docked). Verified live over D-Bus (`HandleLidSwitch = "ignore"`). This is the
  reboot-proof layer the §1 note said was still open; it is now closed.
- **Timezone corrected** from `America/New_York` to the local timezone (+01), the machine's
  actual location. (Was flagged as a caveat in the findings; now fixed.)

**Security note for the owner:** the sudo password was supplied in the chat session, so it is
in the transcript. Rotating it (`passwd`) is recommended, more so because this machine is being
promoted to an always-on node.

## 5. Encrypted vault (TPM-unlocked), 2026-08-14

The owner chose a **TPM-unlocked encrypted vault** over full-disk encryption: full-disk cannot
be done without booting from a USB stick with a person present, and the owner needed a
hands-off, walk-away result. The vault gives the realistic protection — **a stolen/removed SSD
is unreadable** — with zero interaction.

**What was built.** A 2 GB LUKS2 container at `/var/lib/vesper/vault.img` (sparse — 82 MB
actually on disk until filled), auto-mounted at **`/vault`**, owned by `csf` and writable
without sudo. Installed for it: `cryptsetup`, `systemd-cryptsetup`, `tpm2-tools`.

**How it unlocks.** Sealed to the on-board **TPM 2.0**, *presence-only* (no PCR binding) so it
keeps working across kernel and firmware updates rather than locking out on them. `/etc/crypttab`
+ `/etc/fstab` (both `nofail`) mount it automatically on **every boot with nothing to type** —
so "power off, power on" just works, which is what the owner asked for. `nofail` means that even
if the vault ever failed to open, the machine still boots normally; it simply would not have
`/vault` mounted.

**Safety of the build.** The container was formatted with a temporary key held only in RAM
(`/dev/shm`, never written to disk). The TPM was enrolled, and then — before removing anything —
the volume was **closed and re-opened using only the TPM, headless (no passphrase fallback)**;
that test PASSED. Only then was the temporary passphrase keyslot removed. The final volume has
**one keyslot: the TPM** (`cryptsetup luksDump` shows a single `systemd-tpm2` token, no
passphrase slot), and the temp key was wiped from RAM.

**The one honest limitation.** There is deliberately **no passphrase or recovery key** — that
was the point (nothing to leak on the unencrypted disk, nothing for the owner to store or lose).
The consequence: the vault is bound to *this* TPM. If the TPM is ever cleared, or the mainboard
replaced, the vault becomes unrecoverable and is simply recreated — acceptable because it holds
only re-enrollable VESPER secrets, per the owner's "nothing that important" call. It protects
against **disk theft**, not against a thief who powers on the whole running laptop (the vault
auto-mounts at boot); defending that case is what full-disk encryption is for, and remains the
later, in-person upgrade path.

**Verified without a reboot.** The auto-unlock could not be tested by an actual reboot (the
owner was leaving and did not want one), but the exact TPM-unseal path that boot uses was
exercised directly (step 5 above) and passed. The first real boot is the final confirmation;
`nofail` guarantees it is harmless if anything is off.
</content>
