#!/usr/bin/env python3
"""Release notes from the commit messages since the previous release.

Pull requests are squashed, so each commit on master is one change with a written description;
that says more than GitHub's generated notes (the pull request titles only). One merged with a merge
commit stands for the commits it brought; version bumps are left out.

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
MERGE = re.compile(r"^Merge pull request #(\d+) from ")
RELEASE = re.compile(r"^Release \d+\.\d+\.\d+\b")  # a version bump, not a change
BRANCH_SYNC = re.compile(r"\* Merge (remote-tracking )?branch .+")  # one line: master merged into a branch


def commits(previous: str, head: str = "HEAD") -> list[tuple[str, str]]:
    """(title, description) per change on the first-parent line, newest first."""
    span = [f"{previous}..{head}"] if previous else [f"-{MAX_COMMITS}", head]
    result = []
    for sha, parents, title, description in _log("--first-parent", *span):
        merged = MERGE.match(title)
        if merged and len(parents) == 2:
            # "Merge pull request #N from ...": its body is only the pull request's title.
            for _, _, branch_title, branch_description in _log("--no-merges", f"{sha}^1..{sha}^2"):
                number = f" (#{merged[1]})" if "(#" not in branch_title else ""
                result.append((branch_title + number, branch_description))
        else:
            result.append((title, description))
    return [(title, description) for title, description in result if not RELEASE.match(title)]


def _log(*args: str) -> list[tuple[str, list[str], str, str]]:
    """(hash, parent hashes, title, description) per commit of `git log args`."""
    out = subprocess.run(
        ["git", "log", f"--format=%H %P%n%s%n%b{SEPARATOR}", *args],
        check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout
    result = []
    for chunk in out.split(SEPARATOR):
        lines = chunk.strip("\n").splitlines()
        if len(lines) < 2:
            continue
        sha, *parents = lines[0].split()
        title = lines[1].strip()
        body = [line for line in lines[2:] if not TRAILER.match(line)]
        # GitHub's default squash message lists the branch's commits as "* title" paragraphs, merges of
        # master into the branch among them; a squash message pasted with its title repeats it.
        paragraphs = [p.strip() for p in unwrap("\n".join(body)).split("\n\n")]
        paragraphs = [p for p in paragraphs if p and not BRANCH_SYNC.fullmatch(p)]
        if paragraphs and paragraphs[0].removeprefix("* ") == re.sub(r" \(#\d+\)$", "", title):
            paragraphs = paragraphs[1:]
        result.append((sha, parents, title, "\n\n".join(paragraphs)))
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
