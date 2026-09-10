"""Which applications VESPER may reach, and how far.

THE SECOND OF THE THREE GATES, for applications rather than windows.
`contracts/policy/host_actions.toml` says whether VESPER may perform an effect
AT ALL; this module says whether it may perform it on THIS target; the
capability ladder says how much approval that costs. `core/windows.py` is the
same split for windows and its header explains why they are separate: merging
them would put the owner's rule into a policy file that cannot see a target, or
put the vocabulary into a module the checks do not read.

INV-HW-1 IS EASY TO BREAK HERE AND IT IS BROKEN BY WRITING THE OBVIOUS THING.
The obvious implementation of "do not let VESPER drive a terminal" is a list of
bundle identifiers, and `core/windows.py` already refuses that shape in as many
words: *"An application's NAME may travel as an opaque label for the owner to
read; it may never be the thing a rule branches on. A rule that special-cases
one program is a rule the next node cannot honour."* CI-007's mechanical list
would not catch it -- it scans for HARDWARE names -- so this one is held by
doctrine rather than by a gate, which is exactly the kind that erodes. So the
rule below branches on a CLASS, and assigning a class to a bundle is somebody
else's job on a platform that knows what a bundle is.

WHY NO CLASSIFIER SHIPS WITH IT TODAY, SAID PLAINLY RATHER THAN LEFT TO BE
DISCOVERED. Every target is `UNCLASSIFIED` right now, and `UNCLASSIFIED` gets
reads and nothing else. That is not a placeholder that quietly permits things:
it is the fail-closed answer, and it costs nothing today because no
application-CHANGING row exists in the vocabulary yet to be refused. The
classifier is specified in §17 of the workbench and it is a MEASUREMENT, not a
list -- an application's scripting definition says whether it can be told to run
an arbitrary command, and that is a property to be read off the machine rather
than a name to be recognised.
"""

from __future__ import annotations

# WHAT A TARGET APPLICATION IS, AS FAR AS AUTHORITY GOES. Not what it does for
# the owner -- what driving it would let VESPER reach.
#
# `SHELL_HOST` and `AUTOMATION_HOST` are the two that matter and they are the
# reason this vocabulary exists at all. An application that can be told "run
# this command" or "click that element" is a way to perform an act VESPER is
# separately gated on: `shell.run` has containment, a level and a seatbelt
# profile, and §11.5's clicking has an Accessibility grant and a taint rule.
# Reaching either THROUGH an application arrives with none of that attached. A
# gate that can be walked around is not a gate, and this is the walk-around.
ORDINARY = "ordinary"
SHELL_HOST = "shell_host"
AUTOMATION_HOST = "automation_host"
CREDENTIAL_STORE = "credential_store"
VESPER_ITSELF = "vesper_itself"
UNCLASSIFIED = "unclassified"
CLASSES = (ORDINARY, SHELL_HOST, AUTOMATION_HOST, CREDENTIAL_STORE,
           VESPER_ITSELF, UNCLASSIFIED)

# The effects, abstract. `host_actions.toml`'s two application rows are both
# reads today; the changing verbs land with the grant trip and are refused here
# until they do.
READ = "read"
CHANGE = "change"
EFFECTS = (READ, CHANGE)

FREE = "free"
REFUSED = "refused"


class AppRuleViolation(Exception):
    """An effect or class was named that this module does not have.

    Raised rather than defaulted, for `core/host.py`'s reason: an effect that is
    not named is refused rather than approximated to the nearest one that is.
    """


def may_reach(target_class: str, effect: str, *,
              permission: str) -> tuple[bool, str]:
    """May VESPER perform `effect` on an application of `target_class`?

    `permission` is what the platform says about the automation grant, and it is
    an INPUT rather than something read here, so that the rule can be driven by
    a test on a machine with no grants and no window server at all.

    THE PERMISSION IS CHECKED FIRST AND THE ORDER IS THE POINT. Measured on this
    node 2026-09-10: an application VESPER has never been granted returns
    `errAEEventWouldRequireUserConsent`, and SENDING the event anyway is what
    puts a consent dialog on the owner's screen. During an autonomous run there
    is nobody there to answer it. So "not granted" is a refusal computed BEFORE
    an event exists, never a failure discovered after one was sent.
    """
    if effect not in EFFECTS:
        raise AppRuleViolation(
            f"{effect!r} is not one of {EFFECTS}. The set is closed: an effect "
            f"that is not named is refused rather than approximated.")
    if target_class not in CLASSES:
        raise AppRuleViolation(
            f"{target_class!r} is not one of {CLASSES}. An unrecognised class "
            f"is not silently treated as ordinary -- that is the direction that "
            f"grants authority by accident.")

    # VESPER DRIVING VESPER IS NOT AN APPLICATION ACTION, it is a
    # self-modification path with the vocabulary's name on it. INV-SELF-3 says
    # a boundary a sufficiently privileged grant can cross is one an injected
    # page will eventually talk its way past; reaching VESPER's own scripting
    # interface would cross it without asking any grant at all.
    if target_class == VESPER_ITSELF:
        return False, ("vesper does not drive itself through the application "
                       "vocabulary -- that is a self-modification path, and it "
                       "is governed where self-modification is governed")

    if permission != "granted":
        return False, ("vesper has not been granted control of that "
                       "application, and asking for it needs the owner at the "
                       "keyboard rather than a dialog raised mid-run")

    if effect == READ:
        # THE OWNER'S STANDING POLICY, and the reason reads need no per-class
        # rule: "VESPER reads freely and changes nothing on its own." The
        # per-application gate for a read is the Apple Events grant itself,
        # which the owner gives one application at a time and can revoke -- a
        # stronger and more legible allowlist than one this file could hold.
        return True, "vesper reads freely where the owner has granted it"

    # EVERY CHANGE IS REFUSED TODAY AND THE REASON IS NOT CAUTION. There is no
    # application-changing row in `host_actions.toml`, so there is nothing to
    # authorise: `action_provenance_required = "verified_local"` means a verb
    # lands once its effect has been driven against a real application on this
    # node, and that cannot happen before the grant trip. Returning False here
    # is the vocabulary's answer restated, not a second opinion about it.
    if target_class in (SHELL_HOST, AUTOMATION_HOST, CREDENTIAL_STORE):
        return False, ("driving that application would reach past a gate that "
                       "governs the same act directly, so it is refused here "
                       "rather than granted by the back door")
    return False, ("vesper has no verb that changes an application yet -- the "
                   "changing verbs land with the grant trip that measures them")
