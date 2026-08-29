#!/usr/bin/env python3.13
"""Can these rungs actually hold a conversation in Darija?

WHAT IS BEING DECIDED. VESPER answering the owner in Moroccan Darija is a
design choice that only works if the rungs can do it. None of the four private
rungs is Darija-tuned; the published benchmarks (DarijaMMLU, DarijaBench) cover
Arabic script and barely touch the Latin/Arabizi form Moroccans actually text
in. So the question is open on exactly the form that matters, and looking it up
answers the wrong question.

THE TWO THINGS MEASURED, AND THEY ARE DIFFERENT QUESTIONS:

  1. UNPROMPTED -- given Darija in, does it come back in Darija without being
     told? If yes, this costs nothing. If no, an instruction is needed and that
     instruction occupies the same resident block everything else competes for.
  2. INSTRUCTED -- told plainly to answer in Darija, does it comply, and does it
     produce DARIJA or Modern Standard Arabic? MSA is the common failure: the
     model answers in Arabic, technically correct, and reads foreign. A
     response can be fluent, on-topic, and still wrong for this purpose.

WHAT THIS SCRIPT MAY AND MAY NOT JUDGE. It can check mechanically: which script
came back, whether the reply is Arabic at all, and whether it carries Darija
markers (bghit, wach, dyal, daba, bzaf, chnou) or MSA markers. It CANNOT judge
whether the Darija sounds natural to a Moroccan ear. That is the owner's call,
so every response is printed in full for review rather than reduced to a score.
A probe that graded fluency itself would be inventing the one measurement it is
least qualified to make.

Cheap: 4 prompts x 2 conditions x N rungs, short replies.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cache_discount_probe as _cdp       # noqa: E402
from cache_discount_probe import (        # noqa: E402
    ROOT, SUPPLY, load_secrets, post, usage_of,
)

# A CONVERSATIONAL PROBE MUST NOT WAIT LIKE A BATCH ONE. The shared helper
# allows 120 s, which is right for a large-prefix cache call and wrong here:
# ten slow replies turn a five-minute probe into forty minutes, and with output
# buffered that is indistinguishable from a hang. A reply that takes longer than
# this is a failed reply for conversational purposes anyway.
_cdp.TIMEOUT = 25.0

OUT = ROOT / "docs" / "spikes" / "data" / "darija_probe.json"

# Realistic VESPER turns, in Latin-script Darija -- the form actually used in
# texting, and the form the benchmarks do not cover.
PROMPTS = [
    ("alarm",    "chhal baqi 3la l'alarm dyali?"),
    ("status",   "wach node 1 khedama daba?"),
    ("mixed",    "wach kayn chi problem f the router config?"),
    ("summary",  "3tini résumé dyal chno drt lyoum"),
]
ENGLISH_CONTROL = ("control_en", "how long until my alarm?")

# Told to answer in Darija, in the same Latin script. Deliberately short: if a
# long instruction is needed, that is itself a finding, because it competes for
# the same resident budget as memory.
INSTRUCTION = ("Answer in Moroccan Darija written with Latin letters and "
               "numbers, the way Moroccans text. Keep it under 20 words.")

ARABIC = re.compile(r"[؀-ۿ]")
# Words that are Darija and not MSA. Presence is evidence of dialect; absence
# is not evidence of its lack, so this counts rather than decides.
DARIJA_MARKERS = ("bghit", "wach", "dyal", "daba", "bzaf", "chnou", "chno",
                  "shnu", "ghadi", "mzyan", "3ndi", "kayn", "walo", "safi",
                  "baqi", "khedama", "3la", "dyali", "hna", "nta", "ana")
MSA_MARKERS = ("سوف", "أريد", "هل ", "جدا", "الآن", "لدي", "يمكنني", "sawfa",
               "urid", "hal ", "jiddan")


def _hits(markers, text: str) -> list:
    """Word-boundary matching, because substring matching gets this backwards.

    Measured while building this: plain `in` matched the MSA marker "hal " inside
    "chhal" -- so the single most characteristic Darija word in the test set was
    scoring as evidence of Modern Standard Arabic. Latin markers therefore need
    boundaries. Arabic-script markers are matched plainly: Arabic does not
    delimit with spaces the way `\b` assumes, and a boundary there would miss
    real hits.
    """
    out = set()
    for m in markers:
        m_s = m.strip()
        if not m_s:
            continue
        if ARABIC.search(m_s):
            if m_s in text:
                out.add(m_s)
        else:
            # ASYMMETRIC ON PURPOSE, and the asymmetry has a reason rather than
            # being a convenience.
            #
            # Latin Darija is heavily inflected and agglutinative in
            # transcription -- bghit/bghiti/bghitini, kayn/kaynch/makaynch --
            # so a marker has to match as a STEM at a word start or the
            # detector misses most real writing. Measured 2026-08-29: strict
            # boundaries scored two plainly-Darija replies as containing no
            # Darija at all, because the model wrote `bghiti` and `kaynch`.
            #
            # MSA markers keep the closing boundary, because the failure there
            # ran the other way: `hal ` matched inside `chhal`, scoring the most
            # characteristic Darija word in the set as evidence of MSA. A stem
            # match on MSA would reintroduce exactly that.
            strict = markers is MSA_MARKERS
            tail = r"(?![a-z0-9])" if strict else ""
            if re.search(rf"(?<![a-z0-9]){re.escape(m_s)}{tail}", text.lower()):
                out.add(m_s)
    return sorted(out)


def score(text: str) -> dict:
    arabic_chars = len(ARABIC.findall(text or ""))
    return {
        "script": ("arabic" if arabic_chars > len(text or "") * 0.15
                   else "latin"),
        "arabic_chars": arabic_chars,
        "darija_markers": _hits(DARIJA_MARKERS, text or ""),
        "msa_markers": _hits(MSA_MARKERS, text or ""),
        "words": len((text or "").split()),
    }


def reply_text(body: dict) -> str:
    for path in (("choices", 0, "message", "content"),
                 ("result", "response"), ("output",)):
        cur = body
        try:
            for k in path:
                cur = cur[k]
            if isinstance(cur, str) and cur.strip():
                return cur.strip()
        except (KeyError, IndexError, TypeError):
            continue
    return ""


def main() -> int:
    only = sys.argv[1:] or None
    load_secrets()
    supply = tomllib.loads(SUPPLY.read_text())
    rows = [p for p in supply["provider"]
            if p.get("egress_class") == "E1_PRIVATE"
            and p.get("wire") == "openai_chat"
            and p.get("purpose", "text") == "text"
            and (only is None or p["id"] in only)]

    results = []
    for p in rows:
        cred = os.environ.get(p.get("credential_env", ""), "")
        if not cred:
            print(f"skip {p['id']}: no credential"); continue
        ep = p["endpoint"].replace("{model}", p["model"])
        hdr = {"Authorization": f"Bearer {cred}"}
        pace = 21.0 if p["id"] == "mistral-standard" else 3.0

        print(f"\n{'='*74}\n{p['id']}  ({p['model']})\n{'='*74}")
        for cond, system in (("unprompted", None), ("instructed", INSTRUCTION)):
            print(f"\n--- {cond} ---")
            for name, text in PROMPTS + [ENGLISH_CONTROL]:
                msgs = ([{"role": "system", "content": system}] if system
                        else []) + [{"role": "user", "content": text}]
                payload = {"model": p["model"], "messages": msgs,
                           "max_tokens": 120, "temperature": 0}
                if "reasoning_effort" in (p.get("supports") or []):
                    payload["reasoning_effort"] = "low"
                body, _h, elapsed = post(ep, payload, hdr)
                out = reply_text(body)
                err = body.get("__http_error__") or body.get("__error__")
                sc = score(out)
                results.append({"provider": p["id"], "condition": cond,
                                "prompt_name": name, "prompt": text,
                                "reply": out, "error": str(err) if err else None,
                                "elapsed_s": round(elapsed, 2), **sc})
                # WRITTEN AFTER EVERY CALL, not at the end. A run killed at
                # minute 21 otherwise loses all twenty calls it already spent
                # quota on, and the next run has to spend it again.
                OUT.parent.mkdir(parents=True, exist_ok=True)
                OUT.write_text(json.dumps(
                    {"probe": "darija", "when": time.strftime("%F %T"),
                     "instruction": INSTRUCTION, "partial": True,
                     "results": results}, indent=2))
                flag = "ERR " + str(err)[:40] if err else (
                    f"{sc['script']:6} d={len(sc['darija_markers'])} "
                    f"msa={len(sc['msa_markers'])}")
                print(f"  [{name:10}] {flag}", flush=True)
                print(f"     Q: {text}", flush=True)
                print(f"     A: {out[:200] or '(empty)'}",
                      flush=True)
                time.sleep(pace)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"probe": "darija", "when": time.strftime("%F %T"),
                               "instruction": INSTRUCTION,
                               "results": results}, indent=2))

    print(f"\n\n{'='*74}\nMECHANICAL SUMMARY — fluency is NOT judged here\n{'='*74}")
    print(f"{'provider':<20} {'cond':<11} {'latin':>6} {'arabic':>7} "
          f"{'darija mk':>10} {'msa mk':>7} {'errors':>7}")
    for pid in sorted({r['provider'] for r in results}):
        for cond in ("unprompted", "instructed"):
            xs = [r for r in results if r["provider"] == pid
                  and r["condition"] == cond and r["prompt_name"] != "control_en"]
            if not xs:
                continue
            print(f"{pid:<20} {cond:<11} "
                  f"{sum(1 for r in xs if r['script']=='latin'):>6} "
                  f"{sum(1 for r in xs if r['script']=='arabic'):>7} "
                  f"{sum(len(r['darija_markers']) for r in xs):>10} "
                  f"{sum(len(r['msa_markers']) for r in xs):>7} "
                  f"{sum(1 for r in xs if r['error']):>7}")
    print(f"\nRead the replies above and judge them yourself — marker counts say "
          f"a dialect\nwas reached for, never that it landed.")
    print(f"raw -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
