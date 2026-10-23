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
    sources = {}
    for page in imported.pages:
        check_cancel(cancelled)
        if not page.clean_asset:
            continue
        key = pixel_key(incoming[page.asset])
        sources.setdefault(key, []).append(page)
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
        # A unique visual match can also upgrade an older raster-only project.
        originals = sources.get(key, [])
        if len(originals) == 1 and originals[0].pdf_asset:
            source = originals[0]
            page.pdf_asset, page.pdf_page = source.pdf_asset, source.pdf_page
            merged[page.pdf_asset] = incoming[page.pdf_asset]
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
    positional = attach_by_position(trial, merged, imported, incoming)
    if not matched and not positional:
        raise ValueError('현재 작업의 원본과 일치하는 PDF 페이지를 찾지 못했습니다. 작업에 사용한 원본 PDF를 선택해 주세요.')
    validate_bundle(trial, merged)
    check_cancel(cancelled)
    return trial, merged, matched, changed, positional


def _ratio(page):
    width, height = (page.width_pt, page.height_pt) if page.width_pt and page.height_pt else (page.width, page.height)
    return width/height


def attach_by_position(trial, merged, imported, incoming):
    """Attach a source PDF page by page when pixels differ but the layout is the same.

    Pages edited outside the editor (resized or re-composited backgrounds)
    no longer match the PDF pixel for pixel. When exactly one selected PDF
    has as many pages as the work and every unattached page keeps the
    proportions of the source page at its position, link them in order and
    print at the source's page size. Backgrounds and erase data are kept:
    the export compares them with the source and adds only real changes.
    """
    groups = {}
    for page in imported.pages:
        groups.setdefault(page.source_file, []).append(page)
    candidates = [pages for pages in groups.values()
                  if len(pages) == len(trial.pages) and all(p.pdf_asset for p in pages)]
    if len(candidates) != 1:
        return 0
    sources = candidates[0]
    key = sources[0].pdf_asset
    pending = [(index, page) for index, page in enumerate(trial.pages) if not page.pdf_asset]
    # Pages already linked to this PDF must sit at their own position;
    # otherwise the work was reordered and position says nothing.
    if not pending or any(page.pdf_asset == key and page.pdf_page != index
                          for index, page in enumerate(trial.pages)):
        return 0
    if any(abs(_ratio(page)-_ratio(sources[index])) > .001 for index, page in pending):
        return 0
    for index, page in pending:
        source = sources[index]
        page.pdf_asset, page.pdf_page = source.pdf_asset, source.pdf_page
        page.width_pt, page.height_pt = source.width_pt, source.height_pt
    merged[key] = incoming[key]
    return len(pending)
