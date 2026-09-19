#!/usr/bin/env python3
"""
Binds to Render's public $PORT and does two jobs:

1. Proxies every normal request (getMe, getFile, sendMessage, etc. --
   anything under /bot<token>/... or /file/bot<token>/...) straight
   through to the telegram-bot-api process, which start.sh runs
   internally on TBA_PORT. This is what the bot's normal Bot API calls
   use, unchanged.

2. Serves /localfile/<path> itself, directly off disk.

   Why this exists: telegram-bot-api's --local mode (needed to lift the
   20MB download cap) makes getFile return an ABSOLUTE LOCAL DISK PATH
   in file_path, not a relative path you can fetch over the normal
   /file/bot<token>/<path> HTTP endpoint -- that endpoint doesn't
   resolve absolute paths. So a remote caller (the Cloudflare Worker)
   has no way to fetch the actual bytes through telegram-bot-api itself
   once a file is large enough to need --local mode. This tiny endpoint
   is the workaround: it reads the file directly from the shared disk
   this process and telegram-bot-api both have access to.

   Access requires a valid HMAC-SHA256 signature over "<path>:<expires>"
   (hex-encoded) plus an unexpired timestamp, both passed as query
   params and checked against LOCAL_FILE_SECRET. Without that check,
   anyone who saw one /localfile/ URL could read any file ever cached
   here, for any bot token this server has ever served -- there's no
   other access control on this endpoint.
"""
import hashlib
import hmac
import http.server
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qs, unquote, urlparse

TBA_PORT = int(os.environ.get("TBA_PORT", "8081"))
SECRET = os.environ.get("LOCAL_FILE_SECRET", "")
DATA_DIR = os.path.realpath(os.environ.get("DATA_DIR", "/data"))
CHUNK = 256 * 1024
# getFile par bade files (600MB+) ke liye telegram-bot-api khud Telegram se
# poora file disk par utaarta hai, USI KE BAAD response deta hai -- yeh
# download hi kaafi der (kayi minute) le sakta hai bade files par. Isliye
# proxy timeout ko yahan bada rakha hai; chhote/fast calls (getMe,
# sendMessage) is se prabhavit nahi honge, woh vaise hi turant reply karte
# hain.
PROXY_TIMEOUT = int(os.environ.get("PROXY_TIMEOUT_SECONDS", "900"))


def verify_signature(path, expires, sig):
    if not SECRET or not sig or not expires:
        return False
    try:
        if int(expires) < int(time.time()):
            return False
    except ValueError:
        return False
    expected = hmac.new(
        SECRET.encode(), f"{path}:{expires}".encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig)


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _serve_local_file(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        raw_path = unquote(parsed.path[len("/localfile/"):])
        expires = qs.get("expires", [None])[0]
        sig = qs.get("sig", [None])[0]

        if not verify_signature(raw_path, expires, sig):
            self.send_error(403, "Invalid or expired link")
            return

        # raw_path is the absolute path telegram-bot-api's getFile gave
        # the Worker (e.g. "/data/<hash>/documents/foo.pdf"). Resolve and
        # confirm it's actually inside DATA_DIR before touching disk --
        # this is the only thing standing between a signed request and
        # arbitrary file read.
        full_path = os.path.realpath(raw_path)
        if not (full_path == DATA_DIR or full_path.startswith(DATA_DIR + os.sep)):
            self.send_error(403, "Path outside data directory")
            return
        if not os.path.isfile(full_path):
            self.send_error(404, "Not found")
            return

        size = os.path.getsize(full_path)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(full_path, "rb") as f:
            while True:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def _delete_local_file(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        raw_path = unquote(parsed.path[len("/localfile/"):])
        expires = qs.get("expires", [None])[0]
        sig = qs.get("sig", [None])[0]

        if not verify_signature(raw_path, expires, sig):
            self.send_error(403, "Invalid or expired link")
            return

        full_path = os.path.realpath(raw_path)
        if not (full_path == DATA_DIR or full_path.startswith(DATA_DIR + os.sep)):
            self.send_error(403, "Path outside data directory")
            return
        if not os.path.isfile(full_path):
            self.send_error(404, "Not found")
            return

        try:
            os.remove(full_path)
        except OSError as e:
            self.send_error(500, f"Could not delete: {e}")
            return

        body = b"deleted"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _proxy(self):
        url = f"http://127.0.0.1:{TBA_PORT}{self.path}"
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(url, data=body, method=self.command)
        for k, v in self.headers.items():
            if k.lower() not in ("host", "content-length"):
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=PROXY_TIMEOUT) as resp:
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(k, v)
                self.end_headers()
                if self.command != "HEAD":
                    while True:
                        chunk = resp.read(64 * 1024)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
        except urllib.error.HTTPError as e:
            body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except Exception as e:  # noqa: BLE001 -- last-resort proxy failure
            self.send_error(502, f"Upstream error: {e}")

    def do_GET(self):
        if self.path.startswith("/localfile/"):
            self._serve_local_file()
        else:
            self._proxy()

    def do_HEAD(self):
        if self.path.startswith("/localfile/"):
            self._serve_local_file()
        else:
            self._proxy()

    def do_POST(self):
        self._proxy()

    def do_DELETE(self):
        if self.path.startswith("/localfile/"):
            self._delete_local_file()
        else:
            self.send_error(404, "Not found")

    def log_message(self, fmt, *args):  # noqa: A003 -- stdlib signature
        sys.stderr.write("[fileserver] " + (fmt % args) + "\n")


class ThreadingHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    if not SECRET:
        print("!!! LOCAL_FILE_SECRET is not set -- /localfile/ will refuse every request.", file=sys.stderr)
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"[fileserver] listening on 0.0.0.0:{port}, proxying to 127.0.0.1:{TBA_PORT}, DATA_DIR={DATA_DIR}")
    server.serve_forever()
