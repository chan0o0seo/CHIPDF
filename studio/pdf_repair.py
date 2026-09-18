"""Attach real PDF backgrounds to older projects without guessing page names."""
from copy import deepcopy
import hashlib
from io import BytesIO

from PIL import Image, ImageDraw

from .document_io import import_files, check_cancel, validate_bundle
from .model import TextBox
from .recognition import native_background_patch, _selected_rect


def pixel_key(data):
    with Image.open(BytesIO(data)) as image:
        return image.size, hashlib.sha256(image.convert('RGBA').tobytes()).digest()


def prepare_pdf_repair(project, assets, paths, cancelled=None, progress=lambda value: None):
    imported, incoming, _ = import_files(paths, cancelled, progress)
    candidates, ambiguous = {}, set()
    native_layers = {}
    for page in imported.pages:
        check_cancel(cancelled)
        if not page.clean_asset:
            continue
        key = pixel_key(incoming[page.asset])
        clean = incoming[page.clean_asset]
        if key in candidates and pixel_key(candidates[key]) != pixel_key(clean):
            ambiguous.add(key)
        candidates[key] = clean
        if key in native_layers and native_layers[key] != page.native_chars:
            native_layers[key] = []
        else:
            native_layers[key] = page.native_chars
    trial, merged = deepcopy(project), dict(assets)
    matched = changed = 0
    for page in trial.pages:
        check_cancel(cancelled)
        key = pixel_key(assets[page.asset])
        if key not in candidates or key in ambiguous:
            continue
        matched += 1
        clean = candidates[key]
        page.clean_asset = f'assets/{page.id}_background.png'
        merged[page.clean_asset] = clean
        characters = native_layers.get(key, [])
        if characters and sum(len(p.native_chars) for p in trial.pages if p.id != page.id) + len(characters) <= 200000:
            page.native_chars = deepcopy(characters)
        for obj in page.objects:
            if not isinstance(obj, TextBox) or not obj.source_rect:
                continue
            try:
                x, y, w, h = _selected_rect(obj.source_rect, (page.width, page.height))
            except ValueError:
                continue
            selection = Image.new('L', (page.width, page.height))
            ImageDraw.Draw(selection).rectangle((x, y, x+w-1, y+h-1), fill=255)
            native = native_background_patch(assets[page.asset], clean, selection, cancelled)
            if native:
                obj.erase_patch, obj.erase_mask, obj.erase_rect = native
                changed += 1
        progress(f'원래 PDF 배경 적용 준비 · {matched}장 · 원문 {changed}개')
    if not matched:
        raise ValueError('현재 작업의 원본과 일치하는 PDF 페이지를 찾지 못했습니다. 작업에 사용한 원본 PDF를 선택해 주세요.')
    validate_bundle(trial, merged)
    check_cancel(cancelled)
    return trial, merged, matched, changed
