"""Numbered credentials expand a declared row into as many rungs as exist.

THE ALTERNATIVE WAS A TOML EDIT PER KEY. `contracts/policy/provider_supply.toml`
already has the shape for "one row per account" -- `groq-chooser`,
`groq-updater`, `groq-investigator` are the same provider under different
names for exactly that reason. It works, and it means every new free account
is a commit. The owner's stated intent is "same limit, add another" as an
ongoing operational habit, not a one-time provisioning decision, so the numbers
below turn that habit into an env-var convention instead of a code change:
`ELEVENLABS_API_KEY_2`, `_3`, `_4`... Adding a key means adding a line to
`secrets.env`. Nothing here needs to be told it exists.

A GAP DOES NOT STOP THE SCAN. `_2` present, `_3` absent, `_4` present is a real
state -- a key rotated out and back in, or removed while its neighbours were
not touched -- and stopping at the first gap would silently drop `_4`. The
bound exists only so a typo'd env-var scheme cannot make this scan unbounded;
it is not a claim that 20 accounts is expected.
"""

from __future__ import annotations

from typing import Callable

MAX_RUNGS = 20


def numbered_credential_envs(
    base: str, present: Callable[[str], bool], *, max_rungs: int = MAX_RUNGS,
) -> list[str]:
    """Env-var names for `base`'s rungs, in the order they will be tried.

    `base` itself is rung one if present. `f"{base}_2"`, `f"{base}_3"`, ...
    follow, each independently checked -- so a numbered variant with no
    credential is simply not a rung, the same rule `speech_rows` and
    `transcribe_rows` already apply to the unnumbered case.
    """
    out = [base] if present(base) else []
    out += [name for i in range(2, max_rungs + 1)
            if present(name := f"{base}_{i}")]
    return out


def expand_rows(rows: list, *, present: Callable[[str], bool],
                 max_rungs: int = MAX_RUNGS) -> list:
    """One declared row becomes one row per rung its credential has.

    SIBLINGS SHARE EVERY POLICY FIELD. Two accounts of the same provider are
    the same egress class, the same model, the same Arabic capability -- they
    differ only in which credential answers, so the expansion copies the row
    and swaps `credential_env` and `id`, and touches nothing a caller reads to
    decide WHETHER a row may be used, only WHICH ONE.

    ORDER IS PRESERVED WITHIN A `rung`, ACROSS ROWS. The final list is sorted
    by `(rung, position)`, so a declared `rung = 2` row (a different provider,
    used only when the whole first family is exhausted) still sorts after
    every numbered sibling of a `rung = 1` row, and siblings of the same row
    keep the order `numbered_credential_envs` found them in.
    """
    out = []
    for row in rows:
        base_env = row.get("credential_env", "")
        if not base_env:
            out.append(row)
            continue
        envs = numbered_credential_envs(base_env, present, max_rungs=max_rungs)
        if not envs:
            continue
        for i, env in enumerate(envs):
            if i == 0:
                out.append(row)
                continue
            sib = dict(row)
            sib["credential_env"] = env
            sib["id"] = f"{row.get('id')}#{i + 1}"
            out.append(sib)
    return [row for _, row in sorted(
        enumerate(out), key=lambda pair: (pair[1].get("rung", 1), pair[0]))]
