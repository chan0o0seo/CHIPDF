"""Package existing converted weights as optional data, without model inference."""
import datetime
import hashlib
import json
from pathlib import Path
from uuid import uuid4
import zipfile

from studio.model_packs import PACK_FILES, PACK_FORMAT, origin_for
from studio.translation_config import MODEL_DIRECTORY, MODEL_ID, MODEL_REVISION

ROOT = Path(__file__).resolve().parent


def build():
    model = ROOT / "vendor" / MODEL_DIRECTORY
    origin_for(model)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:6]
    output = ROOT / "dist" / ("offline-pack-" + stamp)
    output.mkdir(parents=True)
    manifest = {"format": PACK_FORMAT, "model": MODEL_ID, "revision": MODEL_REVISION,
                "quantization": "int8", "files": {}}
    archive_path = output / "ChiPDF-M2M100-1.2B-Offline-Pack.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for name in PACK_FILES:
            path = model / name
            digest, length = hashlib.sha256(), 0
            print("Packing " + name, flush=True)
            with path.open("rb") as source, archive.open(name, "w", force_zip64=True) as target:
                while chunk := source.read(4 * 1024 * 1024):
                    target.write(chunk)
                    digest.update(chunk)
                    length += len(chunk)
            manifest["files"][name] = {"bytes": length, "sha256": digest.hexdigest()}
        archive.writestr("pack.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    sha = hashlib.sha256()
    with archive_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            sha.update(chunk)
    record = {"zip": str(archive_path), "bytes": archive_path.stat().st_size, "sha256": sha.hexdigest(),
              "model": MODEL_ID, "revision": MODEL_REVISION, "unpacked_bytes": sum(row["bytes"] for row in manifest["files"].values())}
    (output / "pack-release.json").write_text(json.dumps(record, indent=2), "utf-8")
    (output / "SHA256SUMS.txt").write_text(sha.hexdigest() + "  " + archive_path.name + "\n", "utf-8")
    (ROOT / "latest-model-pack.json").write_text(json.dumps(record, indent=2), "utf-8")
    print("MODEL_PACK_RESULT=" + json.dumps(record), flush=True)


if __name__ == "__main__":
    build()
