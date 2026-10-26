"""CLI entry point: mtgdm app | serve | sync."""

import argparse
import contextlib
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

from mtgdm import __version__, prefs
from mtgdm.app import create_app
from mtgdm.config import FROZEN, load_settings
from mtgdm.db import connect
from mtgdm.i18n import Lang, set_lang, tr

DEFAULT_PORT = 8765
# Windows: require the Edge WebView2 runtime; older engines cannot run the UI.
WINDOW_GUI = "edgechromium" if sys.platform == "win32" else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mtgdm", description="MTG Deck Manager")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    # The bundled app is started without arguments (double click): open the window.
    sub = parser.add_subparsers(dest="command", required=not FROZEN)

    sub.add_parser("app", help="run in a native window (pywebview)")
    sub.add_parser("check-window", help="load the window toolkit without opening a window (smoke test)")

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
    if args.command == "check-window":
        return cmd_check_window()
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
    # Before the server: a window that can't open is reported without starting anything.
    try:
        renderer = _load_window_toolkit()
    except Exception as exc:
        logging.exception("Could not load the window toolkit")
        _show_error("window_failed", error=_error_text(exc), log=_log_path())
        return 1
    if renderer == "mshtml":
        # pywebview falls back to Internet Explorer when WebView2 is missing; the UI doesn't run there.
        logging.error("Edge WebView2 runtime not found")
        _show_error("webview2_missing")
        return 1

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
    window = webview.create_window(
        "MTG Deck Manager", f"http://127.0.0.1:{port}/", width=1400, height=900, min_size=(900, 600)
    )
    # The interface scale (Settings, Cmd/Ctrl +/−) zooms the web view: set before the page loads, then on changes.
    window.events.before_show += lambda: _set_page_zoom(window, _saved_scale(), gui_thread=True)
    prefs.set_window_zoom(lambda scale: _set_page_zoom(window, scale))
    try:
        webview.start(gui=WINDOW_GUI)
    except Exception as exc:
        logging.exception("Could not open the app window")
        _show_error("window_failed", error=_error_text(exc), log=_log_path())
        return 1
    finally:
        prefs.set_window_zoom(None)
        server.should_exit = True
        thread.join(timeout=5)
    return 0


def _saved_scale() -> float:
    conn = connect(load_settings().db_path)
    try:
        return prefs.get_scale(conn)
    finally:
        conn.close()


def _set_page_zoom(window, scale: float, gui_thread: bool = False) -> None:
    """Zoom the window's web view like a browser does (layout, text, image resolution). Called from
    another thread, the change is handed to the GUI thread."""
    try:
        if sys.platform == "darwin":
            from PyObjCTools import AppHelper
            from webview.platforms.cocoa import BrowserView

            view = BrowserView.instances.get(window.uid)
            if view is None or not view.webview.respondsToSelector_("setPageZoom:"):  # WKWebView.pageZoom: macOS 11+
                return
            if gui_thread:
                view.webview.setPageZoom_(scale)
            else:
                AppHelper.callAfter(view.webview.setPageZoom_, scale)
        elif sys.platform == "win32":
            from System import Func, Type

            form = window.native
            if form is None or form.webview is None:
                return

            def zoom():
                form.webview.ZoomFactor = scale  # kept by the WebView2 control until its core is ready

            if gui_thread:
                zoom()  # the form has no handle yet: Invoke would fail
            else:
                form.Invoke(Func[Type](zoom))
    except Exception:
        logging.exception("Could not zoom the app window")


def cmd_check_window() -> int:
    """The smoke test of a built app runs this (on Windows with the bundle's files marked as downloaded)."""
    renderer = _load_window_toolkit()
    if sys.platform == "win32":
        # The WebView2 assemblies load even without the runtime, which a CI runner may lack.
        import webview.platforms.edgechromium  # noqa: F401
    print(f"window toolkit: {renderer}")
    return 0


def _load_window_toolkit() -> str:
    """Load pywebview's GUI backend (Windows: WinForms and WebView2 through pythonnet / .NET) and
    return the web engine it picked."""
    from webview.guilib import initialize

    if FROZEN and sys.platform == "win32":
        _unblock_bundle()
    return initialize(WINDOW_GUI).renderer


def _unblock_bundle() -> None:
    """Files unpacked from a downloaded zip carry Windows' "from the internet" mark (a Zone.Identifier
    stream), and .NET refuses to load assemblies marked so (pythonnet, WebView2): the window can't open.
    Drop the mark from the bundle's DLLs, as Unblock-File does; the user has already chosen to run the
    app. Best effort: a read-only folder keeps its marks."""
    bundle = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    for dll in bundle.rglob("*.dll"):
        with contextlib.suppress(OSError):
            os.remove(f"{dll}:Zone.Identifier")


def _error_text(exc: Exception) -> str:
    """First line of an error for a dialog (.NET errors carry their stack trace; the log has it all)."""
    lines = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {lines[0] if lines else ''}"[:300]


def _show_error(key: str, **params: object) -> None:
    """Visible error for a windowed app without a console, in the system's language (the UI is not up)."""
    token = set_lang(_system_lang())
    try:
        message = tr(key, **params)
    finally:
        token.var.reset(token)
    print(message, file=sys.stderr)
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "MTG Deck Manager", 0x10)  # MB_ICONERROR


def _system_lang() -> Lang:
    if sys.platform == "win32":
        import ctypes

        return "pl" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x15 else "en"  # LANG_POLISH
    return "pl"


def cmd_sync(force: bool) -> int:
    from mtgdm.scryfall.sync import run_sync

    labels = {"sets": "Sets", "set_icons": "Set icons", "download": "Downloading cards", "import": "Importing cards",
              "precons": "Precons", "tags": "Downloading card functions"}
    started = time.monotonic()

    def progress(stage: str, done: int, total: int) -> None:
        if stage in ("download", "tags"):
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
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    log = open(path, "a", buffering=1, encoding="utf-8")  # kept open for the whole process
    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log
    logging.basicConfig(
        stream=log, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True
    )


def _log_path() -> Path:
    return load_settings().logs_dir / "mtgdm.log"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


if __name__ == "__main__":
    sys.exit(main())
