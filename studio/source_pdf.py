"""Keep native PDF pages and add only transparent, cropped edit layers.

This is visual editing, not redaction: covered source text remains in the PDF.
Image imports and projects without embedded PDFs use the raster export path.
"""
import hashlib
from copy import copy
from io import BytesIO
import math
from pathlib import Path


def readable_source(data):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    try:
        reader = PdfReader(BytesIO(data))
        return not reader.is_encrypted and 1 <= len(reader.pages) <= 200
    except (PdfReadError, ValueError, TypeError, KeyError, OverflowError, NotImplementedError):
        # PDFium may still render a file unsupported by the preserving writer.
        return False


def source_readers(pages, assets):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    readers = {}
    for page in pages:
        if not page.pdf_asset:
            continue
        key = page.pdf_asset
        if key not in readers:
            data = assets.get(key)
            if (not isinstance(data, bytes) or
                    key != 'assets/'+hashlib.sha256(data).hexdigest()+'.pdf'):
                raise ValueError('보관된 원본 PDF가 없거나 손상되었습니다.')
            try:
                reader = PdfReader(BytesIO(data))
                if reader.is_encrypted or not 1 <= len(reader.pages) <= 200:
                    raise ValueError('지원하지 않는 원본 PDF입니다.')
                readers[key] = reader
            except (PdfReadError, ValueError, TypeError, KeyError, OverflowError, NotImplementedError) as exc:
                raise ValueError('보관된 원본 PDF를 읽지 못했습니다.') from exc
        if not 0 <= page.pdf_page < len(readers[key].pages):
            raise ValueError('원본 PDF에 해당 페이지가 없습니다: '+page.name)
    return readers


def _page_size(page):
    return ((page.width_pt, page.height_pt) if page.width_pt and page.height_pt
            else (page.width*72/200, page.height*72/200))


_CELL = 16


