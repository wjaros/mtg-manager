"""Opening search links in the system browser from the window app (its web view would open one link per
click only). Off in a browser (`mtgdm serve`): there the page opens links itself, one per click."""

import threading
import time
import webbrowser
from collections.abc import Callable

TAB_DELAY = 0.4  # seconds between tabs, so the browser keeps them in order and isn't flooded

_enabled = False


def set_enabled(enabled: bool) -> None:
    """`mtgdm app` turns this on."""
    global _enabled
    _enabled = enabled


def enabled() -> bool:
    return _enabled


def open_urls(urls: list[str], opener: Callable[[str], object] = webbrowser.open_new_tab,
              sleep: Callable[[float], None] = time.sleep) -> threading.Thread:
    """Open the URLs one by one in the background; returns the thread (tests join it)."""

    def run() -> None:
        for i, url in enumerate(urls):
            if i:
                sleep(TAB_DELAY)
            opener(url)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread
