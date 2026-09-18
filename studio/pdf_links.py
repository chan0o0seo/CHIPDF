"""Internal PDF links survive raster editing and follow translated text boxes."""
from copy import deepcopy
import ctypes
import math

from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QGraphicsRectItem

from .model import TextBox


def read_page_links(document, page, width, height):
    """Called while PDF_LOCK is held. PDFium handles CropBox and page rotation."""
    import pypdfium2.raw as raw
    position, handle = ctypes.c_int(), raw.FPDF_LINK()
    links = []
    while raw.FPDFLink_Enumerate(page, ctypes.byref(position), ctypes.byref(handle)):
        if position.value > 10000:
            raise ValueError('한 페이지의 PDF 링크가 너무 많습니다.')
        dest = raw.FPDFLink_GetDest(document, handle)
        if not dest:
            action = raw.FPDFLink_GetAction(handle)
            # Only a local GoTo action; never import remote files or scripts.
            if action and raw.FPDFAction_GetType(action) == raw.PDFACTION_GOTO:
                dest = raw.FPDFAction_GetDest(document, action)
        if not dest:
            continue
        target = raw.FPDFDest_GetDestPageIndex(document, dest)
        rect = raw.FS_RECTF()
        if not 0 <= target < len(document) or not raw.FPDFLink_GetAnnotRect(handle, ctypes.byref(rect)):
            continue
        if not all(math.isfinite(v) for v in (rect.left, rect.bottom, rect.right, rect.top)):
            continue
        points = []
        for px, py in ((rect.left, rect.bottom), (rect.right, rect.top)):
            x, y = ctypes.c_int(), ctypes.c_int()
            if not raw.FPDF_PageToDevice(page, 0, 0, width, height, 0, px, py, ctypes.byref(x), ctypes.byref(y)):
                break
            points.append((x.value, y.value))
        if len(points) != 2:
            continue
        x0, x1 = sorted(p[0] for p in points)
        y0, y1 = sorted(p[1] for p in points)
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(width, x1), min(height, y1)
        if x1 > x0 and y1 > y0:
            links.append({'rect': [x0, y0, x1-x0, y1-y0], 'page_index': target})
    return links


def link_owner(page, rect):
    """Use the original OCR selection, independent of the translated box location."""
    candidates = []
    area = rect.width()*rect.height()
    for obj in page.objects:
        if not isinstance(obj, TextBox) or not obj.source_rect:
            continue
        source = QRectF(*obj.source_rect)
        overlap = source.intersected(rect)
        covered = overlap.width()*overlap.height() if not overlap.isEmpty() else 0
        if area > 0 and covered/area >= .5:
            candidates.append((covered/area, -source.width()*source.height(), obj.id, obj))
    return max(candidates, key=lambda row: row[:3])[-1] if candidates else None


def export_links(page, included_ids):
    """Return clipped page-pixel hotspots. Absent destination pages are omitted."""
    items = {}
    for obj in page.objects:
        item = QGraphicsRectItem(0, 0, obj.width, obj.height)
        item.setPos(obj.x, obj.y)
        item.setTransformOriginPoint(obj.width/2, obj.height/2)
        item.setRotation(obj.rotation)
        item.setScale(obj.scale)
        item.setOpacity(obj.opacity)
        items[obj.id] = item
    for obj in page.objects:
        if obj.parent_id:
            items[obj.id].setParentItem(items[obj.parent_id])
    owners = [(link, link_owner(page, QRectF(*link['rect']))) for link in page.pdf_links]
    targets = {}
    for link, owner in owners:
        if owner:
            targets.setdefault(owner.id, set()).add(link['page_id'])
    results = []
    bounds = QRectF(0, 0, page.width, page.height)

    def add(rect, target):
        rect = rect.intersected(bounds)
        if target in included_ids and not rect.isEmpty():
            row = ([rect.x(), rect.y(), rect.width(), rect.height()], target)
            if row not in results:
                results.append(row)

    for link, owner in owners:
        original = QRectF(*link['rect'])
        if owner is None:
            add(original, link['page_id'])
            continue
        if owner.link_mode != 'auto':
            continue
        if not owner.text.strip():
            if not (owner.erase_enabled and owner.erase_when_empty):
                add(original, link['page_id'])
            continue
        item = items[owner.id]
        if item.effectiveOpacity() <= 0:
            continue
        local = QRectF(0, 0, owner.width, owner.height)
        if len(targets[owner.id]) > 1:
            # A box containing several destinations must not become one ambiguous link.
            source = QRectF(*owner.source_rect)
            part = original.intersected(source)
            local = QRectF((part.x()-source.x())/source.width()*owner.width,
                           (part.y()-source.y())/source.height()*owner.height,
                           part.width()/source.width()*owner.width,
                           part.height()/source.height()*owner.height)
        add(item.mapRectToScene(local), link['page_id'])
        if not owner.erase_enabled:
            add(original, link['page_id'])
    for obj in page.objects:
        if isinstance(obj, TextBox) and obj.link_mode == 'page' and obj.text.strip() and items[obj.id].effectiveOpacity() > 0:
            add(items[obj.id].mapRectToScene(QRectF(0, 0, obj.width, obj.height)), obj.link_page_id)
    return results


def prepare_link_repair(project, assets, paths, cancelled=None, progress=lambda value: None):
    from .document_io import import_files, check_cancel
    from .pdf_repair import pixel_key
    from .model import Project
    imported, incoming, _ = import_files(paths, cancelled, progress)
    originals, existing = {}, {}
    for page in imported.pages:
        originals.setdefault(pixel_key(incoming[page.asset]), []).append(page)
    for page in project.pages:
        existing.setdefault(pixel_key(assets[page.asset]), []).append(page)
    mapping = {}
    for key, pages in originals.items():
        if len(pages) == 1 and len(existing.get(key, [])) == 1:
            mapping[pages[0].id] = existing[key][0].id
    trial = deepcopy(project)
    by_id = {p.id: p for p in trial.pages}
    count = 0
    for source in imported.pages:
        check_cancel(cancelled)
        if source.id not in mapping:
            continue
        page = by_id[mapping[source.id]]
        for link in source.pdf_links:
            if link['page_id'] not in mapping:
                continue
            restored = {'rect': list(link['rect']), 'page_id': mapping[link['page_id']]}
            if restored not in page.pdf_links:
                page.pdf_links.append(restored)
                count += 1
    if not count:
        raise ValueError('복원할 새 링크를 찾지 못했습니다. 출발·도착 페이지가 원본 PDF와 일치해야 합니다. 이미 복원된 링크나 구분할 수 없는 동일한 페이지는 건너뜁니다.')
    Project.from_dict(trial.to_dict())
    check_cancel(cancelled)
    return trial, count
