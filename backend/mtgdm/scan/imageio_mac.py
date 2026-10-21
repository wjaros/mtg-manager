"""HEIC/HEIF (iPhone photos) on macOS through the system's ImageIO, instead of bundling libheif."""

import numpy as np
import Quartz
from Foundation import NSData


def decode(data: bytes, max_side: int) -> np.ndarray:
    """RGB pixels, EXIF orientation applied, longest side at most max_side. Raises ValueError."""
    source = Quartz.CGImageSourceCreateWithData(NSData.dataWithBytes_length_(data, len(data)), None)
    if source is None or Quartz.CGImageSourceGetCount(source) == 0:
        raise ValueError("ImageIO cannot read this file")
    options = {
        Quartz.kCGImageSourceCreateThumbnailFromImageAlways: True,
        Quartz.kCGImageSourceCreateThumbnailWithTransform: True,  # EXIF orientation
        Quartz.kCGImageSourceThumbnailMaxPixelSize: max_side,
    }
    image = Quartz.CGImageSourceCreateThumbnailAtIndex(source, 0, options)
    if image is None:
        raise ValueError("ImageIO cannot decode this file")
    width, height = Quartz.CGImageGetWidth(image), Quartz.CGImageGetHeight(image)
    # Draw into a known pixel format (8-bit RGBX, sRGB) rather than trusting the source's.
    space = Quartz.CGColorSpaceCreateWithName(Quartz.kCGColorSpaceSRGB)
    context = Quartz.CGBitmapContextCreate(None, width, height, 8, width * 4, space, Quartz.kCGImageAlphaNoneSkipLast)
    Quartz.CGContextDrawImage(context, Quartz.CGRectMake(0, 0, width, height), image)
    bitmap = Quartz.CGBitmapContextCreateImage(context)
    row = Quartz.CGImageGetBytesPerRow(bitmap)
    pixels = bytes(Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(bitmap)))
    return np.frombuffer(pixels, np.uint8).reshape(height, row)[:, : width * 4].reshape(height, width, 4)[:, :, :3].copy()
