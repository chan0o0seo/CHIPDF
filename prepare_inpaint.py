"""Explicit build/developer preparation only. The app never downloads at inference."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / ".deps"), str(ROOT)]

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import urllib.request

from studio.inpaint_engine import MODEL_BYTES, MODEL_FILENAME, MODEL_REVISION, MODEL_SHA256, MODEL_URL


def verify_model(path):
    """Check the pinned public artifact before installation or redistribution."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size != MODEL_BYTES:
        raise ValueError(f"LaMa 모델 크기가 다릅니다. {MODEL_FILENAME} ({MODEL_BYTES:,} 바이트)가 필요합니다: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != MODEL_SHA256:
        raise ValueError("LaMa 모델 SHA256이 다릅니다. Carve/LaMa-ONNX의 고정 버전을 다시 받아 주세요.")
    return {"model": "Carve/LaMa-ONNX", "filename": MODEL_FILENAME,
            "revision": MODEL_REVISION, "sha256": MODEL_SHA256,
            "bytes": MODEL_BYTES, "url": MODEL_URL, "license": "Apache-2.0"}


def main(argv=None):
    # Windows code pages may not encode a user's model directory.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description="LaMa 모델을 검증하고 앱의 로컬 모델 폴더에 준비합니다.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--download", action="store_true", help="고정된 공개 모델(약 208MB)을 다운로드")
    group.add_argument("--from-file", type=Path, help="이미 받은 lama_fp32.onnx 파일 사용")
    args = parser.parse_args(argv)
    destination = ROOT / "vendor/models/inpaint" / MODEL_FILENAME
    if destination.is_file() and not (args.download or args.from_file):
        origin = verify_model(destination)
    elif args.download or args.from_file:
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix="lama-", suffix=".part", dir=destination.parent)
        os.close(descriptor)
        temporary = Path(temporary)
        try:
            if args.from_file:
                print("로컬 LaMa 모델 검증 중…", flush=True)
                verify_model(args.from_file)
                shutil.copyfile(args.from_file, temporary)
            else:
                print("공개 LaMa 모델 다운로드 중… (208 MB)", flush=True)
                request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "TranslationStudio-LaMa-Setup"})
                with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as target:
                    shutil.copyfileobj(response, target, length=1024 * 1024)
            origin = verify_model(temporary)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    else:
        parser.error("--from-file 경로 또는 --download를 선택해 주세요.")
    (destination.parent / "origin.json").write_text(json.dumps(origin, indent=2) + "\n", encoding="utf-8")
    print(f"준비 완료: {destination}\n모델 크기와 SHA256 검증 완료. 추론은 실행하지 않았습니다.", flush=True)


if __name__ == "__main__":
    main()