def _edit_regions(alpha):
    """Yield (left, top, mask) per cluster of edits; touching edits share one image.

    Adjacent images show hairlines in some viewers, so a cluster is never split.
    Separate clusters are at least one empty cell apart and never share an edge.
    """
    import numpy as np
    painted = np.asarray(alpha) > 0
    h, w = painted.shape
    gh, gw = -(-h//_CELL), -(-w//_CELL)
    grid = np.zeros((gh*_CELL, gw*_CELL), bool)
    grid[:h, :w] = painted
    cells = grid.reshape(gh, _CELL, gw, _CELL).any(axis=(1, 3))
    labels = np.zeros(cells.shape, np.int32)
    count = 0
    for start in zip(*np.nonzero(cells)):
        if labels[start]:
            continue
        count += 1
        labels[start] = count
        stack = [start]
        while stack:
            y, x = stack.pop()
            for ny in range(max(y-1, 0), min(y+2, gh)):
                for nx in range(max(x-1, 0), min(x+2, gw)):
                    if cells[ny, nx] and not labels[ny, nx]:
                        labels[ny, nx] = count
                        stack.append((ny, nx))
    for label in range(1, count+1):
        ys, xs = np.nonzero(labels == label)
        own = labels[ys.min():ys.max()+1, xs.min():xs.max()+1] == label
        yield int(xs.min())*_CELL, int(ys.min())*_CELL, np.kron(own, np.ones((_CELL, _CELL), bool))


def _page_image(data):
    """Full-page raster as JPEG when it is clearly smaller (photos), else lossless PNG."""
    from PIL import Image
    with Image.open(BytesIO(data)) as decoded:
        if decoded.mode in ('RGBA', 'LA') and decoded.getchannel('A').getextrema()[0] < 255:
            return data
        jpeg = BytesIO()
        decoded.convert('RGB').save(jpeg, 'JPEG', quality=92, subsampling=0, optimize=True)
    return jpeg.getvalue() if jpeg.tell() < len(data)*.75 else data


def _changed_pixels(layer, original):
    """Clear overlay pixels that only repeat the source page bitmap.

    Viewers resample overlay images, so a raster copy of an untouched source
    line lands beside the native vector line and reads as a thin double edge.
    Transparent pixels take the source colour so smoothing cannot pull in black.
    """
    import numpy as np
    from PIL import Image, ImageFilter
    with Image.open(BytesIO(original)) as decoded:
        base = decoded.convert('RGBA')
    if base.size != layer.size:
        return layer
    composite = Image.alpha_composite(base, layer)
    pixels = np.array(composite)
    same = (np.abs(pixels[..., :3].astype(np.int16) -
                   np.asarray(base)[..., :3]).max(axis=2) <= 2)
    alpha = np.array(layer.getchannel('A'))
    # A small margin still covers removed source glyph edges after resampling.
    changed = Image.fromarray(((alpha > 0) & ~same).astype(np.uint8)*255, 'L')
    keep = (alpha > 0) & (np.asarray(changed.filter(ImageFilter.MaxFilter(5))) > 0)
    pixels[..., 3] = np.where(keep, alpha, 0)
    # Keep the straight colour of partially transparent edits.
    pixels[keep, :3] = np.asarray(layer)[keep, :3]
    return Image.fromarray(pixels, 'RGBA')


def _layer_pdf(page, image, overlay, cancel, original=None):
    import numpy as np
    from PIL import Image
    from reportlab import rl_config
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.utils import ImageReader
    from .document_io import check_cancel, png_data

    # ASCII85 only enlarges binary image streams by a quarter.
    rl_config.useA85 = 0
    w, h = _page_size(page)
    output = BytesIO()
    canvas = Canvas(output, pagesize=(w, h), pageCompression=1)
    if overlay:
        with Image.open(BytesIO(png_data(image))) as decoded:
            layer = decoded.convert('RGBA')
        if original is not None:
            layer = _changed_pixels(layer, original)
        alpha = layer.getchannel('A')
        if alpha.getbbox() is None:
            return None
        sx, sy = w/page.width, h/page.height
        # Separate distant edits without embedding the untouched page between them.
        for x, y, own in _edit_regions(alpha):
            check_cancel(cancel)
            region = np.array(layer.crop((x, y, x+own.shape[1], y+own.shape[0])))
            region[..., 3][~own] = 0
            region = Image.fromarray(region, 'RGBA')
            bbox = region.getchannel('A').getbbox()
            region = region.crop(bbox)
            left, top = x+bbox[0], y+bbox[1]
            canvas.drawImage(ImageReader(region), left*sx, h-(top+region.height)*sy,
                             region.width*sx, region.height*sy, mask='auto')
    else:
        canvas.drawImage(ImageReader(BytesIO(_page_image(png_data(image)))), 0, 0, w, h, mask='auto')
    canvas.showPage()
    canvas.save()
    return output.getvalue()


TEXT_MODES = ('text', 'image')
# Share of 4x-downsampled pixels allowed to differ clearly from the editor
# before a page's text falls back to images. Measured on real pages, glyph
# anti-aliasing stays under 0.01% while a missing font or a changed line
# break exceeds 0.4%.
FIDELITY_LIMIT = .001


def _render_exact(data, index, width, height):
    """PDFium render stretched to the page bitmap, exactly as at import."""
    import numpy as np
    import pypdfium2
    import pypdfium2.raw as pr
    from .document_io import PDF_LOCK
    with PDF_LOCK:
        document = pypdfium2.PdfDocument(data)
        try:
            pdf_page = document[index]
            bitmap = pypdfium2.PdfBitmap.new_native(width, height, pr.FPDFBitmap_BGRx)
            try:
                pr.FPDFBitmap_FillRect(bitmap, 0, 0, width, height, 0xFFFFFFFF)
                pr.FPDF_RenderPageBitmap(bitmap, pdf_page, 0, 0, width, height, 0, pr.FPDF_ANNOT)
                return np.asarray(bitmap.to_pil().convert('RGB'))
            finally:
                bitmap.close()
                pdf_page.close()
        finally:
            document.close()


def _device_box(pdf_page, bounds, width, height):
    import ctypes
    import pypdfium2.raw as pr
    left, bottom, right, top = bounds
    xs, ys = [], []
    for x, y in ((left, bottom), (left, top), (right, bottom), (right, top)):
        dx, dy = ctypes.c_int(), ctypes.c_int()
        pr.FPDF_PageToDevice(pdf_page, 0, 0, width, height, 0, x, y, dx, dy)
        xs.append(dx.value)
        ys.append(dy.value)
    return max(0, min(xs)), max(0, min(ys)), min(width, max(xs)+1), min(height, max(ys)+1)


def _strip_native_text(pdf_page, erased, ink=None):
    """Delete source text objects whose glyphs are mostly erased.

    ``ink`` marks the source text's own pixels (page bitmap vs. its textless
    rendering); erase masks often follow glyph strokes, so coverage is
    measured on that ink rather than on the glyph's whole box. Any mismatch
    (a partly kept line, text used as a clip) is caught later by comparing
    against the editor's background, which restores it as an image.
    """
    import numpy as np
    import pypdfium2.raw as pr
    height, width = erased.shape

    def table(mask):
        return np.pad(mask.astype(np.int64).cumsum(0).cumsum(1), ((1, 0), (1, 0)))

    def total(sums, x0, y0, x1, y1):
        return sums[y1, x1]-sums[y0, x1]-sums[y1, x0]+sums[y0, x0]

    erased_sums = table(erased)
    ink_sums = table(ink) if ink is not None else None
    erased_ink = table(ink & erased) if ink is not None else None
    removed = 0
    for obj in list(pdf_page.get_objects(filter=[pr.FPDF_PAGEOBJ_TEXT])):
        x0, y0, x1, y1 = _device_box(pdf_page, obj.get_bounds(), width, height)
        if x1 <= x0 or y1 <= y0:
            continue
        glyph_ink = total(ink_sums, x0, y0, x1, y1) if ink is not None else 0
        if glyph_ink:
            covered = total(erased_ink, x0, y0, x1, y1) >= .5*glyph_ink
        else:
            covered = total(erased_sums, x0, y0, x1, y1) >= .5*(x1-x0)*(y1-y0)
        if covered:
            pdf_page.remove_obj(obj)
            obj.close()
            removed += 1
    if removed:
        pdf_page.gen_content()
    return removed


def _png_idat(image):
    """PNG-predicted zlib data, read by PDF FlateDecode with /Predictor 15."""
    import struct
    out = BytesIO()
    image.save(out, 'PNG', optimize=True)
    data, position, chunks = out.getvalue(), 8, []
    while position < len(data):
        length, kind = struct.unpack('>I4s', data[position:position+8])
        if kind == b'IDAT':
            chunks.append(data[position+8:position+8+length])
        position += 12 + length
    return b''.join(chunks)


def _image_xobject(writer, rgb, mask=None):
    """Smaller of JPEG and lossless Flate for the colour, with a 1-bit soft mask."""
    from pypdf.generic import DictionaryObject, NameObject, NumberObject, StreamObject

    def stream(data, width, height, colorspace, bits, filters, colors=None):
        obj = StreamObject()
        obj._data = data
        obj.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'),
                    NameObject('/Width'): NumberObject(width), NameObject('/Height'): NumberObject(height),
                    NameObject('/ColorSpace'): NameObject(colorspace),
                    NameObject('/BitsPerComponent'): NumberObject(bits), NameObject('/Filter'): NameObject(filters)})
        if colors:
            obj[NameObject('/DecodeParms')] = DictionaryObject({
                NameObject('/Predictor'): NumberObject(15), NameObject('/Colors'): NumberObject(colors),
                NameObject('/BitsPerComponent'): NumberObject(bits), NameObject('/Columns'): NumberObject(width)})
        return obj

    width, height = rgb.size
    jpeg = BytesIO()
    rgb.save(jpeg, 'JPEG', quality=92, subsampling=0, optimize=True)
    flate = _png_idat(rgb)
    if jpeg.tell() < len(flate)*.75:
        color = stream(jpeg.getvalue(), width, height, '/DeviceRGB', 8, '/DCTDecode')
    else:
        color = stream(flate, width, height, '/DeviceRGB', 8, '/FlateDecode', 3)
    if mask is not None:
        smask = stream(_png_idat(mask.convert('1')), width, height, '/DeviceGray', 1, '/FlateDecode', 1)
        color[NameObject('/SMask')] = writer._add_object(smask)
    return writer._add_object(color)


