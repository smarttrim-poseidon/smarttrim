"""Serve the Test Replay demo locally (no internet needed): python demo/serve.py [--port 8765]

Binds to 127.0.0.1 only. Sets explicit content types, because some Windows
installations map .js to text/plain, which browsers refuse for ES modules.
"""
import argparse
import functools
import http.server
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".json": "application/json",
         ".csv": "text/csv", ".stl": "model/stl", ".mp4": "video/mp4",
         ".css": "text/css", ".html": "text/html"}


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, **TYPES}

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def make_server(port=8765, directory=DEMO_DIR):
    handler = functools.partial(Handler, directory=str(directory))
    return http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)


def main():
    parser = argparse.ArgumentParser(description="Serve the SmartTrim Test Replay demo")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = make_server(args.port)
    print(f"SmartTrim V5 · Test Replay: http://127.0.0.1:{args.port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
