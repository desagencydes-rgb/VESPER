# Expandable menu — isolated worktree handback

## Scope and integration boundary

Worktree: `/Users/macbook/VESPER-codex-menus`, branch `codex/menus-v2`.
Baseline: `bfbee1a` (fast-forwarded from the preserved `66b5c8d`). This includes
the template substitution correction, mounted-surface readback, model-completion
rows, producer tags, and the brief's new §7. The primary checkout and running
app are not changed by this work. Claude Code owns review and integration.

## Changes

The existing 51 instruments now have six topic groups, name/description search,
and an availability filter. Every catalogue entry remains represented; filtering
never creates observations. A visible count and empty-result message describe
the current filter. Clear filters restores the entire list.

Rows retain their open state while measurements refresh. Tools have return
navigation, retaining the instruments' query, topic, availability selection,
expanded rows and scroll position. Raw observation details sit behind a separate
disclosure; exact catalogue descriptions, sources, observation times, limits and
unavailability reasons remain available. The seventeen approved icons and their
hover descriptions are preserved.

The menu receiver selects by catalogue identity AND producer area, before its
bounded slice. It forwards the original payload to the HOST receiver in a
`finally` block. A menu rendering exception therefore cannot skip that receiver;
a missing HOST receiver now throws a named error. The menu no longer deletes
HOST DOM nodes by label or filters the HOST payload by menu-name membership.

`HomeChrome.reportStage` now reads a bounded `menu=` record from its existing
mounted WKWebView. It includes current filters, row count, matched and visible
IDs, expanded IDs, missing reasons, scroll and viewport fit. This is part of the
app's real readback, not a second page, synthetic push or substituted template.
The fallback was regenerated using `tools/sync_chrome_fallback.py`.

## Development validation

- `tools/ci/checks.py all`: 143/143 in the final serial run (exit 0).
- `tools/ci/self_test.py chrome-template-renders`: 15/15 executed red/green cases.
- `verification/test_menu_projection.py`: 13/13 unit tests.
- `node verification/test_menu_receiver.js`: production receiver transport passes;
  three syntactically valid faults produce assertion failures (discarded HOST
  payload, ignored producer tag, HOST delivery skipped on menu failure).
- Traceability and reference lints pass; `git diff --check` is clean.
- Inline JavaScript, mounted-readback JavaScript and Swift syntax parse.
- Topic coverage: all 51 catalogue instruments, exactly once.

These checks are not evidence that the running surface renders correctly. The
receiver test has no DOM; it verifies delivery and filtering only. The full
mutation suite was interrupted during the unrelated sensor check and restored
its mutations; only the completed 15-case chrome run is claimed here. The final
full check pass ran after mutation testing had stopped. Local full output is
`/tmp/vesper-menu-checks-final.log`; chrome mutation output is
`/tmp/vesper-menu-chrome-self-tests.log`.

## Live acceptance — owed at integration

NOT RUN. The existing primary app owns the single-home marker. Starting another
home requests that existing home to move; starting a runtime can kill the current
runtime. Neither is an isolated preview. The copied worktree binary predates the
corrected readback. No app rebuild, re-sign, restart, fixture DOM, live state
injection, local model call, or destructive action was used for this handback.

The new native diagnostic needs to be included in Claude Code's authorized
integration/build. Preserve any newer HOST `metrics=` readback alongside `menu=`
when merging. Regenerate the fallback after resolving template conflicts; do not
hand-merge its generated HTML.

Before declaring acceptance, use the app's actual mounted surface and capture
successive `chrome: READBACK` records while performing these gestures:

1. Open Host instruments. With filters cleared, expect 51 rows and 51 matched
   IDs, nonempty absence reasons, `open:true`, and `fits:true`. `visible` is the
   subset intersecting the panel viewport, not a claim that 51 rows fit at once.
2. Search `battery`; choose a topic and each availability filter. Check the
   rendered results/count and absence reasons against the actual rows. Clear
   filters and verify all 51 return. Verify a no-match query shows its message.
3. Expand a real reading and its observation details. Observe multiple producer
   pushes: the reading updates, while focus, filters and expanded state remain.
4. Open Before / after or another local tool and use Back. Confirm filters,
   expanded instruments and scroll position return. Close with Escape and confirm
   focus returns to the original menu trigger.
5. Confirm all 17 main destinations still open with exact hover descriptions.
6. Across those gestures, require all five `recv` entries to be `fn`,
   `jsErrors=none`, and existing stack/history/HOST contents to remain correct for
   the live state. `push OK` alone is not evidence. The HOST card must show only
   its five tagged rows, including explicit absences.
7. Observe the expiry of a real reading if its producer stops. It must become
   unavailable with a reason, including while the panel remains open. Do not
   manufacture a fresh timestamp or overwrite the owner's state to force a pass.

The previous `verification/probe_menus.py` and `MENUS-v2-EVIDENCE.json` do not
satisfy this acceptance gate. They reconstruct a fixture page. Historical green
results from them must not be carried forward as live evidence for this change.