def _patch_layer(page, target, base, erased=None):
    """One-page PDF of the pixels where target differs from base, or None.

    Inside ``erased`` (what the user erased) every difference is kept, so
    removed text inside pictures is always covered. Elsewhere a page bitmap
    can be a resampled copy of the source; such pixels stay within the range
    of their neighbouring source pixels and are left to the native page,
    because patching them would double the crisp native lines.
    """
    import numpy as np
    from PIL import Image, ImageFilter
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    changed = np.abs(target.astype(np.int16)-base).max(axis=2) > 2
    if changed.any():
        source = Image.fromarray(base)
        low = np.asarray(source.filter(ImageFilter.MinFilter(3)), np.int16) - 8
        high = np.asarray(source.filter(ImageFilter.MaxFilter(3)), np.int16) + 8
        outside = ((target < low) | (target > high)).any(axis=2)
        blurred = [np.asarray(Image.fromarray(image).filter(ImageFilter.BoxBlur(1)), np.int16)
                   for image in (target, base)]
        edited = outside & (np.abs(blurred[0]-blurred[1]).max(axis=2) > 24)
        if erased is not None:
            near = np.asarray(Image.fromarray(erased.astype(np.uint8)*255).filter(ImageFilter.MaxFilter(5))) > 0
            edited |= near
        changed &= edited
    if not changed.any():
        return None
    # The margin still covers removed glyph edges after viewers resample the patch.
    keep = np.asarray(Image.fromarray(changed.astype(np.uint8)*255).filter(ImageFilter.MaxFilter(5))) > 0
    w, h = _page_size(page)
    sx, sy = w/page.width, h/page.height
    writer = PdfWriter()
    layer = writer.add_blank_page(w, h)
    xobjects, ops = DictionaryObject(), []
    for n, (x, y, own) in enumerate(_edit_regions(Image.fromarray(keep.astype(np.uint8)))):
        own = own[:page.height-y, :page.width-x] & keep[y:y+own.shape[0], x:x+own.shape[1]]
        ys, xs = np.nonzero(own)
        x0, x1, y0, y1 = xs.min(), xs.max()+1, ys.min(), ys.max()+1
        own = own[y0:y1, x0:x1]
        x, y = x+int(x0), y+int(y0)
        rgb = Image.fromarray(np.ascontiguousarray(target[y:y+own.shape[0], x:x+own.shape[1]]))
        mask = None
        if not own.all():
            mask = Image.fromarray(own.astype(np.uint8)*255, 'L')
            # Hidden pixels only need to be smooth: cheap to encode, no ringing.
            rgb = Image.composite(rgb, rgb.filter(ImageFilter.BoxBlur(6)), mask)
        name = NameObject(f'/Fix{n}')
        xobjects[name] = _image_xobject(writer, rgb, mask)
        ops.append(f'q {rgb.width*sx:.6f} 0 0 {rgb.height*sy:.6f} {x*sx:.6f} '
                   f'{h-(y+rgb.height)*sy:.6f} cm {name} Do Q')
    layer[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): xobjects})
    content = DecodedStreamObject()
    content.set_data('\n'.join(ops).encode())
    layer[NameObject('/Contents')] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _objects_only(page):
    bare = copy(page)
    bare.background_patches = []
    bare.objects = []
    from copy import deepcopy
    from .model import TextBox
    for obj in page.objects:
        obj = deepcopy(obj)
        if isinstance(obj, TextBox):
            obj.erase_enabled = False
        bare.objects.append(obj)
    return bare


