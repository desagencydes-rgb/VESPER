#!/usr/bin/env python3.13
"""Regenerate `HomeChrome.fallbackTemplate()` from `chrome/home.html`.

WHY THIS EXISTS, AND WHY A COMMENT WOULD NOT HAVE DONE.

`fallbackTemplate()` is the markup the binary paints when the template file is
missing -- a layer covering the owner's whole Desktop cannot fail to "file not
found" by going transparent. Its own docstring said *"Byte-identical to the file
at the time it was extracted."*

It was not. Measured 2026-09-06: 514 lines against the file's 726, thirty
divergent hunks, including the rule that makes VESPER's text selectable at all.
The check that guards the pair compared only their SUBSTITUTION TOKENS, so five
hundred lines of drift sat under a green gate for weeks.

That is this corpus's oldest failure in its most ordinary form: a statement of
intent standing where a step was needed. The fix is not a more careful editor.
It is to stop maintaining the copy by hand -- the fallback is now GENERATED, the
file is the only source, and `CI-065`'s content assertion refuses a build where
the two disagree.

Run it after every edit to `home.html`. `tools/ci/checks.py chrome-template-renders`
fails and names this script if you forget.

Stdlib only, per the tree's convention.
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "app" / "home-macos" / "chrome" / "home.html"
SWIFT = REPO / "app" / "home-macos" / "HomeChrome.swift"

OPEN = "        return \"\"\"\n"
CLOSE = "\n        \"\"\"\n"
INDENT = " " * 8

# The one thing a Swift multiline literal reserves that CSS and JS both use.
# `\s` in a regex is not a Swift escape and does not compile; `\(` would open an
# interpolation and splice arbitrary Swift into the page. Escaping the backslash
# covers both, because after the substitution neither can occur.
#
# `"""` would close the literal early. It cannot be escaped into a multiline
# literal, so it is REFUSED rather than mangled -- silently emitting something
# that does not compile is the failure this whole script exists to remove.
FORBIDDEN = '"""'


def swift_literal(text: str) -> str:
    """The file's bytes as the body of a Swift multiline string literal."""
    if FORBIDDEN in text:
        raise SystemExit(
            f"{TEMPLATE.name} contains a triple quote, which would close the "
            f"Swift literal early. There is no escape for it inside a multiline "
            f"literal -- rewrite that markup instead.")
    escaped = text.replace("\\", "\\\\")
    lines = escaped.split("\n")
    # A trailing newline becomes a trailing empty element; the literal's own
    # closing delimiter supplies the final newline, so drop it rather than
    # emitting a line of bare indentation.
    if lines and lines[-1] == "":
        lines.pop()
    # An empty line stays EMPTY. Indenting it would put trailing whitespace into
    # the generated Swift, which every editor in this tree strips on save -- and
    # a file that changes when it is opened is a file that shows as dirty for
    # reasons nobody can explain.
    return "\n".join((INDENT + ln) if ln else "" for ln in lines)


def render() -> str:
    """The whole of HomeChrome.swift with the fallback body replaced."""
    swift = SWIFT.read_text(encoding="utf-8")
    start = swift.find("static func fallbackTemplate()")
    if start < 0:
        raise SystemExit("HomeChrome.swift has no fallbackTemplate()")
    end = swift.find("static func template()", start)
    if end < 0:
        raise SystemExit("HomeChrome.swift has no template() after the fallback")

    body_start = swift.find(OPEN, start, end)
    if body_start < 0:
        raise SystemExit(
            "fallbackTemplate() does not open with an eight-space-indented "
            "`return \"\"\"`. The splice is anchored on that exact line, and an "
            "anchor that no longer matches must FAIL rather than silently "
            "leave the fallback stale -- which is the bug this script fixes.")
    body_end = swift.find(CLOSE, body_start + len(OPEN), end)
    if body_end < 0:
        raise SystemExit("fallbackTemplate()'s literal is not closed as expected")

    lit = swift_literal(TEMPLATE.read_text(encoding="utf-8"))
    return (swift[:body_start + len(OPEN)] + lit
            + swift[body_end:])


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    new = render()
    old = SWIFT.read_text(encoding="utf-8")
    if new == old:
        print("fallback is in sync with home.html")
        return 0
    if check_only:
        print("STALE: HomeChrome.fallbackTemplate() does not match home.html.\n"
              "       Run: python3.13 tools/sync_chrome_fallback.py")
        return 1
    SWIFT.write_text(new, encoding="utf-8")
    print(f"fallback regenerated from {TEMPLATE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
