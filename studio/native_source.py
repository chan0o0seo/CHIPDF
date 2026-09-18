"""Retain selectable PDF characters in page pixels for future source readings."""
from contextlib import closing
import ctypes
import math
import re


def read_native_chars(page, width, height, cancelled=None):
    """Run under PDF_LOCK, using the same device transform as imported links."""
    import pypdfium2.raw as raw
    from .document_io import check_cancel
    rows = []
    with closing(page.get_textpage()) as textpage:
        count = textpage.count_chars()
        if count > 30000:
            return []
        for index in range(count):
            if index % 128 == 0:
                check_cancel(cancelled)
            code = raw.FPDFText_GetUnicode(textpage, index)
            if not code or code > 0x10ffff or 0xd800 <= code <= 0xdfff:
                return []  # An incomplete text layer must not replace good OCR.
            char = chr(code)
            if char.isspace():
                if rows:
                    whitespace = "\n" if char in "\r\n" else " "
                    if rows[-1][0] != whitespace:
                        rows.append([whitespace, *rows[-1][1:]])
                continue
            if code == 0xfffd or 0xe000 <= code <= 0xf8ff or code < 32:
                return []
            left, bottom, right, top = textpage.get_charbox(index)
            if not all(math.isfinite(v) for v in (left, bottom, right, top)):
                return []
            points = []
            for px, py in ((left, bottom), (left, top), (right, bottom), (right, top)):
                x, y = ctypes.c_int(), ctypes.c_int()
                if not raw.FPDF_PageToDevice(page, 0, 0, width, height, 0, px, py, ctypes.byref(x), ctypes.byref(y)):
                    return []
                points.append((x.value, y.value))
            x0, y0 = max(0, min(p[0] for p in points)), max(0, min(p[1] for p in points))
            x1, y1 = min(width, max(p[0] for p in points)), min(height, max(p[1] for p in points))
            if x1 > x0 and y1 > y0:
                rows.append([char, x0, y0, x1-x0, y1-y0])
    return rows


def prefer_native_source(region, characters):
    """Only new readings use native text. Existing/manual source stays untouched."""
    if not characters:
        return region
    x, y, width, height = region.rect
    selected, previous_selected = [], False
    for char, cx, cy, cw, ch in characters:
        if char.isspace():
            if previous_selected:
                selected.append(char)
            continue
        covered = (max(0, min(x+width, cx+cw)-max(x, cx)) *
                   max(0, min(y+height, cy+ch)-max(y, cy)))
        previous_selected = covered >= cw * ch * .7
        if previous_selected:
            selected.append(char)
    text = "".join(selected).replace("\r\n", "\n").strip()
    # Mixed scanned/selectable content must not lose the scanned portion.
    letters = lambda value: len(re.sub(r'\s', '', value))
    original_count, native_count = letters(region.text), letters(text)
    if text and (not original_count or .7 * original_count <= native_count <= 1.8 * original_count):
        region.text = text
        region.source_method = "pdf"
    return region