def _vector_layers(pages):
    """Page objects as real PDF text and paths, one shared document so fonts embed once."""
    from types import SimpleNamespace
    from PySide6.QtCore import QBuffer, QIODevice, QMarginsF, QRectF, QSizeF
    from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter
    from PySide6.QtWidgets import QGraphicsScene
    from .canvas import TextItem
    from .model import GroupBox, TextBox
    from .object_items import GroupItem, VisualItem
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    writer = QPdfWriter(buffer)
    writer.setResolution(1200)
    painter = None
    try:
        for count, page in enumerate(pages):
            w, h = _page_size(page)
            writer.setPageSize(QPageSize(QSizeF(w, h), QPageSize.Point))
            writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Point)
            if painter is None:
                painter = QPainter(writer)
            else:
                writer.newPage()
            scene = QGraphicsScene()
            scene.show_controls = False
            context = SimpleNamespace(changed=lambda: None)
            items = {}
            for obj in page.objects:
                item = (TextItem(obj, context) if isinstance(obj, TextBox) else
                        GroupItem(obj, context) if isinstance(obj, GroupBox) else VisualItem(obj, context))
                scene.addItem(item)
                items[obj.id] = item
            for obj in page.objects:
                if obj.parent_id:
                    items[obj.id].setParentItem(items[obj.parent_id])
            painter.resetTransform()
            painter.scale(writer.width()/page.width, writer.height()/page.height)
            scene.render(painter, QRectF(0, 0, page.width, page.height), QRectF(0, 0, page.width, page.height))
            scene.clear()
    finally:
        if painter is not None:
            painter.end()
    buffer.close()
    return bytes(buffer.data())


