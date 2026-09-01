"""A shadow history of everything VESPER touches, so any change can be undone.

WHY A SEPARATE REPOSITORY AND NOT THE OWNER'S. Aider commits every AI edit into
the project's own git history and its `/undo` refuses to touch a commit a human
made. That works for a coding tool whose whole workspace is one repository. It
is wrong here: VESPER writes to documents, notes and its own workspace, most of
which are not in any repository, and the ones that are belong to the owner. A
shadow repository records what VESPER did without ever writing to a history
somebody else is keeping -- Cline's shape rather than Aider's, and for the same
reason.

WHY IT LIVES BESIDE STATE AND NOT BESIDE CODE. `build.sh` deletes the runtime
directory inside `VESPER.app` on every build. A note written there was created,
hash-verified and reported successful, and the next build removed it -- the
failure was invisible to every instrument pointed at it, because the thing that
destroyed the file was the build and not the runtime. A checkpoint store under
the app bundle would have exactly that property, and would lose the history at
the moment a rebuild made it most useful.

WHAT IS RECORDED IS THE PRE-STATE. The snapshot is taken BEFORE the action, so
what the shadow holds is the world as it was when the decision was made. A
snapshot taken afterwards records the consequence and can restore nothing.

FAIL CLOSED. A capability that declares it needs a checkpoint does not run when
one cannot be taken. The alternative is writing over the owner's data with the
undo quietly unavailable, which is the one moment the undo exists for.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
from typing import Any


class CheckpointUnavailable(Exception):
    """No snapshot could be taken, so the action does not happen."""


class ShadowGit:
    """A git repository that mirrors, by absolute path, what VESPER touches."""

    def __init__(self, root: Any) -> None:
        self.root = pathlib.Path(root)
        self.tree = self.root / "tree"
        self._ready = False

    # ------------------------------------------------------------- plumbing

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(self.root), *args],
                              capture_output=True, text=True, check=False,
                              timeout=30)

    def ensure(self) -> None:
        """Create the shadow repository if it is not there. Idempotent."""
        if self._ready:
            return
        try:
            self.tree.mkdir(parents=True, exist_ok=True)
            if not (self.root / ".git").exists():
                r = self._git("init", "-q")
                if r.returncode != 0:
                    raise CheckpointUnavailable(
                        f"could not create the shadow repository: {r.stderr.strip()}")
                # LOCAL IDENTITY, so the shadow never depends on the owner's
                # global git config being set -- and never signs anything as
                # them. A commit here is VESPER's record, not their authorship.
                self._git("config", "user.name", "VESPER shadow")
                self._git("config", "user.email", "shadow@vesper.local")
                self._git("config", "commit.gpgsign", "false")
        except CheckpointUnavailable:
            raise
        except Exception as exc:                       # noqa: BLE001
            raise CheckpointUnavailable(
                f"the shadow repository is unusable: {exc!r}") from exc
        self._ready = True

    def _mirror_of(self, path: pathlib.Path) -> pathlib.Path:
        """`/Users/x/doc.txt` -> `<tree>/Users/x/doc.txt`.

        The leading separator is dropped rather than resolved away, so two
        files with the same name in different directories cannot collide -- a
        flat store keyed on the basename is the obvious shortcut and it loses
        exactly the case an undo is needed for.
        """
        p = pathlib.Path(path).resolve()
        return self.tree / str(p).lstrip("/")

    # -------------------------------------------------------------- record

    def checkpoint(self, paths: list, label: str) -> str:
        """Snapshot the CURRENT state of these paths and return the commit id.

        A path that does not exist yet is recorded as absent, by removing any
        mirror of it, so restoring a checkpoint taken before a file was created
        deletes it again rather than leaving the creation in place.
        """
        self.ensure()
        for raw in paths:
            src = pathlib.Path(raw)
            dst = self._mirror_of(src)
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if src.is_file():
                    shutil.copy2(src, dst)
                elif dst.exists():
                    dst.unlink()
            except Exception as exc:                   # noqa: BLE001
                raise CheckpointUnavailable(
                    f"could not snapshot {src}: {exc!r}") from exc

        self._git("add", "-A")
        r = self._git("commit", "-q", "--allow-empty", "-m", label[:500])
        if r.returncode != 0:
            raise CheckpointUnavailable(
                f"the shadow commit failed: {r.stderr.strip() or r.stdout.strip()}")
        head = self._git("rev-parse", "HEAD")
        if head.returncode != 0 or not head.stdout.strip():
            raise CheckpointUnavailable("the shadow repository has no HEAD")
        return head.stdout.strip()

    # ------------------------------------------------------------- restore

    def restore(self, commit: str, path: Any) -> dict:
        """Put one file back the way it was at `commit`.

        Returns what was done rather than raising on the absent case, because
        "there was no file then" is a real answer and restoring it means
        deleting what is there now.
        """
        self.ensure()
        target = pathlib.Path(path).resolve()
        rel = str(self._mirror_of(target).relative_to(self.root))
        show = self._git("show", f"{commit}:{rel}", check=False)
        if show.returncode != 0:
            if target.exists():
                target.unlink()
                return {"restored": "absent", "path": str(target)}
            return {"restored": "already_absent", "path": str(target)}
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(show.stdout, encoding="utf-8")
        return {"restored": "contents", "path": str(target),
                "bytes": len(show.stdout)}

    def history(self, limit: int = 20) -> list:
        """The most recent checkpoints, newest first."""
        self.ensure()
        r = self._git("log", f"-{int(limit)}", "--format=%H%x1f%s")
        if r.returncode != 0:
            return []
        out = []
        for line in r.stdout.splitlines():
            if "\x1f" in line:
                h, subject = line.split("\x1f", 1)
                out.append({"commit": h, "label": subject})
        return out
