#!/usr/bin/env python3
"""Smoke test of a built app: start its executable in server mode on an empty, temporary data
directory and check that the API, the bundled UI, migrations and seeds work. No network needed.

    python scripts/smoke_test.py "dist/MTG Deck Manager.app/Contents/MacOS/mtgdm"
    python scripts/smoke_test.py "dist/MTG Deck Manager/MTG Deck Manager.exe"
"""

import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path

STARTUP_TIMEOUT = 90  # first start of a PyInstaller bundle can be slow on CI


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.status, resp.read()


def test_png(width: int, height: int) -> bytes:
    """White card-sized PNG with a dark border and a text-like bar (stdlib only)."""
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            border = x < 20 or y < 20 or x >= width - 20 or y >= height - 20
            bar = 60 < y < 90 and 60 < x < 400 and (x // 12) % 2 == 0
            row += b"\x20\x20\x20" if border or bar else b"\xf0\xf0\xf0"
        rows.append(b"\x00" + bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b"")


def post_scan(url: str, png: bytes, engine: str) -> dict:
    boundary = "----mtgdm-smoke"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"engine\"\r\n\r\n{engine}\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"test.png\"\r\n"
        "Content-Type: image/png\r\n\r\n"
    ).encode() + png + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(request, timeout=120) as resp:
        return json.loads(resp.read())


def main() -> int:
    exe = Path(sys.argv[1])
    if not exe.is_file():
        print(f"Executable not found: {exe}", file=sys.stderr)
        return 2
    port = free_port()
    base = f"http://127.0.0.1:{port}"

    with tempfile.TemporaryDirectory() as data_dir:
        env = {**os.environ, "MTGDM_DATA_DIR": data_dir}
        proc = subprocess.Popen([str(exe), "serve", "--port", str(port)], env=env)
        try:
            deadline = time.monotonic() + STARTUP_TIMEOUT
            while True:
                if proc.poll() is not None:
                    raise RuntimeError(f"app exited with code {proc.returncode}")
                try:
                    status, body = get(f"{base}/api/health")
                    if status == 200:
                        break
                except OSError:
                    pass
                if time.monotonic() > deadline:
                    raise RuntimeError("app did not start in time")
                time.sleep(0.5)

            health = json.loads(body)
            assert health["status"] == "ok", health
            assert health["schema_version"] >= 1, health
            print(f"health: {health}")

            status, html = get(f"{base}/")
            assert status == 200 and b"<title>MTG Deck Manager</title>" in html, html[:200]
            print("ui: index.html served")

            seeds = json.loads(get(f"{base}/api/import/seeds")[1])
            assert len(seeds) >= 3, seeds
            print(f"seeds: {[s['file'] for s in seeds]}")

            sync = json.loads(get(f"{base}/api/sync/status")[1])
            assert sync["card_count"] == 0 and not sync["progress"]["running"], sync
            print("sync status: empty database, idle")

            # OCR engines and image libraries load inside the bundle: scan a plain test image
            # (empty card database, so nothing is matched; it must just not fail).
            engines = json.loads(get(f"{base}/api/scan-engines")[1])
            for engine in engines["available"]:
                try:
                    scans = post_scan(f"{base}/api/scans", test_png(630, 880), engine)
                except urllib.error.HTTPError as exc:
                    raise RuntimeError(f"scan with {engine}: HTTP {exc.code} {exc.read().decode(errors='replace')}") from exc
                assert scans and scans[0]["status"] == "processed" and scans[0]["ocr_engine"] == engine, scans
            print(f"scan: OCR engines work ({', '.join(engines['available'])})")

            # Deck PDF: Pillow's PDF writer and FreeType fonts are in the bundle (an empty deck renders one page).
            request = urllib.request.Request(f"{base}/api/decks", method="POST", data=b'{"name": "Smoke"}',
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=30) as resp:
                deck_id = json.loads(resp.read())["id"]
            status, pdf = get(f"{base}/api/decks/{deck_id}/export/pdf")
            assert status == 200 and pdf.startswith(b"%PDF"), pdf[:100]
            print("pdf: deck export works")

            assert (Path(data_dir) / "db.sqlite").is_file(), "database not created"
            print("OK")
            return 0
        except Exception as exc:  # report and fail the CI step
            print(f"SMOKE TEST FAILED: {exc}", file=sys.stderr)
            log = Path(data_dir) / "logs" / "mtgdm.log"
            if log.is_file():
                print("--- app log ---", file=sys.stderr)
                print(log.read_text(encoding="utf-8", errors="replace")[-4000:], file=sys.stderr)
            return 1
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
