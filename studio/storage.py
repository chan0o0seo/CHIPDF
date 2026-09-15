"""Self-contained project archive; atomic replacement and previous-save backup."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tempfile
import zipfile

from .model import Project


def required_assets(project: Project) -> set[str]:
    return {key for page in project.pages for key in (page.asset, page.clean_asset) if key}


def validate_asset_sizes(project: Project, assets: dict[str, bytes]):
    required = required_assets(project)
    if not required.issubset(assets) or any(not isinstance(assets[key], bytes) for key in required):
        raise ValueError("원본 또는 PDF 배경 자료가 없습니다.")
    if any(len(assets[key]) > 250_000_000 for key in required) or sum(len(assets[key]) for key in required) > 512_000_000:
        raise ValueError("원본과 PDF 배경은 파일당 250MB, 작품당 512MB까지 지원합니다.")


def atomic_write(path: Path, data: bytes):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".studio-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_project(path: Path, project: Project, original: bytes | dict[str, bytes]):
    Project.from_dict(project.to_dict())
    assets = {project.pages[0].asset: original} if isinstance(original, bytes) else original
    validate_asset_sizes(project, assets)
    required = required_assets(project)
    manifest = json.dumps(project.to_dict(), ensure_ascii=False, indent=2)
    if len(manifest.encode("utf-8")) > 64_000_000:
        raise ValueError("작업의 이미지와 편집 정보가 너무 큽니다. 삽입 이미지 크기를 줄여 주세요.")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", manifest)
        for key in sorted(required):
            archive.writestr(key, assets[key])
    path = Path(path)
    if path.exists():
        # Keep only a verified previous save. A bad file must not overwrite a good backup.
        try:
            load_project(path)
        except (ValueError, OSError, zipfile.BadZipFile):
            pass
        else:
            atomic_write(path.with_suffix(path.suffix + ".bak"), path.read_bytes())
    atomic_write(path, output.getvalue())


def load_bundle(path: Path) -> tuple[Project, dict[str, bytes]]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if not 2 <= len(names) <= 401 or len(set(names)) != len(names):
                raise ValueError("프로젝트 구성 파일이 올바르지 않습니다.")
            manifest = archive.getinfo("manifest.json")
            if manifest.file_size > 64_000_000:
                raise ValueError("프로젝트 편집 정보가 너무 큽니다.")
            project = Project.from_dict(json.loads(archive.read(manifest)))
            required = required_assets(project)
            if set(names) != required | {'manifest.json'}:
                raise ValueError("카드 원본 구성과 작업 정보가 일치하지 않습니다.")
            if any(archive.getinfo(key).file_size > 250_000_000 for key in required) or sum(archive.getinfo(key).file_size for key in required) > 512_000_000:
                raise ValueError("원본 자료가 너무 큽니다. 작품당 512MB까지 지원합니다.")
            return project, {key: archive.read(key) for key in required}
    except (KeyError, TypeError, AttributeError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise ValueError("올바른 치pdf 프로젝트가 아닙니다.") from exc


def load_project(path: Path):
    """Retain the single-asset caller contract; additional assets return a map."""
    project, assets = load_bundle(path)
    return project, assets[project.pages[0].asset] if len(assets) == 1 else assets
