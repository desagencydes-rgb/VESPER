"""Serves the SPIKE-004 instrument to the J3 and catches its results.

WHY THIS EXISTS AND NOT `python -m http.server`. The instrument is operated by a
person standing at a phone in a dark room, one hand on the glass. Anything they
have to transcribe afterwards is a number that can be mistyped, and SPIKE-004's
whole output is six numbers. So the page POSTs its own record back and the file
lands in spike-results/ directly. `http.server` answers POST with 501, hence a
handler of our own.

Bind is 0.0.0.0 on purpose: the phone reaches this over the LAN, there is no
cable in the loop (adb does not enumerate this device -- see the spike record).
That also means this listens to the local network while it runs, so it serves
exactly one directory of static test pages and accepts exactly one POST path.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SPIKE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = SPIKE_DIR.parents[1] / "docs" / "planning" / "spike-results"

MAX_BODY = 256 * 1024  # a run record is ~2 KB; this is slack, not a budget


class GhostHandler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SPIKE_DIR), **kw)

    def do_POST(self):  # noqa: N802  (stdlib naming)
        if self.path.split("?")[0] != "/result":
            self.send_error(404, "only /result accepts POST")
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400, "bad Content-Length")
            return
        if length <= 0 or length > MAX_BODY:
            self.send_error(413, "body missing or too large")
            return

        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.send_error(400, f"body is not JSON: {exc}")
            return

        # The page reports what it observed; the server stamps when and from
        # where. A record that dated itself from the phone's clock would be one
        # more thing to trust for no reason.
        now = _dt.datetime.now(_dt.timezone.utc)
        payload["received_at_utc"] = now.isoformat()
        payload["reported_by"] = self.client_address[0]
        payload.setdefault("spike", "SPIKE-004")

        label = re.sub(r"[^a-z0-9-]+", "-", str(payload.get("layout", "run")).lower()).strip("-")
        name = f"SPIKE-004-ghost-{label or 'run'}-{now.strftime('%Y%m%dT%H%M%SZ')}.json"
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULTS_DIR / name
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

        body = json.dumps({"ok": True, "written": name}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        sys.stderr.write(f"[ghost] wrote {out}\n")
        sys.stderr.flush()

    def end_headers(self):
        # The instrument is edited between passes and re-loaded on a phone that
        # will happily serve a stale copy from cache. A measurement taken
        # against yesterday's page is the failure this prevents.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("[ghost] %s\n" % (fmt % args))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()

    srv = ThreadingHTTPServer((args.host, args.port), GhostHandler)
    sys.stderr.write(
        f"[ghost] serving {SPIKE_DIR} on {args.host}:{args.port}\n"
        f"[ghost] results -> {RESULTS_DIR}\n"
    )
    sys.stderr.flush()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