def _page_box(result, page):
    from pypdf.generic import RectangleObject
    if result.rotation:
        result.transfer_rotation_to_content()
    media, crop = result.mediabox, result.cropbox
    box = RectangleObject((max(media.left, crop.left), max(media.bottom, crop.bottom),
                           min(media.right, crop.right), min(media.top, crop.top)))
    if (not all(math.isfinite(float(v)) for v in box) or
            box.width <= 0 or box.height <= 0):
        raise ValueError('원본 PDF의 페이지 크기가 올바르지 않습니다: '+page.name)
    result.cropbox = box
    w, h = _page_size(page)
    if abs(float(box.width)-w) > .1 or abs(float(box.height)-h) > .1:
        raise ValueError('원본 PDF와 편집 페이지의 크기가 다릅니다: '+page.name)
    return box


def _prepare_sources(pages, assets, cancel):
    """Delete covered source text once per source page; returns per-page sources."""
    import numpy as np
    import pypdfium2
    from PIL import Image
    from .document_io import PDF_LOCK, check_cancel
    from .recognition import restored_background
    documents, plan, removed = {}, {}, 0
    with PDF_LOCK:
        for index, page in enumerate(pages):
            if not page.pdf_asset:
                continue
            check_cancel(cancel)
            # A source page used twice keeps independent edits in its own copy.
            copies = documents.setdefault(page.pdf_asset, [])
            slot = next((i for i, (_, used) in enumerate(copies) if page.pdf_page not in used), None)
            if slot is None:
                copies.append((pypdfium2.PdfDocument(assets[page.pdf_asset]), set()))
                slot = len(copies)-1
            document, used = copies[slot]
            used.add(page.pdf_page)
            plan[index] = (page.pdf_asset, slot)
            if page.objects or page.background_patches:
                layer = Image.open(BytesIO(restored_background(assets[page.asset], page.objects,
                                                               page.background_patches, overlay=True)))
                erased = np.asarray(layer.getchannel('A')) > 0
                ink = None
                if page.clean_asset in assets:
                    with Image.open(BytesIO(assets[page.asset])) as shown, \
                            Image.open(BytesIO(assets[page.clean_asset])) as clean:
                        ink = (np.abs(np.asarray(shown.convert('RGB'), np.int16) -
                                      np.asarray(clean.convert('RGB'), np.int16)).max(axis=2) > 24)
                    if ink.shape != erased.shape:
                        ink = None
                if erased.any():
                    pdf_page = document[page.pdf_page]
                    try:
                        removed += _strip_native_text(pdf_page, erased, ink)
                    finally:
                        pdf_page.close()
        saved = {}
        for key, copies in documents.items():
            for slot, (document, _) in enumerate(copies):
                output = BytesIO()
                document.save(output)
                document.close()
                saved[key, slot] = output.getvalue()
    return saved, plan, removed


