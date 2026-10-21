"""RapidOCR (PaddleOCR models on onnxruntime): Windows / Linux, also usable on macOS."""

import threading

import numpy as np

from mtgdm.scan.ocr.base import OcrLine


class RapidOcrEngine:
    name = "rapidocr"

    def __init__(self):
        from rapidocr import RapidOCR

        # Models ship inside the package (no download). One engine instance is not thread safe.
        self._engine = RapidOCR(params={"Global.log_level": "critical"})
        self._lock = threading.Lock()

    def recognize(self, image: np.ndarray) -> list[OcrLine]:
        h, w = image.shape[:2]
        with self._lock:
            result = self._engine(image)
        if result.boxes is None or result.txts is None:
            return []
        lines = []
        for box, text, score in zip(result.boxes, result.txts, result.scores):
            xs, ys = box[:, 0], box[:, 1]
            lines.append(OcrLine(
                text=str(text),
                confidence=float(score),
                x=float(xs.min()) / w,
                y=float(ys.min()) / h,
                w=float(xs.max() - xs.min()) / w,
                h=float(ys.max() - ys.min()) / h,
            ))
        return sorted(lines, key=lambda line: (round(line.y, 3), line.x))
