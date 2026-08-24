#!/usr/bin/env python3
"""A JSON Schema subset validator, stdlib only.

WHY THIS EXISTS. `contracts/entities/` has carried schemas since F0 and nothing
in this tree has ever validated an INSTANCE against one. `tools/ci/checks.py`
inspects schema DOCUMENTS -- it asserts that `cost_class` is in a `required`
list, that `additionalProperties` is false -- which checks that the rule was
written, never that anything obeys it.

`node_capability_profile.schema.json` is the case that made this necessary. Its
`allOf` block encodes three real constraints: INV-TRUST-1 (a Z2 node may render
and observe only), that a control plane cannot live on a node that is not
reliably awake, and INV-HW-2 (a measured profile carries its measurement time).
Written 2026-08-20, never instantiated, never enforced. A schema whose
constraints are never applied is documentation wearing enforcement's clothes.

SCOPE, STATED SO NOBODY MISTAKES IT FOR A FULL IMPLEMENTATION. This handles the
subset the entity schemas in this repo actually use: `type` (including union
types), `enum`, `const`, `required`, `properties`, `additionalProperties`,
`items`, `minItems`, `minimum`, `maximum`, `contains`, and `allOf` with
`if`/`then`. It does NOT implement `$ref`, `oneOf`, `anyOf`, `not`,
`patternProperties`, `dependentSchemas` or `format` assertions.

AN UNKNOWN KEYWORD IS A FAILURE, NOT A SHRUG. `validate` refuses a schema
containing a keyword it does not implement, rather than ignoring it and
returning "valid". Silently skipping `oneOf` would report a pass on a document
whose central constraint was never read -- which is the vacuity defect this
repo has been bitten by twice, in `CI-007`'s scope list and in `A-022`'s graded
corpus. If a schema here grows a keyword, this file grows with it or the gate
goes red.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Keywords that carry no assertion and are safe to pass over.
_ANNOTATIONS = {"$schema", "$id", "title", "description", "$comment",
                "examples", "default", "format", "deprecated", "readOnly"}

_SUPPORTED = {"type", "enum", "const", "required", "properties",
              "additionalProperties", "items", "minItems", "maxItems",
              "minimum", "maximum", "contains", "allOf", "if", "then", "else",
              "propertyNames"}

_TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool,
    "number": (int, float), "integer": int, "null": type(None),
}


class SchemaUnsupported(Exception):
    """The schema uses a keyword this validator does not implement."""


def _type_ok(value, name: str) -> bool:
    if name not in _TYPES:
        raise SchemaUnsupported(f"unknown type {name!r}")
    # bool is a subclass of int in Python and is NOT a JSON number. Without
    # this, `true` validates against {"type": "integer"} and a boolean lands in
    # a field the schema declared numeric.
    if name in ("number", "integer") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[name])


def _check_keywords(schema: dict, where: str) -> None:
    for k in schema:
        if k in _ANNOTATIONS or k in _SUPPORTED:
            continue
        raise SchemaUnsupported(
            f"{where}: schema keyword {k!r} is not implemented by "
            "tools/schema_validate.py. Implement it or the validation is a "
            "pass that read nothing.")


def _matches(value, schema: dict) -> bool:
    """Does `value` satisfy `schema`? Used for `if` -- never reports errors."""
    return not _validate(value, schema, "$", collect=[])


def _validate(value, schema: dict, path: str, collect: list) -> list:
    _check_keywords(schema, path)

    if "type" in schema:
        names = schema["type"]
        names = [names] if isinstance(names, str) else names
        if not any(_type_ok(value, n) for n in names):
            collect.append(f"{path}: expected type {schema['type']}, got "
                           f"{type(value).__name__}")
            return collect

    if "const" in schema and value != schema["const"]:
        collect.append(f"{path}: must be {schema['const']!r}, got {value!r}")
    if "enum" in schema and value not in schema["enum"]:
        collect.append(f"{path}: {value!r} not in {schema['enum']}")
    if "minimum" in schema and isinstance(value, (int, float)) \
            and not isinstance(value, bool) and value < schema["minimum"]:
        collect.append(f"{path}: {value} < minimum {schema['minimum']}")
    if "maximum" in schema and isinstance(value, (int, float)) \
            and not isinstance(value, bool) and value > schema["maximum"]:
        collect.append(f"{path}: {value} > maximum {schema['maximum']}")

    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                collect.append(f"{path}: missing required property {req!r}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for k in value:
                if k not in props:
                    collect.append(f"{path}: property {k!r} is not permitted "
                                   "(additionalProperties: false)")
        for k, sub in props.items():
            if k in value:
                _validate(value[k], sub, f"{path}.{k}", collect)

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            collect.append(f"{path}: {len(value)} items < minItems "
                           f"{schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            collect.append(f"{path}: {len(value)} items > maxItems "
                           f"{schema['maxItems']}")
        if "items" in schema:
            for i, item in enumerate(value):
                _validate(item, schema["items"], f"{path}[{i}]", collect)
        if "contains" in schema and not any(
                _matches(v, schema["contains"]) for v in value):
            collect.append(f"{path}: no item satisfies `contains`")

    # allOf carries the conditional rules, which is where the invariants live.
    for i, sub in enumerate(schema.get("allOf", [])):
        _check_keywords(sub, f"{path}.allOf[{i}]")
        if "if" in sub:
            if _matches(value, sub["if"]):
                if "then" in sub:
                    _validate(value, sub["then"], path, collect)
            elif "else" in sub:
                _validate(value, sub["else"], path, collect)
        else:
            _validate(value, sub, path, collect)
    return collect


def validate(instance, schema: dict) -> list:
    """Return a list of error strings. Empty means valid."""
    return _validate(instance, schema, "$", [])


def validate_file(instance_path: Path, schema_path: Path) -> list:
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    instance = json.loads(Path(instance_path).read_text(encoding="utf-8"))
    return validate(instance, schema)


# --------------------------------------------------------------------------
# SELF-TEST -- red under violation, green after restore.
#
# A validator that returns "valid" is indistinguishable from one that read
# nothing, which is the entire failure mode this file was written against. So
# each case below asserts a SPECIFIC constraint fires, not merely that some
# error appeared: a case expecting the Z2 role bound would otherwise pass on a
# validator that rejected the document for a missing `node_id`.
# --------------------------------------------------------------------------

_BASE = {
    "node_id": "t", "schema_version": 1, "cpu_cores": 4, "ram_gb": 8.0,
    "accelerator": "none", "memory_architecture": "discrete",
    "sustained_tokens_per_sec": {"small": 10.0},
    "measured_at": "2026-08-24T00:00:00Z",
    "trust_zone": "Z1", "availability_class": "usually_on",
    "roles": ["compute_node"],
}


def _self_test() -> int:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    cases = [
        ("the baseline instance is valid", _BASE, None),
        ("INV-TRUST-1: a Z2 node may not be survival_capable",
         {**_BASE, "trust_zone": "Z2", "survival_capable": True},
         "survival_capable"),
        ("INV-TRUST-1: a Z2 node may not hold a compute role",
         {**_BASE, "trust_zone": "Z2"}, "roles[0]"),
        ("a control_candidate must be Z0",
         {**_BASE, "roles": ["control_candidate"]}, "trust_zone"),
        ("a control_candidate must be reliably awake",
         {**_BASE, "trust_zone": "Z0", "roles": ["control_candidate"],
          "availability_class": "foreground_only"}, "availability_class"),
        ("INV-HW-2: a measured profile carries its measurement time",
         {k: v for k, v in _BASE.items() if k != "measured_at"}, "measured_at"),
        ("an undeclared property is refused",
         {**_BASE, "vendor_score": 9}, "vendor_score"),
        ("an unknown enum value is refused",
         {**_BASE, "accelerator": "tpu"}, "accelerator"),
        ("roles may not be empty", {**_BASE, "roles": []}, "minItems"),
        ("a boolean is not an integer",
         {**_BASE, "cpu_cores": True}, "cpu_cores"),
    ]
    failures = 0
    for label, inst, expect in cases:
        errs = validate(inst, schema)
        if expect is None:
            ok = not errs
            detail = "; ".join(errs)
        else:
            ok = any(expect in e for e in errs)
            detail = ("no error mentioning " + repr(expect)
                      + (f" (got: {'; '.join(errs)})" if errs else " (got none)"))
        print(f"  [{'ok  ' if ok else 'FAIL'}] {label}")
        if not ok:
            print(f"         {detail}")
            failures += 1

    # An unimplemented keyword must RAISE, never be skipped.
    raised = False
    try:
        validate({}, {"oneOf": [{"type": "object"}]})
    except SchemaUnsupported:
        raised = True
    print(f"  [{'ok  ' if raised else 'FAIL'}] an unimplemented keyword raises "
          "rather than passing")
    failures += 0 if raised else 1

    print(f"\n  {len(cases) + 1 - failures}/{len(cases) + 1} self-tests behaved "
          "correctly")
    return 1 if failures else 0


SCHEMA_PATH = (Path(__file__).resolve().parents[1] / "contracts" / "entities"
               / "node_capability_profile.schema.json")


def main(argv: list) -> int:
    if len(argv) == 2 and argv[1] == "--self-test":
        return _self_test()
    if len(argv) != 3:
        print("usage: schema_validate.py <instance.json> <schema.json>")
        print("       schema_validate.py --self-test")
        return 2
    errors = validate_file(Path(argv[1]), Path(argv[2]))
    if errors:
        print(f"INVALID: {argv[1]}")
        for e in errors:
            print(f"  {e}")
        return 1
    print(f"VALID: {argv[1]} against {Path(argv[2]).name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
