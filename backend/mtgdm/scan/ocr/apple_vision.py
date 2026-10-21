"""macOS Vision framework OCR (VNRecognizeTextRequest, accurate level)."""

import cv2
import numpy as np
import Vision
from Foundation import NSData

from mtgdm.scan.ocr.base import OcrLine


class AppleVisionEngine:
    name = "apple_vision"

    def recognize(self, image: np.ndarray) -> list[OcrLine]:
        ok, png = cv2.imencode(".png", image)
        if not ok:
            return []
        data = NSData.dataWithBytes_length_(png.tobytes(), len(png))
        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        # Set codes and collector numbers are not words: no dictionary "correction".
        request.setUsesLanguageCorrection_(False)
        success, _error = handler.performRequests_error_([request], None)
        if not success:
            return []
        lines = []
        for obs in request.results() or []:
            candidate = obs.topCandidates_(1)[0]
            box = obs.boundingBox()  # normalized, origin bottom-left
            lines.append(OcrLine(
                text=str(candidate.string()),
                confidence=float(candidate.confidence()),
                x=box.origin.x,
                y=1 - box.origin.y - box.size.height,
                w=box.size.width,
                h=box.size.height,
            ))
        return sorted(lines, key=lambda line: (round(line.y, 3), line.x))
