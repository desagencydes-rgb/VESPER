"""Shared acceptance-harness scaffolding: a case, its assertions, its verdict.

ONE RULE IS ENCODED HERE AND IT IS THE ONE THAT MATTERS. A negative control is
`ok` when it FAILS. A control that passes is not a pleasant surprise -- it means
the control tests nothing, and the matching positive result is void rather than
merely unconfirmed. The 2026-08-15 report records four separate occasions where
a control passed while measuring nothing, so the verdict text says "void"
explicitly rather than leaving the reader to infer it.
"""

from __future__ import annotations


class Case:
    def __init__(self, cid: str, title: str, *, control: bool = False) -> None:
        self.cid, self.title, self.control = cid, title, control
        self.assertions: list[dict] = []

    def check(self, name: str, passed: bool, detail: str = "") -> bool:
        self.assertions.append({"assertion": name, "passed": bool(passed),
                                "detail": detail})
        return bool(passed)

    def record(self, rec: dict, sink: list) -> dict:
        sink.append(rec)
        return rec

    def finish(self, error: str | None = None, sink: list | None = None) -> dict:
        allp = bool(self.assertions) and all(a["passed"] for a in self.assertions)
        if self.control:
            ok = not allp
            verdict = ("CONTROL OK -- broken build failed as required" if ok else
                       "HARNESS DEFECT -- the control PASSED, so it tests nothing. "
                       "The matching positive result is void.")
        else:
            ok = allp and error is None
            verdict = "PASS" if ok else "FAIL"
        rec = {"case": self.cid, "title": self.title,
               "is_negative_control": self.control, "ok": ok,
               "verdict": verdict, "assertions": self.assertions}
        if error:
            rec["error"] = error
        if sink is not None:
            sink.append(rec)
        return rec


def print_results(results: list) -> None:
    """One line per case, plus every assertion that did not pass."""
    width = max((len(r["case"]) for r in results), default=8) + 2
    print()
    for r in results:
        print(f"[{'ok  ' if r['ok'] else 'FAIL'}] {r['case']:<{width}} {r['verdict']}")
        for a in r["assertions"]:
            if not a["passed"]:
                sym = "expected-fail" if r["is_negative_control"] else "MISS"
                print(f"           {sym}: {a['assertion']}"
                      + (f" -- {a['detail']}" if a["detail"] else ""))
        if r.get("error"):
            print(f"           ERROR: {r['error'].splitlines()[-1]}")
