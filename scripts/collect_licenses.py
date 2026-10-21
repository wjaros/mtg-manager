#!/usr/bin/env python3
"""Collect the license texts of everything the app bundle ships into one folder.

MIT, BSD, Apache, MPL and PSF licenses require their text to travel with binary copies. The
bundle includes the Python runtime, the Python packages mtgdm depends on (on this platform), the
PyInstaller bootloader, the minimal OpenCV build with its third-party parts, and the frontend's
npm packages.

    cd backend && uv run python ../scripts/collect_licenses.py [OPENCV_DIR]

OPENCV_DIR is the directory printed by build_opencv.py (its licenses/ folder is copied).
Writes build/licenses/ and prints its path.
"""

import json
import re
import shutil
import sys
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "licenses"
LICENSE_FILE = re.compile(r"(^|/)(LICEN[CS]E|COPYING|NOTICE|AUTHORS)[^/]*$", re.IGNORECASE)
# Not license texts although named like one (pyobjc's test module PyObjCTest/copying.cpython-312-darwin.so).
NOT_LICENSE = re.compile(r"\.(so|pyd|dylib|dll|py|pyc|yml|plist)$|\.dSYM/", re.IGNORECASE)
# PEP 639 / REUSE: everything under a licenses folder (e.g. pypdfium2's PDFium build licenses).
LICENSE_DIR = re.compile(r"(^|/)(LICENSES|BUILD_LICENSES)/", re.IGNORECASE)
# Bundled although not a runtime dependency of mtgdm: the executable's bootloader.
EXTRA = ["pyinstaller"]


def main() -> int:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    index = ["Licenses of the third-party software bundled with MTG Deck Manager.", ""]

    runtime = python_license()
    shutil.copy(runtime, OUT / "Python-LICENSE.txt")
    index.append(f"Python {sys.version.split()[0]}: Python-LICENSE.txt")

    missing = []
    for dist in python_distributions():
        name = f"{dist.metadata['Name']}-{dist.version}"
        files = [
            f for f in dist.files or []
            if (LICENSE_FILE.search(str(f)) or LICENSE_DIR.search(str(f))) and not NOT_LICENSE.search(str(f))
        ]
        target = OUT / "python" / name
        for f in files:
            # Keep the path below a licenses folder (pypdfium2 has one file per bundled library).
            relative = str(f).split("/licenses/", 1)[-1] if "/licenses/" in str(f) else Path(str(f)).name
            dest = target / relative
            if dest.exists():  # several files with the same name (e.g. vendored code)
                dest = target / str(f).replace("/", "_")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(dist.locate_file(f), dest)
        license_name = dist.metadata.get("License-Expression") or (dist.metadata.get("License") or "").split("\n")[0]
        if not files:
            missing.append(name)
            target.mkdir(parents=True, exist_ok=True)
            (target / "LICENSE-INFO.txt").write_text(
                f"{name}: {license_name or 'see the project'}\n{dist.metadata.get('Home-page') or ''}\n", encoding="utf-8"
            )
        index.append(f"python/{name}: {license_name}")

    if len(sys.argv) > 1 and (Path(sys.argv[1]) / "licenses").is_dir():
        shutil.copytree(Path(sys.argv[1]) / "licenses", OUT, dirs_exist_ok=True)
        index.append("opencv/: OpenCV (Apache-2.0) and the third-party code built into it")

    for package_dir in npm_packages():
        meta = json.loads((package_dir / "package.json").read_text(encoding="utf-8"))
        target = OUT / "frontend" / f"{meta['name'].replace('/', '__')}-{meta['version']}"
        target.mkdir(parents=True, exist_ok=True)
        for f in package_dir.iterdir():
            if LICENSE_FILE.search(f.name):
                shutil.copy(f, target / f.name)
        index.append(f"frontend/{target.name}: {meta.get('license')}")

    (OUT / "README.txt").write_text("\n".join(index) + "\n", encoding="utf-8")
    if missing:
        print(f"no license file in: {', '.join(missing)} (metadata noted instead)", file=sys.stderr)
    print(OUT)
    return 0


def python_license() -> Path:
    base = Path(sys.base_prefix)
    for candidate in (base / "LICENSE.txt", base / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "LICENSE.txt"):
        if candidate.is_file():
            return candidate
    raise SystemExit(f"Python's LICENSE.txt not found under {base}")


def python_distributions() -> list[metadata.Distribution]:
    """mtgdm's dependency closure for this platform (markers evaluated), plus EXTRA."""
    seen: dict[str, metadata.Distribution] = {}
    # (requirement, the extra it was pulled in by: its marker is evaluated with that extra)
    queue = [(Requirement(r), "") for r in metadata.requires("mtgdm") or []] + [(Requirement(n), "") for n in EXTRA]
    expanded: set[tuple[str, str]] = set()
    while queue:
        req, extra = queue.pop()
        if req.marker and not req.marker.evaluate({"extra": extra}):
            continue
        key = req.name.lower().replace("_", "-")
        try:
            dist = seen.get(key) or metadata.distribution(req.name)
        except metadata.PackageNotFoundError:
            continue  # optional on this platform
        seen[key] = dist
        # A package's dependencies once, plus those of each extra asked for (uvicorn[standard]).
        for wanted in {""} | set(req.extras):
            if (key, wanted) in expanded:
                continue
            expanded.add((key, wanted))
            queue += [(Requirement(r), wanted) for r in dist.requires or []]
    return sorted(seen.values(), key=lambda d: d.metadata["Name"].lower())


def npm_packages() -> list[Path]:
    """The frontend's production dependencies (they end up in the built JavaScript)."""
    modules = ROOT / "frontend" / "node_modules"
    root = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    queue, seen = list(root.get("dependencies", {})), {}
    while queue:
        name = queue.pop()
        if name in seen or not (modules / name / "package.json").is_file():
            continue
        seen[name] = modules / name
        meta = json.loads((modules / name / "package.json").read_text(encoding="utf-8"))
        queue += list(meta.get("dependencies", {}))
    return [seen[n] for n in sorted(seen)]


if __name__ == "__main__":
    sys.exit(main())
