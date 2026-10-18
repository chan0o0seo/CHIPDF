"""Keep native PDF pages and add only transparent, cropped edit layers.

This is visual editing, not redaction: covered source text remains in the PDF.
Image imports and projects without embedded PDFs use the raster export path.
"""
import hashlib
from copy import copy
from io import BytesIO
import math


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


def _layer_pdf(page, image, overlay, cancel):
    from PIL import Image
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.utils import ImageReader
    from .document_io import check_cancel, png_data

    w, h = _page_size(page)
    output = BytesIO()
    canvas = Canvas(output, pagesize=(w, h), pageCompression=1)
    if overlay:
        with Image.open(BytesIO(png_data(image))) as decoded:
            layer = decoded.convert('RGBA')
        bounds = layer.getchannel('A').getbbox()
        if bounds is None:
            return None
        # Separate distant edits without embedding the untouched page between
        # them. Tiles also bound the PDF image and soft-mask decode memory.
        for y in range(bounds[1], bounds[3], 512):
            for x in range(bounds[0], bounds[2], 512):
                check_cancel(cancel)
                tile = layer.crop((x, y, min(x+512, bounds[2]), min(y+512, bounds[3])))
                bbox = tile.getchannel('A').getbbox()
                if bbox is None:
                    continue
                tile = tile.crop(bbox)
                left, top = x+bbox[0], y+bbox[1]
                canvas.drawImage(ImageReader(tile), left*w/page.width,
                                 (page.height-top-tile.height)*h/page.height,
                                 tile.width*w/page.width, tile.height*h/page.height, mask='auto')
    else:
        canvas.drawImage(ImageReader(BytesIO(png_data(image))), 0, 0, w, h, mask='auto')
    canvas.showPage()
    canvas.save()
    return output.getvalue()


def export_pdf(project, assets, pages, destination, cancel, progress):
    from pypdf import PdfReader, PdfWriter, Transformation
    from pypdf.annotations import Link
    from pypdf.generic import ArrayObject, NameObject, RectangleObject
    from .document_io import check_cancel, render_page
    from .pdf_links import export_links

    readers = source_readers(pages, assets)
    writer = PdfWriter()
    writer.add_metadata({'/Title': project.name})
    destinations = {page.id: index for index, page in enumerate(pages)}
    for count, page in enumerate(pages):
        progress(count)
        check_cancel(cancel)
        if page.pdf_asset:
            # Original annotations are rebuilt using stable project page IDs,
            # so reordered and partial exports cannot retain dangling targets.
            original = copy(readers[page.pdf_asset].pages[page.pdf_page])
            original.pop('/Annots', None)
            result = writer.add_page(original,
                                     excluded_keys=('/Annots', '/AA', '/B'))
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
            # Rendering controls transforms, clipping, opacity, rich text and
            # vertical writing exactly as the existing PNG/preview renderer.
            layer = (_layer_pdf(page, render_page(page, assets[page.asset], overlay=True), True, cancel)
                     if page.objects or page.background_patches else None)
            if layer is not None:
                transform = Transformation().scale(float(box.width)/w, float(box.height)/h)
                transform = transform.translate(float(box.left), float(box.bottom))
                result.merge_transformed_page(PdfReader(BytesIO(layer)).pages[0], transform)
            result.compress_content_streams()
        else:
            layer = _layer_pdf(page, render_page(page, assets[page.asset]), False, cancel)
            result = writer.add_page(PdfReader(BytesIO(layer)).pages[0])

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
    writer.write(destination)
    progress(len(pages))
