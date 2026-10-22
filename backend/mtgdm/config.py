"""Paths and runtime settings."""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path

from mtgdm import APP_NAME

FROZEN = getattr(sys, "frozen", False)  # running from a PyInstaller bundle (.app / .exe)

if FROZEN:
    # Bundle layout, see packaging/mtgdm.spec.
    _RESOURCES = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    _DEFAULT_FRONTEND_DIST = _RESOURCES / "frontend"
    _DEFAULT_SEEDS_DIR = _RESOURCES / "seeds"
else:
    # Repo layout: backend/mtgdm/config.py -> <repo>/frontend/dist, <repo>/seeds
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    _DEFAULT_FRONTEND_DIST = _REPO_ROOT / "frontend" / "dist"
    _DEFAULT_SEEDS_DIR = _REPO_ROOT / "seeds"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    frontend_dist: Path
    seeds_dir: Path = _DEFAULT_SEEDS_DIR

    @property
    def db_path(self) -> Path:
        return self.data_dir / "db.sqlite"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def scans_dir(self) -> Path:
        return self.data_dir / "scans"

    @property
    def bulk_dir(self) -> Path:
        return self.data_dir / "bulk"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def print_dir(self) -> Path:
        """Proxy PDFs being built or waiting for download (temporary)."""
        return self.data_dir / "print"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.images_dir, self.scans_dir, self.bulk_dir):
            path.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    """Build settings from defaults, overridable via MTGDM_DATA_DIR / MTGDM_FRONTEND_DIST / MTGDM_SEEDS_DIR."""
    data_dir = os.environ.get("MTGDM_DATA_DIR")
    frontend_dist = os.environ.get("MTGDM_FRONTEND_DIST")
    seeds_dir = os.environ.get("MTGDM_SEEDS_DIR")
    return Settings(
        # macOS: ~/Library/Application Support/MTGDeckManager, Windows: %APPDATA%\MTGDeckManager
        data_dir=Path(data_dir) if data_dir else user_data_path(APP_NAME, appauthor=False, roaming=True),
        frontend_dist=Path(frontend_dist) if frontend_dist else _DEFAULT_FRONTEND_DIST,
        seeds_dir=Path(seeds_dir) if seeds_dir else _DEFAULT_SEEDS_DIR,
    )
