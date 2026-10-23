"""Text box effects drawn as extra passes under the editable text.

The same painter calls serve the canvas, PNG export and the vector PDF layer,
so outlines stay vector paths there. A blurred shadow becomes a small image.
"""
import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QTextCharFormat, QTextCursor

_TRANSPARENT = QColor(0, 0, 0, 0)


def effect_extent(model):
    """How far effects may reach outside the box, in item units."""
    extent = model.outline_width
    if model.shadow_enabled:
        extent += max(abs(model.shadow_dx), abs(model.shadow_dy)) + model.shadow_blur * 2
    return extent


def _effect_document(item, color=None, outline=None, highlight=None):
    source = item.document()
    key = (source.revision(), source.textWidth(), color and color.rgba(),
           outline and (outline.color().rgba(), outline.widthF()), highlight and highlight.rgba())
    cache = item.__dict__.setdefault('_effect_documents', {})
    if key in cache:
        return cache[key]
    document = source.clone()
    document.setDocumentMargin(source.documentMargin())
    document.setDefaultTextOption(source.defaultTextOption())
    document.setTextWidth(source.textWidth())
    fmt = QTextCharFormat()
    if highlight is not None:
        fmt.setBackground(highlight)
        fmt.setForeground(_TRANSPARENT)
    else:
        if color is not None:
            fmt.setForeground(color)
        if outline is not None:
            fmt.setTextOutline(outline)
            if color is None:
                fmt.setForeground(outline.color())
    cursor = QTextCursor(document)
    cursor.select(QTextCursor.Document)
    cursor.mergeCharFormat(fmt)
    if len(cache) > 6:
        cache.clear()
    cache[key] = document
    return document


def _draw(item, painter, color=None, outline=None, highlight=None):
    if item.is_vertical:
        item.vertical_layout().paint(painter, color=color, outline=outline, highlight=highlight)
    else:
        _effect_document(item, color, outline, highlight).drawContents(painter)


def _outline_pen(color, width):
    # The stroke is centred on the glyph edge; the fill pass covers the inner half.
    return QPen(QColor(color), width * 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)


def _blurred_shadow(item, painter, color, outline):
    model = item.model
    transform = painter.worldTransform()
    scale = max(.25, min(4.0, math.hypot(transform.m11(), transform.m12()) or 1.0))
    pad = model.shadow_blur * 2 + model.outline_width + 2
    width = max(1, math.ceil((model.width + pad * 2) * scale))
    height = max(1, math.ceil((model.height + pad * 2) * scale))
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    canvas = QPainter(image)
    canvas.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    canvas.scale(scale, scale)
    canvas.translate(pad, pad)
    _draw(item, canvas, color, outline)
    canvas.end()
    from PIL import Image, ImageFilter
    pixels = Image.frombuffer('RGBA', (width, height), bytes(image.constBits()), 'raw', 'BGRA', 0, 1)
    pixels = pixels.filter(ImageFilter.GaussianBlur(model.shadow_blur * scale / 2))
    blurred = QImage(pixels.tobytes('raw', 'BGRA'), width, height, QImage.Format_ARGB32_Premultiplied).copy()
    painter.drawImage(QRectF(model.shadow_dx - pad, model.shadow_dy - pad, width / scale, height / scale), blurred)


def paint_effects(item, painter):
    """Highlight, shadow and outline passes, drawn before the normal text."""
    model = item.model
    if model.highlight != 'transparent':
        _draw(item, painter, highlight=QColor(model.highlight))
    outline = _outline_pen(model.outline_color, model.outline_width) if model.outline_width > 0 else None
    if model.shadow_enabled and model.shadow_opacity > 0:
        color = QColor(model.shadow_color)
        shadow_outline = _outline_pen(model.shadow_color, model.outline_width) if outline is not None else None
        painter.save()
        painter.setOpacity(painter.opacity() * model.shadow_opacity)
        if model.shadow_blur > 0:
            _blurred_shadow(item, painter, color, shadow_outline)
        else:
            painter.translate(model.shadow_dx, model.shadow_dy)
            _draw(item, painter, color, shadow_outline)
        painter.restore()
    if outline is not None:
        _draw(item, painter, outline=outline)
