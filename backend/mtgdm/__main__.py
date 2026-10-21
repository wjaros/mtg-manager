"""CLI entry point: mtgdm app | serve | sync."""

import argparse
import logging
import socket
import sys
import threading
import time

import uvicorn

from mtgdm import __version__
from mtgdm.app import create_app
from mtgdm.config import FROZEN, load_settings

DEFAULT_PORT = 8765


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mtgdm", description="MTG Deck Manager")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    # The bundled app is started without arguments (double click): open the window.
    sub = parser.add_subparsers(dest="command", required=not FROZEN)

    sub.add_parser("app", help="run in a native window (pywebview)")

    serve = sub.add_parser("serve", help="run as an HTTP server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev)")

    sync = sub.add_parser("sync", help="download / refresh Scryfall data")
    sync.add_argument("--force", action="store_true", help="re-import cards even if bulk data is unchanged")

    args = parser.parse_args(argv)
    if FROZEN:
        _log_to_file()
    if args.command == "serve":
        return cmd_serve(args.host, args.port, args.reload)
    if args.command in ("app", None):
        return cmd_app()
    if args.command == "sync":
        return cmd_sync(args.force)
    return 2


def cmd_serve(host: str, port: int, reload: bool) -> int:
    if reload:
        uvicorn.run("mtgdm.app:create_app", factory=True, host=host, port=port, reload=True)
    else:
        uvicorn.run(create_app(), host=host, port=port)
    return 0


def cmd_app() -> int:
    import webview

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        if not thread.is_alive():
            print("Server failed to start", file=sys.stderr)
            return 1
        time.sleep(0.05)

    # Exports (CSV, decklists) are plain downloads from the API.
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.create_window("MTG Deck Manager", f"http://127.0.0.1:{port}/", width=1400, height=900, min_size=(900, 600))
    try:
        # Windows: require the Edge WebView2 runtime; older engines cannot run the UI.
        webview.start(gui="edgechromium" if sys.platform == "win32" else None)
    except Exception:
        logging.exception("Could not open the app window")
        _show_error(
            "Nie można otworzyć okna aplikacji.\n\n"
            + (
                "Zainstaluj Microsoft Edge WebView2 Runtime:\n"
                "https://developer.microsoft.com/microsoft-edge/webview2/"
                if sys.platform == "win32"
                else "Szczegóły w pliku logu w katalogu danych aplikacji."
            )
        )
        return 1
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    return 0


def _show_error(message: str) -> None:
    """Visible error for a windowed app without a console."""
    print(message, file=sys.stderr)
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "MTG Deck Manager", 0x10)  # MB_ICONERROR


def cmd_sync(force: bool) -> int:
    from mtgdm.scryfall.sync import run_sync

    labels = {"sets": "Sets", "set_icons": "Set icons", "download": "Downloading cards", "import": "Importing cards"}
    started = time.monotonic()

    def progress(stage: str, done: int, total: int) -> None:
        if stage == "download":
            amount = f"{done / 1e6:.0f}/{total / 1e6:.0f} MB" if total else f"{done / 1e6:.0f} MB"
        else:
            amount = f"{done}/{total}" if total else str(done)
        print(f"\r{labels.get(stage, stage)}: {amount}\033[K", end="", file=sys.stderr, flush=True)

    settings = load_settings()
    result = run_sync(settings, force=force, on_progress=progress)
    print(file=sys.stderr)
    cards = result.cards
    if cards.skipped:
        print(f"{result.sets} sets; cards already up to date (Scryfall data from {cards.updated_at}).")
    else:
        print(f"{result.sets} sets, {cards.cards} cards imported, {cards.removed} removed"
              f" (Scryfall data from {cards.updated_at}) in {time.monotonic() - started:.0f} s.")
    print(f"Database: {settings.db_path}")
    return 0


def _log_to_file() -> None:
    """A windowed bundle has no console (stdout/stderr may be None): log to the data dir."""
    settings = load_settings()
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    log = open(settings.logs_dir / "mtgdm.log", "a", buffering=1, encoding="utf-8")  # kept open for the whole process
    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log
    logging.basicConfig(
        stream=log, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


if __name__ == "__main__":
    sys.exit(main())
