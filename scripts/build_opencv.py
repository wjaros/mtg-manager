#!/usr/bin/env python3
"""Build a minimal OpenCV for the app bundle: only core, imgproc (+ geometry, flann) and
imgcodecs with JPEG and PNG.

The PyPI wheels carry ffmpeg, OpenEXR, AVIF, JPEG XL, X11, gnutls, ... (~120 MB on macOS);
the app needs none of it. Same OpenCV version as uv.lock, same speed (KleidiCV on arm64, IPP on
x86-64), ~15 MB. Development and tests keep using the PyPI wheel.

    cd backend && uv run python ../scripts/build_opencv.py     # prints the dir to put on PYTHONPATH

The result (cv2/ plus licenses/) is cached in build/opencv-slim/<version>-<platform>/ (delete it to rebuild).
Needs a C++ compiler (Xcode command line tools / Visual Studio); cmake and ninja come from uvx.
"""

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "opencv-python-headless"

MODULES = "core,imgproc,imgcodecs,python3"
COMMON_FLAGS = [
    "-DCMAKE_BUILD_TYPE=Release",
    f"-DBUILD_LIST={MODULES}",
    "-DBUILD_SHARED_LIBS=OFF",
    "-DBUILD_opencv_python3=ON",
    "-DBUILD_opencv_python2=OFF",
    "-DOPENCV_PYTHON3_INSTALL_PATH=python",
    # No video, no exotic image formats: JPEG and PNG (built in) are all the app reads and writes.
    *(f"-DWITH_{name}=OFF" for name in (
        "FFMPEG", "GSTREAMER", "AVFOUNDATION", "MSMF", "DSHOW", "OPENEXR", "AVIF", "TIFF", "WEBP", "OPENJPEG",
        "JASPER", "JPEGXL", "SPNG", "IMGCODEC_HDR", "IMGCODEC_SUNRASTER", "IMGCODEC_PXM", "IMGCODEC_PFM",
        "IMGCODEC_GIF", "OPENCL", "ITT", "PROTOBUF", "EIGEN", "LAPACK", "ADE", "OPENVX", "GTK", "QT", "WIN32UI",
    )),
    "-DWITH_JPEG=ON", "-DBUILD_JPEG=ON", "-DWITH_PNG=ON", "-DBUILD_PNG=ON", "-DBUILD_ZLIB=ON",
    *(f"-DBUILD_{name}=OFF" for name in ("TESTS", "PERF_TESTS", "EXAMPLES", "DOCS", "opencv_apps", "JAVA", "opencv_js")),
]


