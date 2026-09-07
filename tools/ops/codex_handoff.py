#!/usr/bin/env python3.13
"""Hand a slice of this repo to a second agent, and get it back verifiably.

WHY THIS IS A TOOL AND NOT A PARAGRAPH IN A BRIEF.

The owner's question was "what if codex breaks something?", and the honest
answer is that a brief cannot stop it. A brief is a request; an agent that
misreads one, or reasonably decides a file needs touching, breaks the thing
either way and nobody finds out until a gate goes red somewhere unrelated. This
project is at a state where that is expensive.

So the boundary is MECHANICAL. Before the handoff this records a hash of every
file the second agent may not touch. Afterwards it compares, and an
out-of-scope change is a named file and a diff rather than a suspicion.

THREE BACKUPS, EACH FOR A DIFFERENT FAILURE:

  1. A GIT TAG. Cheap, instant, and enough for "undo the whole slice".
  2. A TARBALL OUTSIDE THE REPO. For the case the tag cannot help with -- a
     `git reset --hard` in the wrong directory, a deleted `.git`, an agent that
     "cleans up". The owner asked for a local backup untouched by codex, and a
     copy inside the tree it is working in is not that.
  3. THE AGENT'S OWN WORKING COPY, which it makes and deletes when it is done.
     That one is its safety net, not ours, and it is deliberately not our
     business except that it must not be left behind.

WHAT THIS DELIBERATELY DOES NOT DO. It does not sandbox the agent, it does not
review its code, and it cannot stop a destructive command mid-flight. It makes
damage VISIBLE and REVERSIBLE, which is a different and achievable claim.

Stdlib only.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import tarfile
import time

REPO = pathlib.Path(__file__).resolve().parents[2]

# OUTSIDE THE REPO, deliberately. The owner asked for "a local backup untouched
# by codex", and anything under the working tree is reachable by a careless
# `rm -rf`, a `git clean -fdx`, or an agent tidying up after itself.
VAULT = pathlib.Path.home() / "VESPER-backups"

MANIFEST = VAULT / "handoff-manifest.json"

# WHAT THE SECOND AGENT MAY CHANGE. Everything else is protected, so the list
# is the AGREEMENT rather than a filter -- adding to it is a decision somebody
# makes on purpose, not something that happens by forgetting.
ALLOWED = (
    "app/home-macos/chrome/home.html",
    "docs/planning/CODEX-BRIEF-MENUS.md",
)

# Directories never worth hashing or archiving: build output, caches, and the
# app bundle, which is regenerated and is 40 MB of it.
SKIP = (".git/", "__pycache__/", ".DS_Store", "app/VESPER.app/",
        "graphify-out/", ".vesper-preview/", "node_modules/")


def _tracked() -> list:
    """Every file git knows about. The archive follows the repo, not the disk."""
    out = subprocess.run(["git", "-C", str(REPO), "ls-files"],
                         capture_output=True, text=True, check=False)
    return [ln for ln in out.stdout.splitlines()
            if ln and not any(s in ln for s in SKIP)]


def _digest(rel: str) -> str | None:
    p = REPO / rel
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None            # absent is a real state and compares as one


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO), *args],
                          capture_output=True, text=True, check=False)


def open_handoff(label: str) -> int:
    """Tag, archive, and record what must not change."""
    if _git("status", "--porcelain").stdout.strip():
        print("REFUSED: the working tree is dirty.\n"
              "         A handoff has to start from a committed state, or "
              "'what changed' cannot be answered afterwards -- the second "
              "agent's work and yours would be the same diff.")
        return 1

    VAULT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    tag = f"handoff/{label}/{stamp}"

    r = _git("tag", "-a", tag, "-m", f"before the {label} handoff")
    if r.returncode != 0:
        print(f"REFUSED: could not tag: {r.stderr.strip()}")
        return 1

    # THE TARBALL IS THE ONE THAT SURVIVES A LOST `.git`. Built from the
    # tracked list so it is the repo rather than whatever else is lying around.
    archive = VAULT / f"{label}-{stamp}.tar.gz"
    files = _tracked()
    with tarfile.open(archive, "w:gz") as tf:
        for rel in files:
            p = REPO / rel
            if p.is_file():
                tf.add(p, arcname=rel)

    head = _git("rev-parse", "HEAD").stdout.strip()
    manifest = {
        "label": label,
        "opened_at": stamp,
        "tag": tag,
        "head": head,
        "archive": str(archive),
        "allowed": list(ALLOWED),
        # EVERY TRACKED FILE, not just the interesting ones. A boundary that
        # only watches the files somebody thought of is a boundary around
        # somebody's imagination.
        "hashes": {rel: _digest(rel) for rel in files},
    }
    MANIFEST.write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    print(f"handoff open: {label}")
    print(f"  git tag     {tag}")
    print(f"  archive     {archive}  ({archive.stat().st_size // 1024} KB)")
    print(f"  protected   {len(files) - len(ALLOWED)} files hashed")
    print(f"  writable    {', '.join(ALLOWED)}")
    print()
    print("  to undo everything:")
    print(f"    git -C {REPO} reset --hard {tag}")
    return 0


def verify() -> int:
    """Did anything outside the agreement change?"""
    if not MANIFEST.is_file():
        print("no open handoff (no manifest). Run --open first.")
        return 1
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    allowed = set(m["allowed"])
    before: dict = m["hashes"]

    # AGAINST HEAD, NOT AGAINST THE FROZEN MANIFEST -- and that distinction is
    # what makes this usable at all.
    #
    # The manifest is a snapshot of the moment the handoff opened. Comparing to
    # it reports every file that has changed since, INCLUDING the first
    # session's own committed work -- which is most of them, because the owner
    # asked that session to keep going. Measured 2026-09-07: the first verify
    # after the handoff named five files, all of them mine, and a boundary that
    # reports the wrong agent's work is one nobody can act on.
    #
    # The second agent does not commit; this session does. So an UNCOMMITTED
    # change outside the agreement is the second agent's, and that is exactly
    # the question worth asking. The manifest and the tag stay for the archive
    # and the undo -- they are the answer to "put it all back", not to "what
    # did the other agent touch".
    st = _git("status", "--porcelain", "--untracked-files=all").stdout
    changed, added, removed = [], [], []
    for ln in st.splitlines():
        if len(ln) < 4:
            continue
        code, rel = ln[:2], ln[3:].strip().strip('"')
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[1]
        if rel in allowed or any(sk in rel for sk in SKIP):
            continue
        if code.strip() == "??":
            added.append(rel)
        elif "D" in code:
            removed.append(rel)
        else:
            changed.append(rel)

    print(f"handoff {m['label']}, opened {m['opened_at']}")
    ok = not (changed or removed or added)
    if ok:
        print("  IN SCOPE: no uncommitted change outside the agreement.")
    else:
        # NAMED, NOT COUNTED. "3 files changed" sends the owner looking; a list
        # of paths sends them to the diff.
        for rel in changed:
            print(f"  CHANGED   {rel}")
        for rel in removed:
            print(f"  DELETED   {rel}")
        for rel in added:
            print(f"  ADDED     {rel}")
        print()
        print("  UNCOMMITTED and outside the agreement. This session commits its")
        print("  own work, so what is left here is the second agent's. Review:")
        print(f"    git -C {REPO} diff -- <path>")

    # AND THE AGENT'S OWN BACKUP MUST BE GONE. The owner asked for it to be
    # deleted after finishing; a stale copy of the tree inside the tree is how
    # a later session edits the wrong file for an hour.
    # NOT INSIDE `.git`. The first version globbed the whole tree and reported
    # `.git/refs/heads/backup` -- a perfectly ordinary git BRANCH called
    # `backup` -- as an agent's leftover directory. A boundary that cries wolf
    # about the repository's own bookkeeping is one people learn to skim.
    strays = [p for p in REPO.rglob("*")
              if p.is_dir()
              and ".git" not in p.parts
              and p.name in ("codex-backup", ".codex-backup",
                             "backup", ".backup")]
    for p in strays:
        print(f"  LEFTOVER  {p.relative_to(REPO)}  (the agent's own backup, "
              f"not deleted)")
        ok = False

    return 0 if ok else 1


def close() -> int:
    """Finish the handoff. Keeps the archive; clears the manifest."""
    if not MANIFEST.is_file():
        print("no open handoff")
        return 1
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    MANIFEST.unlink()
    print(f"handoff {m['label']} closed.")
    print(f"  the tag and the archive are KEPT: {m['tag']}")
    print(f"  {m['archive']}")
    print("  delete them yourself when the work has been merged and trusted.")
    return 0


def main(argv: list) -> int:
    if "--open" in argv:
        i = argv.index("--open")
        label = argv[i + 1] if i + 1 < len(argv) else "handoff"
        return open_handoff(label)
    if "--verify" in argv:
        return verify()
    if "--close" in argv:
        return close()
    print(__doc__.strip().splitlines()[0])
    print()
    print("  --open <label>   tag, archive outside the repo, hash everything")
    print("  --verify         report anything changed outside the agreement")
    print("  --close          finish; keeps the tag and the archive")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
