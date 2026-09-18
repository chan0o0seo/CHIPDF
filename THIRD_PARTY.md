# Runtime components — 0.11.0

Python, Qt, OCR, PDF and small translation runtime libraries are bundled in the portable directory. The default lightweight edition omits M2M100 weights. Offline translation is an optional data pack; existing compatible model folders can also be connected. Installed package license/notice files and additional model/native notices are copied into `licenses`. No user documents or system fonts are included. The editor uses the system font. ReportLab includes its own support assets; associated font notices are also copied into `licenses/reportlab-support`.

- Python: https://www.python.org/ — PSF license and bundled component notices.
- PySide6 Essentials / Shiboken6 6.10.2: https://www.qt.io/qt-for-python — see the bundled license texts and https://code.qt.io/cgit/pyside/pyside-setup.git/ for source.
- Qt 6.10.2: https://code.qt.io/cgit/qt/ — source archives: https://download.qt.io/archive/qt/6.10/6.10.2/
- PyInstaller 6.16.0 is used to package the app: https://pyinstaller.org/ . Its bootloader distribution exception is described at https://pyinstaller.org/en/stable/license.html .

| Added component | Source / notices |
|---|---|
| Pillow 12.3.0 | https://github.com/python-pillow/Pillow — HPND and bundled codec notices |
| tesserocr 2.10.0 | https://github.com/sirfz/tesserocr — MIT |
| Windows OCR binaries | https://github.com/simonflueckiger/tesserocr-windows_build/releases/tag/tesserocr-v2.10.0-tesseract-5.5.2 |
| Tesseract 5.5.2 | https://github.com/tesseract-ocr/tesseract/tree/5.5.2 — Apache 2.0 |
| Leptonica 1.87.0 | https://github.com/DanBloomberg/leptonica/tree/1.87.0 — BSD-style license |
| cysignals (vendored by the OCR wheel) | https://github.com/sagemath/cysignals — LGPL 3 |
| CTranslate2 4.6.2 | https://github.com/OpenNMT/CTranslate2/tree/v4.6.2 — MIT and bundled native component notices |
| SentencePiece 0.2.1 | https://github.com/google/sentencepiece — Apache 2.0 |
| NumPy 2.5.3 | https://github.com/numpy/numpy — BSD and bundled native component notices |
| PyYAML 6.0.3 | https://github.com/yaml/pyyaml — MIT |
| pypdfium2 5.13.0 / PDFium | https://github.com/pypdfium2-team/pypdfium2 — wrapper and bundled Windows PDFium notices are in `licenses/pypdfium2-5.13.0.dist-info/licenses` including `BUILD_LICENSES` |
| pypdf 6.10.0 | https://github.com/py-pdf/pypdf — included BSD license in `licenses/pypdf-6.10.0.dist-info/licenses` |
| ReportLab 4.4.9 | https://hg.reportlab.com/hg-public/reportlab/ — included package license |
| charset-normalizer 3.5.1 | https://github.com/jawah/charset_normalizer — included package license |
| Inno Setup 7.1.0 (installer only) | https://jrsoftware.org/ — Copyright (C) 1997–2026 Jordan Russell; portions Copyright (C) 2000–2026 Martijn Laan. Installer license is included at `licenses/Inno-Setup-LICENSE.txt`. The compiler is a development tool and is not installed with Translation Studio. |
| Japanese OCR models | https://github.com/tesseract-ocr/tessdata_fast — Apache 2.0, jpn and jpn_vert |
| M2M100 1.2B model | https://huggingface.co/facebook/m2m100_1.2B — MIT; official revision `7b36184180524c1a1bbfa37f120a608046250b98` recorded in bundled origin.json, locally converted to CTranslate2 int8 |

The Windows OCR wheel also supplies zlib, zstd, libpng, libjpeg, libtiff, giflib, OpenJPEG, WebP and xz shared libraries. Their upstream sources are linked from the Windows build project. Qt and Pillow also supply image codec notices in their package license folders.

PyTorch and Transformers are used only to convert public model weights and are not bundled. Older Argos experiments and M2M100 418M weights are not bundled.

Public asset preparation records are included in `licenses/models-and-native/asset-origins.json`; those development records may describe optional assets not shipped in the lightweight edition. The optional pack contains the model card, MIT license, origin.json and file SHA-256 metadata. The small CTranslate2 and SentencePiece runtimes remain bundled so installing a data-only offline pack does not require downloading executable code. The optional M2M100 model performs inference on the CPU.

The default translation provider is the Translator API in the user's separately installed Google Chrome. Chrome and its language packs are not redistributed with this application. The app sends text only to its authenticated loopback helper page; Chrome's on-device Translator API handles inference. Chrome installation and language-pack downloads are managed separately by Chrome.

The larger model requires more disk space and memory than the previous 418M model and may translate more slowly. Version 0.9.1 was prepared without tests, benchmarks or sample translations at the user's request; no measured quality or speed improvement is claimed.
