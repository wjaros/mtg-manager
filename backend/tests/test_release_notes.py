import importlib.util
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts" / "release_notes.py"
spec = importlib.util.spec_from_file_location("release_notes", SCRIPT)
release_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_notes)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_notes_from_commit_messages(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "T")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "Old release")
    git(tmp_path, "tag", "v0.1.0")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m",
        "Proxy printing (#1)\n\nPrint proxies of the cards a deck is\nmissing:\n- deck dialog: cards\n  not owned\n- PDF\n\n"
        "Co-Authored-By: Someone <x@example.com>")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "Small fix")
    monkeypatch.chdir(tmp_path)

    changes = release_notes.commits("v0.1.0")
    assert [title for title, _ in changes] == ["Small fix", "Proxy printing (#1)"]  # newest first
    assert changes[1][1] == "Print proxies of the cards a deck is missing:\n- deck dialog: cards not owned\n- PDF"

    notes = release_notes.render("v0.1.0", "v0.2.0", "me/repo", changes)
    assert notes.startswith("Download the file for your system:")
    assert "### Proxy printing (#1)\n\nPrint proxies" in notes and "Co-Authored-By" not in notes
    assert "### Small fix\n\n### Proxy" in notes
    assert notes.rstrip().endswith("https://github.com/me/repo/compare/v0.1.0...v0.2.0")
    # First release: no previous tag, no comparison link.
    assert "Full changelog" not in release_notes.render("", "v0.1.0", "me/repo", release_notes.commits(""))


def test_merge_commits_and_version_bumps(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q", "-b", "master")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "T")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "Old release")
    git(tmp_path, "tag", "v0.1.0")
    # A pull request merged with a merge commit: its own commits carry the descriptions.
    git(tmp_path, "switch", "-q", "-c", "feature")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "Similar cards\n\nRight click on a card.")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "Faster tags (#7)\n\nOne bulk file.")
    git(tmp_path, "switch", "-q", "master")
    git(tmp_path, "merge", "-q", "--no-ff", "feature", "-m",
        "Merge pull request #9 from me/feature\n\nSimilar cards")
    # Squashed with the title pasted into the message again; then a version bump.
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "Windows fix (#10)\n\nWindows fix\n\nUnblock the DLLs.")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "Release 0.2.0 (#11)")
    monkeypatch.chdir(tmp_path)

    assert release_notes.commits("v0.1.0") == [
        ("Windows fix (#10)", "Unblock the DLLs."),
        ("Faster tags (#7)", "One bulk file."),
        ("Similar cards (#9)", "Right click on a card."),
    ]
