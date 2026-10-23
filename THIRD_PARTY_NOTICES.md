# Third-party notices

Copyright © 2026 Wojciech Jaros. MTG Deck Manager is licensed under the GNU General Public License
v3.0 or later (see `LICENSE`).
The app bundles or uses the components below under their own licenses. Their full license texts
ship inside the app in the `licenses` folder (collected at build time by
`scripts/collect_licenses.py`; an index is in `licenses/README.txt`).

## Data and images

- **Card data and images**: [Scryfall](https://scryfall.com), used under the
  [Scryfall API guidelines](https://scryfall.com/docs/api): cached locally, never altered.
  This project is not produced by or endorsed by Scryfall.
- **Preconstructed deck lists**: [MTGJSON](https://mtgjson.com), downloaded with the card data,
  MIT License, Copyright (c) 2018–present Zach Halpern: "Permission is hereby granted, free of charge,
  to any person obtaining a copy of this software and associated documentation files (the
  "Software"), to deal in the Software without restriction, including without limitation the rights
  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
  and to permit persons to whom the Software is furnished to do so, subject to the following
  conditions: The above copyright notice and this permission notice shall be included in all copies
  or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
  KIND, EXPRESS OR IMPLIED." (full text: https://mtgjson.com/license/)
- **Magic: The Gathering**: card names, text, symbols and images are property of
  Wizards of the Coast LLC. MTG Deck Manager is unofficial Fan Content permitted under the
  [Fan Content Policy](https://company.wizards.com/en/legal/fancontentpolicy); not approved or
  endorsed by Wizards. ©Wizards of the Coast LLC.
- **Test fixtures** (`backend/tests/fixtures/`): a small subset of Scryfall card data and card
  images, and of MTGJSON deck files, used only to test the app offline.

## Bundled software (desktop app)

| Component | License |
|---|---|
| Python | PSF-2.0 |
| OpenCV (minimal build: core, imgproc, imgcodecs; with libjpeg-turbo, libpng, zlib, KleidiCV / IPP) | Apache-2.0 (bundled libraries: BSD-style, IJG, libpng, zlib, Apache-2.0) |
| NumPy | BSD-3-Clause (and bundled BSD/MIT/zlib parts) |
| Pillow | MIT-CMU (HPND) |
| pypdfium2, PDFium | Apache-2.0 / BSD-3-Clause |
| ReportLab (proxy printing), charset-normalizer | BSD-3-Clause, MIT |
| FastAPI | MIT |
| Starlette | BSD-3-Clause |
| Uvicorn | BSD-3-Clause |
| uvloop | MIT / Apache-2.0 |
| httptools, h11, AnyIO | MIT |
| HTTPX, HTTPCore, idna | BSD-3-Clause |
| Pydantic, pydantic-core, annotated-types | MIT |
| python-multipart | Apache-2.0 |
| ijson | BSD-3-Clause, ISC |
| RapidFuzz | MIT |
| platformdirs | MIT |
| pywebview, proxy_tools, bottle | BSD-3-Clause, MIT |
| certifi | MPL-2.0 |
| typing_extensions | PSF-2.0 |
| PyObjC (macOS: Vision, Quartz) | MIT |
| RapidOCR (Windows), its OCR models | Apache-2.0 |
| ONNX Runtime (Windows) | MIT |
| Shapely, OmegaConf (Windows) | BSD-3-Clause |
| pyclipper, PyYAML, colorlog, six (Windows) | MIT |
| tqdm (Windows) | MPL-2.0 and MIT |
| requests (Windows) | Apache-2.0 |
| PyInstaller bootloader | GPL-2.0-or-later with the bootloader exception |
| React, React DOM, TanStack Virtual (frontend) | MIT |

Source code of the bundled components is available from their projects (PyPI and npm list the
exact versions in `licenses/README.txt`); this includes the MPL-2.0 licensed certifi and tqdm. The
app's own source code is at https://github.com/wjaros/mtg-manager.

On macOS the app uses the system's Vision framework (OCR) and ImageIO (HEIC photos); they are part
of macOS and not bundled.
