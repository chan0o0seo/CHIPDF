"""Build-time public asset preparation; never used by the installed application."""
from pathlib import Path
import hashlib
import json
import urllib.request

ROOT = Path(__file__).resolve().parent
vendor = ROOT / "vendor"
notices = vendor / "notices"
notices.mkdir(parents=True, exist_ok=True)
sources = {
    "M2M100-MIT.txt": "https://raw.githubusercontent.com/facebookresearch/fairseq/main/LICENSE",
    "tessdata-Apache-2.0.txt": "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/LICENSE",
    "Tesseract-LICENSE.txt": "https://raw.githubusercontent.com/tesseract-ocr/tesseract/5.5.2/LICENSE",
    "Leptonica-LICENSE.txt": "https://raw.githubusercontent.com/DanBloomberg/leptonica/1.87.0/leptonica-license.txt",
    "cysignals-LICENSE.txt": "https://raw.githubusercontent.com/sagemath/cysignals/main/LICENSE",
}
records = []
for name, url in sources.items():
    target = notices / name
    if not target.exists():
        with urllib.request.urlopen(url, timeout=60) as response:
            target.write_bytes(response.read())
    records.append({"file": str(target.relative_to(vendor)), "url": url,
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
for name in ("jpn", "jpn_vert"):
    url = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/{name}.traineddata"
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    target = vendor / "tessdata" / (name + ".traineddata")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != data:
        raise ValueError("Existing OCR model differs from public asset: " + name)
    target.write_bytes(data)
    records.append({"file": str(target.relative_to(vendor)), "url": url, "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest()})
model = vendor / "m2m100-int8"
origin = json.loads((model / "origin.json").read_text("utf-8"))
card = model / "MODEL_CARD.md"
if not card.exists():
    url = f"https://huggingface.co/facebook/m2m100_418M/raw/{origin['revision']}/README.md"
    with urllib.request.urlopen(url, timeout=60) as response:
        card.write_bytes(response.read())
(model / "LICENSE.txt").write_bytes((notices / "M2M100-MIT.txt").read_bytes())
for path in model.iterdir():
    if path.is_file():
        records.append({"file": str(path.relative_to(vendor)), "bytes": path.stat().st_size,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
(notices / "asset-origins.json").write_text(json.dumps({"model": origin, "assets": records}, indent=2), "utf-8")
print("Public model assets and license notices prepared.")
