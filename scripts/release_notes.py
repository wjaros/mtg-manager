#!/usr/bin/env python3
"""Release notes from the commit messages since the previous release.

Pull requests are squashed, so each commit on master is one change with a written description;
that says more than GitHub's generated notes (the pull request titles only).

    python scripts/release_notes.py <previous tag or ""> <new tag> [repository]

Prints Markdown: download instructions, then per commit its title (a "(#N)" links the pull
request) and description without Co-Authored-By lines, then a link to the full comparison.
"""

import re
import subprocess
import sys

DOWNLOADS = """Download the file for your system:
- **macOS (Apple Silicon: M1/M2/M3/M4)**: `…-arm64.dmg`
- **macOS (Intel)**: `…-x86_64.dmg`
- **Windows**: `…-windows-x64.zip` (unpack it and run `MTG Deck Manager.exe`; needs the Edge WebView2 runtime, built into Windows 11)

macOS: the app is not notarized – the first time, right-click it → Open.
On first start, open Settings → Download card data."""

TRAILER = re.compile(r"^(Co-Authored-By|Signed-off-by):", re.IGNORECASE)
SEPARATOR = "\x1e"  # between commits in the git log output
MAX_COMMITS = 30    # first release (no previous tag): the latest commits only


def commits(previous: str, head: str = "HEAD") -> list[tuple[str, str]]:
    """(title, description) per commit on the first-parent line, newest first."""
    span = [f"{previous}..{head}"] if previous else [f"-{MAX_COMMITS}", head]
    out = subprocess.run(
        ["git", "log", "--first-parent", f"--format=%s%n%b{SEPARATOR}", *span],
        check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout
    result = []
    for chunk in out.split(SEPARATOR):
        lines = chunk.strip("\n").splitlines()
        if not lines:
            continue
        body = [line for line in lines[1:] if not TRAILER.match(line)]
        result.append((lines[0].strip(), unwrap("\n".join(body).strip())))
    return result


LIST_ITEM = re.compile(r"^\s*([-*+]|\d+[.)])\s")


def unwrap(text: str) -> str:
    """Commit messages are wrapped at ~72 columns, and GitHub shows every newline in release notes
    as a line break: join wrapped lines back into paragraphs and list items."""
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            out.append("")
        elif out and out[-1] and not LIST_ITEM.match(line):
            out[-1] += " " + stripped  # continues the paragraph or list item above
        else:
            out.append(line.rstrip())
    return "\n".join(out)


def render(previous: str, tag: str, repository: str, changes: list[tuple[str, str]]) -> str:
    parts = [DOWNLOADS, "## What's changed"]
    for title, description in changes:
        parts.append(f"### {title}" + (f"\n\n{description}" if description else ""))
    if previous and repository:
        parts.append(f"**Full changelog**: https://github.com/{repository}/compare/{previous}...{tag}")
    return "\n\n".join(parts) + "\n"


def main() -> int:
    previous, tag = sys.argv[1], sys.argv[2]
    repository = sys.argv[3] if len(sys.argv) > 3 else ""
    sys.stdout.write(render(previous, tag, repository, commits(previous)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
