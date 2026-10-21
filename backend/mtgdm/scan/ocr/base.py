"""OCR engine interface. Engines are created once and reused (model loading is slow)."""

import importlib.util
import sys
import threading
from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass
class OcrLine:
    text: str
    confidence: float
    # Box in relative image coordinates (0..1), origin top-left.
    x: float
    y: float
    w: float
    h: float

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


class OcrEngine(Protocol):
    name: str

    def recognize(self, image: np.ndarray) -> list[OcrLine]:
        """Text lines of a BGR image, top to bottom."""
        ...


_engines: dict[str, OcrEngine] = {}
_lock = threading.Lock()


def available_engines() -> list[str]:
    names = []
    if sys.platform == "darwin":
        try:
            import Vision  # noqa: F401

            names.append("apple_vision")
        except ImportError:
            pass
    # The macOS app bundle leaves RapidOCR out (Apple Vision is better and free of ~100 MB).
    if importlib.util.find_spec("rapidocr") is not None:
        names.append("rapidocr")
    return names


def default_engine_name() -> str:
    return available_engines()[0]


def get_engine(name: str | None = None) -> OcrEngine:
    name = name or default_engine_name()
    if name not in available_engines():
        raise ValueError(f"OCR engine not available: {name}")
    with _lock:
        if name not in _engines:
            if name == "apple_vision":
                from mtgdm.scan.ocr.apple_vision import AppleVisionEngine

                _engines[name] = AppleVisionEngine()
            else:
                from mtgdm.scan.ocr.rapid import RapidOcrEngine

                _engines[name] = RapidOcrEngine()
        return _engines[name]