def _page_matches(rendered, expected):
    import numpy as np
    from PIL import Image
    size = (max(1, rendered.shape[1]//4), max(1, rendered.shape[0]//4))
    small = [np.asarray(Image.fromarray(image).resize(size, Image.Resampling.BOX), np.int16)
             for image in (rendered, expected)]
    return (np.abs(small[0]-small[1]).max(axis=2) > 48).mean() <= FIDELITY_LIMIT


def _build_pdf(project, assets, pages, cancel, progress, text_mode, image_text, report):
    """Assemble the output; pages listed in image_text keep their text as images."""
    import numpy as np
    from PIL import Image
    from pypdf import PdfReader, PdfWriter, Transformation
    from pypdf.annotations import Link
    from pypdf.generic import ArrayObject, NameObject
    from .document_io import check_cancel, render_page
    from .pdf_links import export_links
    from .recognition import restored_background

    readers = source_readers(pages, assets)
    sources, plan, removed = {}, {}, 0
    if text_mode == 'text':
        sources, plan, removed = _prepare_sources(pages, assets, cancel)
    edited_readers = {key: PdfReader(BytesIO(data)) for key, data in sources.items()}
    vector = None
    vector_index = {}
    if text_mode == 'text':
        drawn = [i for i, page in enumerate(pages)
                 if page.pdf_asset and page.objects and i not in image_text]
        if drawn:
            vector = PdfReader(BytesIO(_vector_layers([pages[i] for i in drawn])))
            vector_index = {i: n for n, i in enumerate(drawn)}
    writer = PdfWriter()
    writer.add_metadata({'/Title': project.name})
    destinations = {page.id: index for index, page in enumerate(pages)}
    raster_pages = []
    for count, page in enumerate(pages):
        progress(count)
        check_cancel(cancel)
        if not page.pdf_asset:
            raster_pages.append(count)
            layer = _layer_pdf(page, render_page(page, assets[page.asset]), False, cancel)
            writer.add_page(PdfReader(BytesIO(layer)).pages[0])
            continue
        if text_mode == 'text':
            key, slot = plan[count]
            original = copy(edited_readers[key, slot].pages[page.pdf_page])
        else:
            original = copy(readers[page.pdf_asset].pages[page.pdf_page])
        # Original annotations are rebuilt using stable project page IDs,
        # so reordered and partial exports cannot retain dangling targets.
        original.pop('/Annots', None)
        result = writer.add_page(original, excluded_keys=('/Annots', '/AA', '/B'))
        box = _page_box(result, page)
        w, h = _page_size(page)
        transform = Transformation().scale(float(box.width)/w, float(box.height)/h)
        transform = transform.translate(float(box.left), float(box.bottom))
        layers = []
        if text_mode == 'image':
            # Rendering controls transforms, clipping, opacity, rich text and
            # vertical writing exactly as the existing PNG/preview renderer.
            if page.objects or page.background_patches:
                layers.append(_layer_pdf(page, render_page(page, assets[page.asset], overlay=True), True,
                                         cancel, assets[page.asset]))
        else:
            # Background: whatever the edited page shows that the cleaned source
            # does not (text inside pictures, pasted art, repaired patches).
            repaired = np.asarray(Image.open(BytesIO(
                restored_background(assets[page.asset], page.objects, page.background_patches)
                if page.objects or page.background_patches else assets[page.asset])).convert('RGB'))
            erased = None
            if page.objects or page.background_patches:
                coverage = Image.open(BytesIO(restored_background(
                    assets[page.asset], page.objects, page.background_patches, overlay=True)))
                erased = np.asarray(coverage.getchannel('A')) > 0
            base = _render_exact(sources[plan[count]], page.pdf_page, page.width, page.height)
            layers.append(_patch_layer(page, repaired, base, erased))
            if count in image_text and page.objects:
                layers.append(_layer_pdf(page, render_page(_objects_only(page), assets[page.asset], overlay=True),
                                         True, cancel))
        for layer in layers:
            if layer is not None:
                result.merge_transformed_page(PdfReader(BytesIO(layer)).pages[0], transform)
        if count in vector_index:
            result.merge_transformed_page(vector.pages[vector_index[count]], transform)
        result.compress_content_streams()

    for index, page in enumerate(pages):
        check_cancel(cancel)
        crop = writer.pages[index].cropbox
        for (x, y, rw, rh), target in export_links(page, destinations):
            annotation = writer.add_annotation(index, Link(
                rect=(float(crop.left)+x*float(crop.width)/page.width,
                      float(crop.bottom)+(page.height-y-rh)*float(crop.height)/page.height,
                      float(crop.left)+(x+rw)*float(crop.width)/page.width,
                      float(crop.bottom)+(page.height-y)*float(crop.height)/page.height),
                target_page_index=destinations[target]))
            annotation[NameObject('/Dest')] = ArrayObject([
                writer.pages[destinations[target]].indirect_reference, NameObject('/Fit')])
    check_cancel(cancel)
    output = BytesIO()
    writer.write(output)
    report.update(raster_pages=raster_pages, removed_source_text=removed)
    return output.getvalue()


def export_pdf(project, assets, pages, destination, cancel, progress, text_mode='text', report=None):
    """Write the PDF. In text mode, translated source text is deleted from the
    original page and Korean is written as real text; pages whose result
    differs from the editor's rendering keep their text as images instead."""
    import numpy as np
    from PIL import Image
    from .document_io import check_cancel, png_data, render_page
    if text_mode not in TEXT_MODES:
        raise ValueError('지원하지 않는 PDF 글자 출력 방식입니다.')
    report = {} if report is None else report
    image_text = set()
    data = _build_pdf(project, assets, pages, cancel, progress, text_mode, image_text, report)
    if text_mode == 'text':
        candidates = [i for i, page in enumerate(pages) if page.pdf_asset and page.objects]
        for index in candidates:
            check_cancel(cancel)
            page = pages[index]
            with Image.open(BytesIO(png_data(render_page(page, assets[page.asset])))) as decoded:
                expected = np.asarray(decoded.convert('RGB'))
            rendered = _render_exact(data, index, page.width, page.height)
            if not _page_matches(rendered, expected):
                image_text.add(index)
        if image_text:
            data = _build_pdf(project, assets, pages, cancel, progress, text_mode, image_text, report)
    report.update(text_mode=text_mode, image_text_pages=sorted(image_text))
    check_cancel(cancel)
    Path(destination).write_bytes(data)
    progress(len(pages))
