"""VESPER's face on a display node: served over the local network, and nothing else.

THE OWNER, 2026-09-12, asked for a node that carries "vesper's face, speaker,
microphone, showing stuff, hologram", and on 2026-09-13 for the hologram first.
HOME-WORKBENCH §32.1 decides what this is: the island's face on a second
surface, not a second face. SPIKE-004 measures the optics; this serves the face
the rig reflects.

NAMED BY ITS ROLE, NEVER BY A HANDSET (INV-HW-1). The first draft carried a
device's model name in this module, its routes and its preference, and
`no-product-names` refused it. Any node with a browser and a display can open
this; placement, not a product, decides which one does.

WHAT CROSSES THE NETWORK, AND WHAT NEVER DOES. The page, the face's point cloud
(`face.bin`, derived from the owner's reference image and already shipped inside
the app) and the NAME of what the face is doing. Never the transcript, the
cards, the windows, or anything a person on the same Wi-Fi should not read: a
listener on the LAN is readable by everyone on it, so the state it serves is
built from an allowlist of two keys, never filtered out of `home.json`.

THE NODE'S NUMBERS ARE MEASURED ON THE NODE (§32.2, INV-HW-2). The page reports
the frame rate it actually sustained, with the point count and viewport it drew
at; each reading lands in `face-surface-readings.jsonl`, validated and bounded.
A reading that is not a number, or not one a display can produce, is refused
rather than recorded.

A MODULE INSIDE VESPER'S RUNTIME, NOT A SCRIPT. Everything runs as VESPER from
the bundle; `start()` returns the server so a check can drive it on an
ephemeral port and stop it.
"""

from __future__ import annotations

import json
import pathlib
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = pathlib.Path(__file__).resolve().parent
STATE = pathlib.Path.home() / "Library" / "Application Support" / "VESPER"
PORT = 8741
PAGE = HERE / "face_surface.html"
# The bundle carries face.bin at Contents/Resources/face.bin, one level above the
# runtime directory this module's copy sits in; from the repo it sits beside the
# island's sources.
FACE_BIN_CANDIDATES = (HERE.parents[1] / "face.bin",
                       HERE.parent / "app" / "island-macos" / "face.bin")
STATE_KEYS = ("behaviour", "since_s")
READINGS = "face-surface-readings.jsonl"
MAX_READINGS_BYTES = 256_000


def face_bin_path() -> pathlib.Path | None:
    for p in FACE_BIN_CANDIDATES:
        if p.is_file():
            return p
    return None


def state(state_dir: pathlib.Path) -> dict:
    """What the face is doing, from an allowlist. Nothing else leaves."""
    try:
        face = json.loads((state_dir / "home.json").read_text(encoding="utf-8")).get("face") or {}
    except (OSError, ValueError, AttributeError):
        face = {}
    out: dict = {}
    b = face.get("behaviour") if isinstance(face, dict) else None
    out["behaviour"] = b if isinstance(b, str) and b else "resting"
    s = face.get("since_s") if isinstance(face, dict) else None
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        out["since_s"] = round(float(s), 1)
    return out


def record(state_dir: pathlib.Path, query: dict, *, peer: str) -> tuple[bool, str]:
    """One reading measured on the device, or a refusal saying why."""
    try:
        fps = float(query.get("fps", [""])[0])
        points = int(query.get("points", [""])[0])
        w = int(query.get("w", [""])[0])
        h = int(query.get("h", [""])[0])
    except (ValueError, IndexError, TypeError):
        return False, "a reading is fps, points, w and h, as numbers"
    if not (0 < fps <= 240 and 0 < points <= 100_000 and 0 < w <= 8192 and 0 < h <= 8192):
        return False, "a reading outside what a display can report is not recorded"
    p = state_dir / READINGS
    if p.exists() and p.stat().st_size > MAX_READINGS_BYTES:
        return False, "the readings file has reached its bound"
    rec = {"at_ms": int(time.time() * 1000), "fps": fps, "points": points, "w": w, "h": h,
           "peer": str(peer), "source": "measured on the device by the served face page"}
    state_dir.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return True, ""


def make_handler(*, state_dir: pathlib.Path, page: pathlib.Path,
                 face_bin: pathlib.Path | None) -> type:
    class FaceHandler(BaseHTTPRequestHandler):
        server_version = "VESPER-face"

        def log_message(self, fmt, *args):  # noqa: D401 -- the bus is the log, not stderr
            return

        def _send(self, code: int, body: bytes = b"", ctype: str = "text/plain; charset=utf-8",
                  extra: dict | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self):  # noqa: N802 -- stdlib naming
            u = urlparse(self.path)
            if u.path in ("/", "/face"):
                return self._send(302, extra={"Location": "/face/"})
            if u.path in ("/face/", "/face/index.html"):
                return self._send(200, page.read_bytes(), "text/html; charset=utf-8")
            if u.path == "/face/face.bin":
                if face_bin is None or not face_bin.is_file():
                    return self._send(404, b"no face cloud on this node")
                return self._send(200, face_bin.read_bytes(), "application/octet-stream")
            if u.path == "/face/state.json":
                return self._send(200, json.dumps(state(state_dir)).encode("utf-8"),
                                  "application/json")
            if u.path == "/face/reading":
                ok, why = record(state_dir, parse_qs(u.query), peer=self.client_address[0])
                return self._send(204) if ok else self._send(400, why.encode("utf-8"))
            return self._send(404, b"not served here")

        def do_POST(self):  # noqa: N802
            return self._send(405, b"this surface accepts no writes")

        do_PUT = do_POST
        do_DELETE = do_POST

    return FaceHandler


def start(*, port: int = PORT, host: str = "0.0.0.0", state_dir: pathlib.Path | None = None,
          page: pathlib.Path | None = None, face_bin: pathlib.Path | None = None) -> ThreadingHTTPServer:
    """Serve the face from a daemon thread. `server.server_address[1]` is the port."""
    handler = make_handler(state_dir=pathlib.Path(state_dir or STATE),
                           page=pathlib.Path(page or PAGE),
                           face_bin=pathlib.Path(face_bin) if face_bin else face_bin_path())
    srv = ThreadingHTTPServer((host, port), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, name="face-surface", daemon=True).start()
    return srv


def stop(srv: ThreadingHTTPServer) -> None:
    srv.shutdown()
    srv.server_close()
