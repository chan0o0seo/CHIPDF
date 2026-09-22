"""Optional data-only offline packs, independent of the lightweight app install."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from uuid import uuid4
import zipfile

from .storage import atomic_write
from .platform_support import default_data_dir
from .translation_config import MODEL_DIRECTORY, MODEL_FILES, MODEL_ID, MODEL_REVISION

PACK_FILES = (*MODEL_FILES, "origin.json", "MODEL_CARD.md", "LICENSE.txt")
PACK_FORMAT = "chipdf-offline-model-1"
MAX_PACK_BYTES = 2_000_000_000


def origin_for(root):
    root = Path(root)
    origin_path = root / "origin.json"
    if not origin_path.is_file() or origin_path.stat().st_size > 8192:
        raise ValueError("선택한 폴더에 오프라인 모델 정보가 없습니다.")
    try:
        origin = json.loads(origin_path.read_text("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("오프라인 모델 정보를 읽을 수 없습니다.") from exc
    if not isinstance(origin, dict) or (origin.get("model"), origin.get("revision"), origin.get("quantization")) != (
            MODEL_ID, MODEL_REVISION, "int8"):
        raise ValueError("이 버전과 호환되는 M2M100 1.2B int8 모델이 아닙니다.")
    if not all((root / name).is_file() and (root / name).stat().st_size > 0 for name in MODEL_FILES):
        raise ValueError("오프라인 모델 파일이 빠져 있습니다. 팩을 다시 설치하거나 다른 폴더를 선택하세요.")
    return origin


def bundled_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "vendor" / MODEL_DIRECTORY


def selected_root(data_dir=None):
    data_dir = Path(data_dir) if data_dir else default_data_dir()
    config = data_dir / "offline-model.json"
    # An explicitly connected but unavailable drive must not silently switch models.
    if config.is_file():
        if config.stat().st_size > 32768:
            raise ValueError("오프라인 모델 연결 정보를 다시 설정해 주세요.")
        try:
            record = json.loads(config.read_text("utf-8"))
            value = record["path"]
            if not isinstance(value, str) or not value or not Path(value).is_absolute():
                raise ValueError()
            root = Path(value)
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise ValueError("오프라인 모델 연결 정보를 다시 설정해 주세요.") from exc
        origin_for(root)
        return root
    root = bundled_root()
    if root.is_dir():
        origin_for(root)
        return root
    raise ValueError("오프라인 팩이 없습니다. ‘번역 설정 → 오프라인 팩 설치’ 또는 ‘기존 모델 폴더 연결’을 사용하세요. Chrome 번역은 팩 없이 사용할 수 있습니다.")


def status(data_dir):
    try:
        root = selected_root(data_dir)
        return "사용 가능 · " + str(root)
    except (OSError, ValueError) as exc:
        return str(exc)


def connect_folder(folder, data_dir):
    root = Path(folder).resolve()
    origin_for(root)
    atomic_write(Path(data_dir) / "offline-model.json", json.dumps({
        "model": MODEL_ID, "revision": MODEL_REVISION, "path": str(root)
    }, ensure_ascii=False, indent=2).encode("utf-8"))
    return root


def install_pack(archive_path, data_dir, cancelled, progress):
    """Stream known filenames; no executable/code files or extractall calls."""
    from .document_io import Cancelled
    base = (Path(data_dir) / "offline-models").resolve()
    if not base.is_relative_to(Path(data_dir).resolve()):
        raise ValueError("오프라인 모델 저장 위치가 사용자 데이터 폴더 밖에 있습니다.")
    base.mkdir(parents=True, exist_ok=True)
    staging = base / (".install-" + uuid4().hex)
    destination = base / (MODEL_DIRECTORY + "-" + uuid4().hex[:12])
    staging.mkdir()
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or set(names) != {*PACK_FILES, "pack.json"}:
                raise ValueError("치pdf 오프라인 팩 ZIP 파일을 선택해 주세요.")
            if archive.getinfo("pack.json").file_size > 32768:
                raise ValueError("오프라인 팩 정보가 너무 큽니다.")
            manifest = json.loads(archive.read("pack.json"))
            if not isinstance(manifest, dict) or (manifest.get("format"), manifest.get("model"),
                    manifest.get("revision"), manifest.get("quantization")) != (PACK_FORMAT, MODEL_ID, MODEL_REVISION, "int8"):
                raise ValueError("이 앱과 호환되지 않는 오프라인 팩입니다.")
            records = manifest.get("files")
            if not isinstance(records, dict) or set(records) != set(PACK_FILES):
                raise ValueError("오프라인 팩의 파일 정보가 올바르지 않습니다.")
            total = sum(archive.getinfo(name).file_size for name in PACK_FILES)
            if not 0 < total <= MAX_PACK_BYTES:
                raise ValueError("오프라인 팩 크기가 허용 범위를 벗어납니다.")
            if shutil.disk_usage(base).free < total + 100_000_000:
                raise ValueError("오프라인 팩을 설치할 디스크 공간이 부족합니다. 약 1.4GB의 여유 공간을 확보해 주세요.")
            completed = 0
            for name in PACK_FILES:
                if cancelled.is_set():
                    raise Cancelled("오프라인 팩 설치를 중단했습니다.")
                record = records[name]
                info = archive.getinfo(name)
                if (not isinstance(record, dict) or record.get("bytes") != info.file_size or
                        not isinstance(record.get("sha256"), str) or
                        not re.fullmatch(r"[a-f0-9]{64}", record["sha256"]) or info.file_size <= 0):
                    raise ValueError("오프라인 팩 파일 정보가 올바르지 않습니다: " + name)
                digest = hashlib.sha256()
                progress(f"오프라인 팩 설치 · {round(completed / total * 100)}%")
                last_percent = -1
                with archive.open(name) as source, (staging / name).open("wb") as output:
                    while chunk := source.read(4 * 1024 * 1024):
                        if cancelled.is_set():
                            raise Cancelled("오프라인 팩 설치를 중단했습니다.")
                        output.write(chunk)
                        digest.update(chunk)
                        completed += len(chunk)
                        percent = round(completed / total * 100)
                        if percent != last_percent:
                            progress(f"오프라인 팩 설치 · {percent}%")
                            last_percent = percent
                if digest.hexdigest() != record["sha256"]:
                    raise ValueError("오프라인 팩 파일이 손상되었습니다. 다시 내려받아 주세요: " + name)
            origin_for(staging)
            if cancelled.is_set():
                raise Cancelled("오프라인 팩 설치를 중단했습니다.")
        staging.rename(destination)
        # Publish only after every file was completely copied. Old packs stay intact.
        connect_folder(destination, data_dir)
        return str(destination)
    except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("오프라인 팩을 읽지 못했습니다. 내려받기가 끝난 ZIP 파일을 선택해 주세요.") from exc
    finally:
        if staging.is_dir() and staging.resolve().is_relative_to(base) and staging.name.startswith(".install-"):
            shutil.rmtree(staging)
