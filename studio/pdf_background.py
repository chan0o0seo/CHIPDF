"""Render the real PDF background without drawing its native text objects.

Call under document_io.PDF_LOCK with an open page. No PDF content is rewritten:
only rendering activity is changed temporarily, including text inside Forms.
Raster text and outlined glyphs remain part of their original image/path.
"""
from contextlib import closing
import ctypes
from io import BytesIO
import math


MAX_OBJECTS = 100_000
MAX_FORM_DEPTH = 32


def _check_cancel(cancelled):
    if cancelled and cancelled():
        raise InterruptedError('PDF 배경 준비가 중단되었습니다.')


def render_without_text(pdf_page, scale, cancelled=None):
    """Return ``(PNG bytes, hidden object count)`` or None if unavailable.

    Uses exactly ``pdf_page.render(scale=scale)`` like the original import.
    Text clipping can affect later graphics, so a page containing active text
    in a clipping or unknown rendering mode is deliberately left unsupported.
    Invisible text is retained; an OCR-only PDF therefore has no clean asset.
    Object/depth and bitmap limits bound work on unusual PDF content streams.
    Cancellation raises InterruptedError and always restores page activity.
    """
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    _check_cancel(cancelled)
    if not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0:
        raise ValueError('PDF 배경 배율이 올바르지 않습니다.')
    width, height = pdf_page.get_size()
    if not all(math.isfinite(value) and value > 0 for value in (width, height)):
        return None
    size = (math.ceil(width * scale), math.ceil(height * scale))
    if max(size) > 16000 or size[0] * size[1] > 80_000_000:
        return None
    names = ('FPDFPageObj_GetIsActive', 'FPDFPageObj_SetIsActive',
             'FPDFTextObj_GetTextRenderMode', 'FPDFFormObj_CountObjects',
             'FPDFFormObj_GetObject')
    if any(not hasattr(raw, name) for name in names):
        return None

    texts, visited = [], set()
    remaining = MAX_OBJECTS

    def collect(parent, depth=0):
        nonlocal remaining
        count_objects = raw.FPDFPage_CountObjects if depth == 0 else raw.FPDFFormObj_CountObjects
        get_object = raw.FPDFPage_GetObject if depth == 0 else raw.FPDFFormObj_GetObject
        count = count_objects(parent)
        if count < 0 or count > remaining:
            return False
        remaining -= count
        for index in range(count):
            _check_cancel(cancelled)
            obj = get_object(parent, index)
            if not obj:
                return False
            address = ctypes.cast(obj, ctypes.c_void_p).value
            if address in visited:
                continue
            visited.add(address)
            active = raw.FPDF_BOOL()
            if not raw.FPDFPageObj_GetIsActive(obj, ctypes.byref(active)):
                return False
            if not active.value:
                continue
            kind = raw.FPDFPageObj_GetType(obj)
            if kind == raw.FPDF_PAGEOBJ_TEXT:
                mode = raw.FPDFTextObj_GetTextRenderMode(obj)
                if mode in (raw.FPDF_TEXTRENDERMODE_FILL, raw.FPDF_TEXTRENDERMODE_STROKE,
                            raw.FPDF_TEXTRENDERMODE_FILL_STROKE):
                    texts.append(obj)
                elif mode != raw.FPDF_TEXTRENDERMODE_INVISIBLE:
                    return False
            elif kind == raw.FPDF_PAGEOBJ_FORM:
                if depth >= MAX_FORM_DEPTH or not collect(obj, depth + 1):
                    return False
        return True

    if not collect(pdf_page) or not texts:
        return None
    changed = []
    try:
        for obj in texts:
            _check_cancel(cancelled)
            if not raw.FPDFPageObj_SetIsActive(obj, False):
                return None
            changed.append(obj)
        _check_cancel(cancelled)
        with closing(pdf_page.render(scale=scale)) as bitmap:
            _check_cancel(cancelled)
            stream = BytesIO()
            bitmap.to_pil().save(stream, 'PNG')
        _check_cancel(cancelled)
        return stream.getvalue(), len(texts)
    finally:
        restored = True
        for obj in reversed(changed):
            if not raw.FPDFPageObj_SetIsActive(obj, True):
                restored = False
        if not restored:
            raise pdfium.PdfiumError('PDF 글자 표시 상태를 복구하지 못했습니다.')
