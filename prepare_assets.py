"""Build-time public asset preparation; never used by the installed application."""
from pathlib import Path
import argparse
import hashlib
import json
import urllib.request

from studio.translation_config import MODEL_DIRECTORY, MODEL_ID, MODEL_REVISION

ROOT = Path(__file__).resolve().parent
vendor = ROOT / "vendor"
model = vendor / MODEL_DIRECTORY
parser = argparse.ArgumentParser(description="OCR 자료와 선택 오프라인 모델의 배포 출처 준비")
parser.add_argument("--offline-model", action="store_true")
args = parser.parse_args()
origin = None
if args.offline_model:
    origin = json.loads((model / "origin.json").read_text("utf-8"))
    if (origin.get("model") != MODEL_ID or origin.get("revision") != MODEL_REVISION
            or origin.get("quantization") != "int8"):
        raise ValueError("Prepared translation model does not match the configured official model revision.")
    for name in ("model.bin", "config.json", "shared_vocabulary.json", "sentencepiece.bpe.model"):
        if not (model / name).is_file() or (model / name).stat().st_size == 0:
            raise ValueError("Prepared translation model is incomplete: " + name)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
                    "sha256": sha256_file(target)})
for name in ("jpn", "jpn_vert"):
    url = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/{name}.traineddata"
    target = vendor / "tessdata" / (name + ".traineddata")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Translation upgrades preserve the installed OCR assets byte for byte.
    if not target.exists():
        with urllib.request.urlopen(url, timeout=60) as response:
            target.write_bytes(response.read())
    records.append({"file": str(target.relative_to(vendor)), "url": url, "bytes": target.stat().st_size,
                    "sha256": sha256_file(target)})
if args.offline_model:
    card = model / "MODEL_CARD.md"
    card_url = f"https://huggingface.co/{origin['model']}/raw/{origin['revision']}/README.md"
    with urllib.request.urlopen(card_url, timeout=60) as response:
        card.write_bytes(response.read())
    (model / "LICENSE.txt").write_bytes((notices / "M2M100-MIT.txt").read_bytes())
    for path in model.iterdir():
        if path.is_file():
            record = {"file": str(path.relative_to(vendor)), "bytes": path.stat().st_size,
                      "sha256": sha256_file(path)}
            if path == card:
                record["url"] = card_url
            records.append(record)
(notices / "asset-origins.json").write_text(json.dumps({"model": origin, "assets": records}, indent=2), "utf-8")
print("Public model assets and license notices prepared.")