def main() -> int:
    version = locked_version()
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    # The speed-ups the PyPI wheels have: KleidiCV (Arm) and IPP (x86-64). Not IPP on Windows: the static
    # IPP libraries don't get linked into the Python module there (unresolved ippicv* symbols); OpenCV is
    # a small part of a scan's time next to OCR.
    ipp = not arm and sys.platform != "win32"
    flags = COMMON_FLAGS + [f"-DWITH_KLEIDICV={'ON' if arm else 'OFF'}", f"-DWITH_IPP={'ON' if ipp else 'OFF'}"]
    if sys.platform == "darwin":
        flags.append("-DCMAKE_OSX_DEPLOYMENT_TARGET=11.0")
    key = hashlib.sha256(json.dumps(flags).encode()).hexdigest()[:8]
    work = ROOT / "build" / "opencv-slim"
    out = work / f"{version}-{sys.platform}-{machine}-py{sys.version_info.major}{sys.version_info.minor}-{key}"
    if (out / "cv2" / "__init__.py").is_file() and (out / "licenses" / "opencv" / "LICENSE").is_file():
        if arm:
            kleidicv_license(work / f"src-{version}" / "opencv", out / "licenses" / "opencv")
        print(out)
        return 0

    source = fetch_source(version, work)
    build = work / "cmake-build"
    shutil.rmtree(build, ignore_errors=True)
    install = work / "cmake-install"
    shutil.rmtree(install, ignore_errors=True)
    import numpy

    cmake = ["uvx", "cmake"]
    generator = []
    if sys.platform != "win32":  # Windows: the default Visual Studio generator
        ninja = subprocess.run(["uvx", "--from", "ninja", "python", "-c",
                                "import ninja, os; print(os.path.join(ninja.BIN_DIR, 'ninja'))"],
                               check=True, capture_output=True, text=True).stdout.strip()
        generator = ["-G", "Ninja", f"-DCMAKE_MAKE_PROGRAM={ninja}"]
    run([*cmake, "-S", str(source), "-B", str(build), *generator, *flags,
         f"-DCMAKE_INSTALL_PREFIX={install}",
         f"-DPYTHON3_EXECUTABLE={sys.executable}",
         f"-DPYTHON3_NUMPY_INCLUDE_DIRS={numpy.get_include()}"])
    run([*cmake, "--build", str(build), "--config", "Release", "--parallel", str(os.cpu_count() or 4)])
    run([*cmake, "--install", str(build), "--config", "Release"])

    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    shutil.copytree(install / "python" / "cv2", out / "cv2")
    # Apache-2.0 (OpenCV, KleidiCV) and the bundled libjpeg-turbo, libpng, zlib, ... licenses must ship with
    # the binaries: OpenCV installs the licenses of exactly the components it built.
    licenses = out / "licenses" / "opencv"
    shutil.copytree(install / "share" / "licenses", licenses / "3rdparty", dirs_exist_ok=True)
    for name in ("LICENSE", "COPYRIGHT"):
        shutil.copy(source / name, licenses / name)
    if arm:
        kleidicv_license(source, licenses)
    shutil.rmtree(build, ignore_errors=True)
    shutil.rmtree(install, ignore_errors=True)
    print(out)
    return 0


def kleidicv_license(source: Path, licenses: Path) -> None:
    """KleidiCV (Apache-2.0) is downloaded by OpenCV's configure step and not installed with a license."""
    for archive in (source / ".cache" / "kleidicv").glob("*.tar.gz"):
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                parts = member.name.split("/")
                # REUSE layout: <top>/LICENSES/<SPDX id>.txt
                if member.isfile() and len(parts) == 3 and parts[1] == "LICENSES":
                    (licenses / "3rdparty" / f"kleidicv-{parts[2]}").write_bytes(tar.extractfile(member).read())


def locked_version() -> str:
    lock = (ROOT / "backend" / "uv.lock").read_text(encoding="utf-8")
    match = re.search(rf'name = "{PACKAGE}"\nversion = "([^"]+)"', lock)
    if not match:
        raise SystemExit(f"{PACKAGE} not found in uv.lock")
    return match.group(1)


def fetch_source(version: str, work: Path) -> Path:
    """The opencv-python sdist bundles the OpenCV sources of exactly that release."""
    source = work / f"src-{version}" / "opencv"
    if source.is_dir():
        return source
    with urllib.request.urlopen(f"https://pypi.org/pypi/{PACKAGE}/{version}/json") as resp:
        url = next(u["url"] for u in json.load(resp)["urls"] if u["packagetype"] == "sdist")
    archive = work / f"{PACKAGE}-{version}.tar.gz"
    work.mkdir(parents=True, exist_ok=True)
    print(f"downloading {url}", file=sys.stderr)
    urllib.request.urlretrieve(url, archive)
    target = work / f"src-{version}"
    with tarfile.open(archive) as tar:
        top = tar.getnames()[0].split("/")[0]
        members = [m for m in tar.getmembers() if m.name.startswith(f"{top}/opencv/")]
        for m in members:
            m.name = m.name[len(top) + 1:]
        tar.extractall(target, members=members, filter="data")
    archive.unlink()
    return source


def run(command: list[str]) -> None:
    # Build output goes to stderr: stdout carries only the result path.
    subprocess.run(command, check=True, stdout=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
