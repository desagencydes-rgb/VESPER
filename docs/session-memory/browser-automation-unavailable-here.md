---
name: browser-automation-unavailable-here
description: claude-in-chrome tools fail on this machine ("Grouping is not supported by tabs in this window") — verify web instruments with a Node DOM stub instead
metadata:
  type: reference
---

The `mcp__claude-in-chrome__*` tools fail on node 1 with **"Failed to query
tabs: Grouping is not supported by tabs in this window."** Both
`tabs_context_mcp` and standalone `navigate` fail. Retrying does not help.

**Why it matters:** VESPER's field instruments are web pages run on the owner's
devices (`tools/spike/spike004_ghost.html`, `tools/spike/camera_audit.html`),
and [[verify-instruments-before-asking-the-owner]] requires driving them
end-to-end first. Without a browser, that has to happen another way.

**How to apply:** extract the page's `<script>` and execute it under a Node DOM
stub — `tools/spike/camera_audit_domstub.js` is a working example. It catches
what actually kills these pages: an exception on the load path. Two harness bugs
to expect, both already hit — a stubbed `setTimeout` that never fires, and
Node's read-only `navigator`, which silently ignores plain assignment and will
"prove" the page lacks `getUserMedia`. Use `Object.defineProperty` for
`navigator`, and keep the real `setTimeout`.
