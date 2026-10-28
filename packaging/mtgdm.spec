# PyInstaller spec for the desktop app: "MTG Deck Manager.app" on macOS, a folder with
# "MTG Deck Manager.exe" on Windows. Build with scripts/build_macos.sh or scripts/build_windows.ps1.
# -*- mode: python ; coding: utf-8 -*-
import os
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
LICENSES = ROOT / "build" / "licenses"
if not (LICENSES / "README.txt").is_file():
    raise SystemExit("build/licenses missing: run scripts/collect_licenses.py (the build scripts do)")
BACKEND = ROOT / "backend"
VERSION = re.search(r'__version__ = "([^"]+)"', (BACKEND / "mtgdm" / "__init__.py").read_text(encoding="utf-8")).group(1)
APP_NAME = "MTG Deck Manager"
MACOS = sys.platform == "darwin"
# RapidOCR is the Windows/Linux engine; MTGDM_BUNDLE_RAPIDOCR=1 bundles it on macOS too (testing).
RAPIDOCR = not MACOS or os.environ.get("MTGDM_BUNDLE_RAPIDOCR") == "1"


def windows_version_info():
    """The exe's version resource (Properties → Details). Code signing checks the product name and
    version (SignPath's artifact configuration, packaging/signpath/), so they must be set."""
    # Needs pefile, which PyInstaller installs on Windows only.
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    numbers = tuple(int(n) for n in re.findall(r"\d+", VERSION)[:4])
    numbers += (0,) * (4 - len(numbers))
    strings = {
        "CompanyName": "Wojciech Jaros",
        "FileDescription": APP_NAME,
        "FileVersion": VERSION,
        "InternalName": "mtgdm",
        "LegalCopyright": "Copyright © 2026 Wojciech Jaros. GPL-3.0-or-later.",
        "OriginalFilename": f"{APP_NAME}.exe",
        "ProductName": APP_NAME,
        "ProductVersion": VERSION,
    }
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            StringFileInfo([StringTable("040904B0", [StringStruct(k, v) for k, v in strings.items()])]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )


a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(BACKEND)],
    datas=[
        # Resource layout must match mtgdm/config.py (FROZEN branch).
        (str(ROOT / "frontend" / "dist"), "frontend"),
        (str(ROOT / "seeds"), "seeds"),
        # GPL: the license and the third-party notices travel with the binaries, and so do the license
        # texts of every bundled component (scripts/collect_licenses.py, run by the build scripts).
        (str(ROOT / "LICENSE"), "."),
        (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
        (str(LICENSES), "licenses"),
        (str(BACKEND / "mtgdm" / "db" / "migrations" / "*.sql"), "mtgdm/db/migrations"),
        # RapidOCR models (onnx) and its yaml configs live inside the package (Windows only).
        *(collect_data_files("rapidocr") if RAPIDOCR else []),
    ],
    # uvicorn picks its loop/protocol implementations at runtime; OCR engines are imported lazily.
    hiddenimports=[
        *collect_submodules("uvicorn"),
        *collect_submodules("mtgdm.scan"),
        # Only the ONNX Runtime engine: the PyTorch / TensorRT / Paddle / OpenVINO / MNN ones are never used.
        *(collect_submodules("rapidocr", filter=lambda name: not any(
            f".inference_engine.{engine}" in name for engine in ("pytorch", "tensorrt", "paddle", "openvino", "mnn")
        )) if RAPIDOCR else []),
        *(["Vision"] if MACOS else []),
    ],
    excludes=[
        "tkinter", "pytest", "IPython", "unittest",
        # Pulled in by optional imports, unused by the app: httpx CLI (pygments), uvicorn extras for
        # websockets / auto-reload / .env files, build tooling.
        "pygments", "websockets", "watchfiles", "dotenv",
        # PyYAML: only RapidOCR needs it (its config via omegaconf).
        *([] if RAPIDOCR else ["yaml"]),
        "setuptools", "pkg_resources", "_distutils_hack",
        # macOS uses Apple Vision for OCR: RapidOCR and onnxruntime would add ~100 MB.
        *([] if RAPIDOCR else ["rapidocr", "onnxruntime", "shapely", "pyclipper"]),
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    # On Windows the exe name is what users see in the folder and the taskbar.
    name="mtgdm" if MACOS else APP_NAME,
    console=False,
    argv_emulation=False,
    codesign_identity=None,
    icon=str(ROOT / "packaging" / ("icon.icns" if MACOS else "icon.ico")),
    version=None if MACOS else windows_version_info(),
)
coll = COLLECT(exe, a.binaries, a.datas, name="mtgdm" if MACOS else APP_NAME)

if MACOS:
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=str(ROOT / "packaging" / "icon.icns"),
        bundle_identifier="com.mtgdeckmanager.app",
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "LSApplicationCategoryType": "public.app-category.card-games",
        },
    )
