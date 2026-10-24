import sys

import pytest

from mtgdm import __main__ as cli


@pytest.fixture
def errors(monkeypatch):
    shown = []
    monkeypatch.setattr(cli, "_show_error", lambda key, **params: shown.append((key, params)))
    return shown


def test_window_toolkit_failure_shows_the_error_and_the_log(monkeypatch, errors):
    def fail():
        raise RuntimeError("Failed to resolve Python.Runtime.Loader.Initialize from Python.Runtime.dll\n   at stack")

    monkeypatch.setattr(cli, "_load_window_toolkit", fail)
    assert cli.cmd_app() == 1
    [(key, params)] = errors
    assert key == "window_failed"
    assert params["error"] == "RuntimeError: Failed to resolve Python.Runtime.Loader.Initialize from Python.Runtime.dll"
    assert params["log"].name == "mtgdm.log"


def test_internet_explorer_fallback_asks_for_webview2(monkeypatch, errors):
    monkeypatch.setattr(cli, "_load_window_toolkit", lambda: "mshtml")
    assert cli.cmd_app() == 1
    assert errors == [("webview2_missing", {})]


@pytest.mark.skipif(sys.platform == "win32", reason="opens a message box")
def test_error_dialog_text_is_translated(capsys):
    cli._show_error("window_failed", error="RuntimeError: x", log="mtgdm.log")
    message = capsys.readouterr().err
    assert "RuntimeError: x" in message and "mtgdm.log" in message


@pytest.mark.skipif(sys.platform != "win32", reason="Zone.Identifier is an NTFS alternate data stream")
def test_unblock_bundle_drops_the_downloaded_mark(tmp_path, monkeypatch):
    dll = tmp_path / "pythonnet" / "runtime" / "Python.Runtime.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"MZ")
    with open(f"{dll}:Zone.Identifier", "w", encoding="utf-8") as mark:
        mark.write("[ZoneTransfer]\nZoneId=3\n")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    cli._unblock_bundle()
    with pytest.raises(FileNotFoundError):
        open(f"{dll}:Zone.Identifier", encoding="utf-8")
    assert dll.read_bytes() == b"MZ"
