"""Provider adapters: the only place in the tree that speaks to a model.

INV-HW-1 SCANS THIS DIRECTORY (CI-007) and the rule is not "avoid a word list".
It is: write the profile, never the device. A module here is named for the
INTERFACE it speaks -- an HTTP completion endpoint -- and never for the runner,
the vendor or the machine on the other end. Which runner answers, at which
build, on which node, is DATA supplied at construction and recorded in the
call's evidence. Substituting the hardware is then a profile change rather than
an edit to this package, which is the whole property INV-HW-1 buys.

Nothing here decides WHICH profile to use. `core/router.py` decides that and
`core/gateway.py` enforces it at the cost choke point; an adapter is handed a
profile and serves it or fails. An adapter that chose for itself would be the
second path to the model that INV-COST-3 exists to prevent.
"""
