#!/usr/bin/env python3
"""Serve the A-008 camera audit page over HTTPS on the LAN.

WHY NOT THE ARTIFACT, WHICH ALREADY EXISTS
------------------------------------------
The page was published as an artifact first, and on 2026-08-18 it was run on
the owner's iPhone and reported:

    permission state       denied
    frame camera policy    unknown (no featurePolicy API)
    2 . Devices            No video input devices reported.

with Safari's own Website Settings for the host showing **Camera: Allow**. Both
are true at once. An artifact renders inside a cross-origin iframe, and a frame
only receives the camera if the embedding page hands the permission down with
`allow="camera"`. A site-level grant does not reach into a frame that was never
delegated the capability.

So the artifact is fine for reading and cannot be the instrument. This serves
the same file from a page that IS the top-level document.

WHY HTTPS AND NOT PLAIN HTTP
----------------------------
`getUserMedia` requires a secure context. `http://` on a LAN address is not one
-- only `localhost` gets the exemption, and the devices being audited are not
this machine. `tools/spike/serve_ghost.py` gets away with plain HTTP because
the SPIKE-004 ghost page never touches a camera.

The certificate is self-signed, so the browser will warn once and the owner has
to tap through it. That is the whole cost, and it is smaller than not being
able to run the test.
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import subprocess
import sys
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PAGE = HERE / "camera_audit.html"
RESULTS = REPO / "docs" / "planning" / "spike-results"


def lan_ip() -> str:
    """The address a phone on the same network can actually reach."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.1.1", 1))   # no packet is sent for UDP connect
        return s.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())
    finally:
        s.close()


def ensure_cert(certdir: Path, ip: str) -> tuple[Path, Path]:
    """Self-signed cert with the LAN IP in subjectAltName.

    The IP must be a SAN, not just the CN. Modern browsers ignore the common
    name entirely, and a cert without a matching SAN produces a hard failure on
    iOS rather than the tap-through warning -- which would look exactly like
    the server being broken.
    """
    certdir.mkdir(parents=True, exist_ok=True)
    crt, key = certdir / "camera-audit.crt", certdir / "camera-audit.key"
    if crt.exists() and key.exists():
        return crt, key
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(key), "-out", str(crt), "-days", "30",
         "-subj", "/CN=VESPER camera audit",
         "-addext", f"subjectAltName=IP:{ip},DNS:localhost"],
        check=True, capture_output=True)
    return crt, key


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            # No caching. The SPIKE-004 runs were lost to a page nobody
            # reloaded; a stale instrument that reports confidently is worse
            # than one that fails.
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self):
        """Accept the result blob so it does not have to be copied by hand."""
        if self.path != "/result":
            self.send_error(404); return
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n).decode("utf-8", "replace")
        RESULTS.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%SZ")
        out = RESULTS / f"A-008-camera-audit-{stamp}.json"
        try:
            out.write_text(json.dumps(json.loads(raw), indent=2), encoding="utf-8")
        except json.JSONDecodeError:
            out = out.with_suffix(".raw.txt")
            out.write_text(raw, encoding="utf-8")
        print(f"  [result] {out.name}  ({len(raw)} bytes)", flush=True)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({"saved": out.name}).encode())

    def log_message(self, fmt, *a):
        print(f"  {self.address_string()} {fmt % a}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8443)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--certdir", default=str(HERE / "_certs"))
    a = ap.parse_args()

    if not PAGE.is_file():
        print(f"missing {PAGE}", file=sys.stderr); return 1

    ip = lan_ip()
    crt, key = ensure_cert(Path(a.certdir), ip)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(crt), str(key))

    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    print(f"camera audit page: https://{ip}:{a.port}/")
    print("  self-signed -- the browser warns once, tap through it")
    print(f"  results land in {RESULTS}")
    print("  Ctrl-C to stop")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
