"""Loopback-only, read-only preview of the invented household review example."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
FILES = {"/": (ROOT / "review/index.html", "text/html; charset=utf-8")}
for name in ("styles.css", "entry.mjs", "app.mjs", "client.mjs", "contracts.mjs", "demo.mjs"):
    FILES["/" + name] = (ROOT / "review" / name, "text/css; charset=utf-8" if name.endswith(".css") else "text/javascript; charset=utf-8")
FILES["/fixtures/furnace-baseline.json"] = (ROOT / "examples/maintenance/furnace-baseline/prepared.json", "application/json; charset=utf-8")
CSP = "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"


class ReviewHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        origins = {"http://" + host for host in hosts}
        if (self.headers.get("Host") not in hosts
                or self.headers.get("Origin", next(iter(origins))) not in origins
                or self.headers.get("Sec-Fetch-Site") == "cross-site"):
            self.send_error(403, "Local preview only")
            return
        parsed = urlsplit(self.path)
        if parsed.query or parsed.path not in FILES:
            self.send_error(404, "Unknown preview file")
            return
        path, content_type = FILES[parsed.path]
        data = path.read_bytes()
        self.send_response(200)
        for key, value in (("Content-Type", content_type), ("Content-Length", str(len(data))),
                           ("Cache-Control", "no-store"), ("Content-Security-Policy", CSP),
                           ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer")):
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, _format, *_args):
        pass  # No household request text or browser headers in preview logs.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be 1024..65535")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), ReviewHandler)
    print(f"Example only: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
