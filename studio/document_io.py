"""Bounded local imports and snapshot-based PNG/PDF collection export."""
from copy import deepcopy
from contextlib import closing
from io import BytesIO
import math
import os
from pathlib import Path
import re
import tempfile
from threading import Lock
from types import SimpleNamespace

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QImage, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsScene

from .model import Page, Project, TextBox, GroupBox
from .storage import load_bundle, validate_asset_sizes

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp'}
PDF_LOCK = Lock()


class Cancelled(Exception):
    pass


def check_cancel(cancel):
    if cancel and cancel():
        raise Cancelled('중단됨 · 기존 작업과 출력은 유지됩니다')


def png_data(image):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer, 'PNG'):
        raise OSError('이미지 변환에 실패했습니다.')
    return bytes(data)


def folder_images(path):
    def natural(file):
        return [(0, int(part)) if part.isdigit() else (1, part.casefold()) for part in re.split(r'(\d+)', file.name)]
    files = sorted((p for p in Path(path).iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS), key=natural)
    if not files:
        raise ValueError('이 폴더에 PNG·JPG·BMP 이미지가 없습니다.')
    return files


def validate_bundle(project, assets):
    from .object_items import validate_images
    from .recognition import validate_patches
    Project.from_dict(project.to_dict())
    validate_asset_sizes(project, assets)
    for page in project.pages:
        validate_images(page)
        validate_patches(page)
        for key in (page.asset, page.clean_asset):
            if not key:
                continue
            image = QImage.fromData(assets[key], 'PNG')
            if image.isNull() or (image.width(), image.height()) != (page.width, page.height):
                raise ValueError('카드의 원본 또는 PDF 배경 이미지 크기가 일치하지 않습니다: '+page.name)


def import_files(paths, cancel=None, progress=lambda message: None):
    paths = [Path(p).resolve() for p in paths]
    if len(paths) == 1 and paths[0].is_dir():
        paths = folder_images(paths[0])
    if not paths or len(paths) > 200:
        raise ValueError('한 번에 자료 1~200개를 선택해 주세요.')
    if any(p.name.lower().endswith(('.twproj', '.twproj.bak')) for p in paths):
        if len(paths) != 1:
            raise ValueError('작업 파일은 하나씩 열어 주세요. 이미지·PDF는 함께 선택할 수 있습니다.')
        project, assets = load_bundle(paths[0])
        validate_bundle(project, assets)
        check_cancel(cancel)
        return project, assets, paths[0]
    pages, assets = [], {}
    total = 0
    def append(image, name, source, points=None, clean_data=None):
        nonlocal total
        check_cancel(cancel)
        if len(pages) >= 200:
            raise ValueError('한 작품에 최대 200장을 가져올 수 있습니다.')
        if not points:
            dpi_x, dpi_y = image.dotsPerMeterX()*.0254, image.dotsPerMeterY()*.0254
            dpi_x = dpi_x if 72 <= dpi_x <= 600 else 200
            dpi_y = dpi_y if 72 <= dpi_y <= 600 else dpi_x
            points = (image.width()*72/dpi_x, image.height()*72/dpi_y)
        page = Page(image.width(), image.height(), name=name, width_pt=points[0], height_pt=points[1], source_file=str(source))
        page.asset = 'assets/'+page.id+'.png'
        data = png_data(image)
        if len(data) > 250_000_000 or (clean_data and len(clean_data) > 250_000_000):
            raise ValueError('원본 또는 PDF 배경 이미지가 250MB를 넘습니다.')
        total += len(data) + (len(clean_data) if clean_data else 0)
        if total > 512_000_000:
            raise ValueError('작품 원본 용량이 512MB를 넘습니다. 자료를 나눠 가져와 주세요.')
        pages.append(page)
        assets[page.asset] = data
        if clean_data:
            page.clean_asset = f'assets/{page.id}_background.png'
            assets[page.clean_asset] = clean_data
        progress(f'자료 가져오는 중 · {len(pages)}장 · {name}')
    for path in paths:
        check_cancel(cancel)
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            size = reader.size()
            if not size.isValid() or max(size.width(), size.height()) > 16000 or size.width()*size.height() > 80_000_000:
                raise ValueError('이미지 크기를 확인해 주세요: '+path.name)
            image = reader.read()
            if image.isNull():
                raise ValueError('이미지를 읽지 못했습니다: '+path.name)
            append(image, path.name, path)
        elif path.suffix.lower() == '.pdf':
            import pypdfium2 as pdfium
            from .pdf_background import render_without_text
            # Every PDFium call and handle lifetime stays within this mutex.
            with PDF_LOCK:
                try:
                    document = pdfium.PdfDocument(path)
                except pdfium.PdfiumError as exc:
                    raise ValueError('PDF를 읽지 못했습니다. 암호 또는 파일 상태를 확인해 주세요: '+path.name) from exc
                with document:
                    textless_pdf = None
                    if not len(document) or len(pages)+len(document) > 200:
                        raise ValueError('PDF를 포함해 최대 200장까지 가져올 수 있습니다.')
                    for index in range(len(document)):
                        check_cancel(cancel)
                        with closing(document[index]) as pdf_page:
                            w, h = pdf_page.get_size()
                            if not all(math.isfinite(v) and 1 <= v <= 14400 for v in (w, h)):
                                raise ValueError('PDF 페이지 크기가 지원 범위를 벗어납니다.')
                            scale = min(200/72, 6000/max(w, h), math.sqrt(24_000_000/(w*h)))
                            with closing(pdf_page.render(scale=scale)) as bitmap:
                                stream = BytesIO()
                                bitmap.to_pil().save(stream, 'PNG')
                                image = QImage.fromData(stream.getvalue(), 'PNG')
                            clean_data = None
                            try:
                                cleaned = render_without_text(pdf_page, scale, cancelled=cancel)
                                if cleaned is None:
                                    from .pdf_text_stream import TextlessPdf
                                    from pypdf.errors import PdfReadError
                                    try:
                                        if textless_pdf is None:
                                            textless_pdf = TextlessPdf(path)
                                        if textless_pdf is not False:
                                            cleaned = textless_pdf.render(index, scale, cancelled=cancel)
                                    except (PdfReadError, NotImplementedError):
                                        # A PDFium-readable page must still open if
                                        # its stream cannot be safely rewritten.
                                        textless_pdf = False
                            except InterruptedError as exc:
                                raise Cancelled('중단됨 · 기존 작업과 출력은 유지됩니다') from exc
                            check_cancel(cancel)
                            if cleaned and cleaned[1] > 0:
                                clean_image = QImage.fromData(cleaned[0], 'PNG')
                                if clean_image.isNull() or clean_image.size() != image.size():
                                    raise ValueError('PDF 배경 이미지 크기가 원본과 일치하지 않습니다.')
                                if clean_image.convertToFormat(QImage.Format_RGBA8888) != image.convertToFormat(QImage.Format_RGBA8888):
                                    clean_data = cleaned[0]
                            append(image, f'{path.stem} · {index+1}', path, (w, h), clean_data)
        else:
            raise ValueError('지원하지 않는 자료입니다: '+path.name)
    project = Project(name=paths[0].stem if len(paths) == 1 else paths[0].parent.name, pages=pages)
    Project.from_dict(project.to_dict())
    return project, assets, None


