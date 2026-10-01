#!/usr/bin/env python3
"""Transcodes a Muse track (AAC-in-MP4) to raw PCM for the ESP32 speaker.

GET /play/<track_rowid> -> ffmpeg piping s16le/44100/stereo PCM straight
through to the response body. The ESP32 firmware streams this directly
into I2S; no audio decoding happens on the device.
"""
import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

MUSE_BASE = os.environ.get("CADENCE_MUSE_BASE_URL", "http://ianshomeserver:8080")
LISTEN_PORT = 8765
TRACK_PATH_RE = re.compile(r"^/play/(\d+)$")

# Default EQ: lower the highs, lift the bass a bit. Overridable per
# request via ?bass=<dB>&treble=<dB>, e.g. /play/123?bass=8&treble=-6
DEFAULT_BASS_DB = 6
DEFAULT_TREBLE_DB = -4


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        match = TRACK_PATH_RE.match(parsed.path)
        if not match:
            self.send_error(404, "expected /play/<track_rowid>")
            return

        query = parse_qs(parsed.query)
        bass_db = float(query.get("bass", [DEFAULT_BASS_DB])[0])
        treble_db = float(query.get("treble", [DEFAULT_TREBLE_DB])[0])

        track_rowid = match.group(1)
        source_url = f"{MUSE_BASE}/api/tracks/{track_rowid}/stream"
        audio_filter = f"bass=g={bass_db}:f=110,treble=g={treble_db}:f=8000"

        proc = subprocess.Popen(
            [
                "ffmpeg",
                "-i", source_url,
                "-af", audio_filter,
                "-f", "s16le",
                "-ar", "44100",
                "-ac", "2",
                "-loglevel", "error",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
        )

        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        try:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                self.wfile.write(b"%x\r\n" % len(chunk))
                self.wfile.write(chunk)
                self.wfile.write(b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            proc.stdout.close()
            proc.terminate()
            proc.wait()

    def log_message(self, fmt, *args):
        print(f"[muse_proxy] {self.address_string()} {fmt % args}")


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler)
    print(f"muse_proxy listening on :{LISTEN_PORT}, source {MUSE_BASE}")
    server.serve_forever()