def render_page(page, original):
    """Use the same item painters as the editor without switching its active page."""
    from .canvas import TextItem
    from .object_items import GroupItem, VisualItem
    from .recognition import restored_background
    scene = QGraphicsScene()
    scene.show_controls = False
    context = SimpleNamespace(changed=lambda: None)
    needs_restoration = page.background_patches or any(isinstance(o, TextBox) and (o.text.strip() or o.erase_when_empty) and o.erase_enabled and o.erase_patch for o in page.objects)
    background = QImage.fromData(restored_background(original, page.objects, page.background_patches), 'PNG') if needs_restoration else QImage.fromData(original, 'PNG')
    scene.addPixmap(QPixmap.fromImage(background)).setZValue(-1)
    items = {}
    for obj in page.objects:
        item = TextItem(obj, context) if isinstance(obj, TextBox) else GroupItem(obj, context) if isinstance(obj, GroupBox) else VisualItem(obj, context)
        scene.addItem(item)
        items[obj.id] = item
    for obj in page.objects:
        if obj.parent_id:
            items[obj.id].setParentItem(items[obj.parent_id])
    result = QImage(page.width, page.height, QImage.Format_ARGB32_Premultiplied)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
    try:
        scene.render(painter, QRectF(0, 0, page.width, page.height), QRectF(0, 0, page.width, page.height))
    finally:
        painter.end()
        scene.clear()
    return result


def export_collection(project, assets, indices, destination, kind, cancel=None, progress=lambda value: None):
    indices = sorted(set(indices))
    if not indices or any(i < 0 or i >= len(project.pages) for i in indices) or kind not in ('png', 'pdf'):
        raise ValueError('출력할 카드와 형식을 확인해 주세요.')
    destination = Path(destination).resolve()
    if kind == 'png' and destination.exists():
        raise ValueError('PNG 묶음은 새 폴더에 저장해 주세요.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    snapshot = [deepcopy(project.pages[i]) for i in indices]
    # Stage the entire batch next to its destination; cancellation never publishes half a batch.
    with tempfile.TemporaryDirectory(prefix='.studio-export-', dir=destination.parent) as temporary:
        stage = Path(temporary)
        folder = stage / 'cards'
        folder.mkdir()
        canvas = None
        if kind == 'pdf':
            from reportlab.pdfgen.canvas import Canvas
            from reportlab.lib.utils import ImageReader
            canvas = Canvas(str(stage / 'output.pdf'), pageCompression=1)
            canvas.setTitle(project.name)
        for count, (index, page) in enumerate(zip(indices, snapshot)):
            progress(count)
            check_cancel(cancel)
            image = render_page(page, assets[page.asset])
            data = png_data(image)
            if canvas:
                w, h = (page.width_pt, page.height_pt) if page.width_pt and page.height_pt else (page.width*72/200, page.height*72/200)
                canvas.setPageSize((w, h))
                canvas.drawImage(ImageReader(BytesIO(data)), 0, 0, w, h, mask='auto')
                canvas.showPage()
            else:
                name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', page.name).strip(' .')[:70] or '카드'
                (folder / f'{index+1:03d}_{name}.png').write_bytes(data)
        if canvas:
            canvas.save()
        progress(len(indices))
        check_cancel(cancel)
        os.replace(stage / 'output.pdf', destination) if canvas else os.rename(folder, destination)
    return destination
