"""Small, consistent outline icons drawn locally with Qt.

These original geometric glyphs use a 24-unit grid, rounded 1.65-unit strokes,
and the Blue Office palette. They require no downloaded assets, icon font,
QtSvg installation, or changes to application packaging. A QGuiApplication
must exist before calling icon(), just as for any QPixmap-based icon.
"""
from __future__ import annotations

from functools import lru_cache
from math import cos, pi, sin

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from .theme import COLORS


_ALIASES = {
    "folder": "open", "folder_open": "open", "folder-open": "open",
    "file-open": "open", "file_open": "open", "save-as": "save",
    "save_as": "save", "download": "export", "pdf": "export",
    "add": "text", "add_text": "text", "text-box": "text",
    "text_box": "text", "insert-text": "text", "cursor": "select",
    "pointer": "select", "ocr": "region", "scan": "region",
    "sentence": "region", "select_text": "region", "language": "translate",
    "source_text": "source", "inspect": "source", "eye": "compare",
    "eraser": "erase", "apply_erase": "erase", "clear": "erase",
    "remove": "delete", "trash": "delete", "cancel": "close",
    "stop": "close", "x": "close", "shape": "shapes",
    "insert-image": "image", "picture": "image", "page_link": "link",
    "page-link": "link", "restore_links": "link", "layout": "arrange",
    "geometry": "arrange", "position": "arrange", "align": "arrange",
    "align_left": "align-left", "align_center": "align-center",
    "align_right": "align-right", "line_spacing": "paragraph",
    "spacing": "paragraph", "format": "font", "font_color": "color",
    "font-color": "color", "fill_color": "fill", "background": "fill",
    "favorite": "star", "favorites": "star", "font_favorite": "star",
    "strike": "strikethrough", "strikeout": "strikethrough",
    "vertical_text": "vertical", "writing-mode": "vertical",
    "copy_style": "format-painter", "paste_style": "format-painter",
    "format_painter": "format-painter", "format-copy": "format-painter",
    "preset": "styles", "text-preset": "styles", "layout-preset": "arrange",
    "unlock_all": "unlock", "leave_group": "ungroup", "snap": "grid",
    "guides": "grid", "thumbnails": "pages", "page": "pages",
    "sidebar": "pages", "add_page": "append", "add-page": "append",
    "zoom_in": "zoom-in", "zoom_out": "zoom-out", "fit_page": "fit",
    "fit-page": "fit", "chevron": "down", "chevron-down": "down", "chevron-right": "right",
    "chevron-left": "left", "chevron-up": "up", "more-horizontal": "more",
    "settings": "options", "info": "help", "check": "done",
    "review": "done", "refresh": "restore", "rotate": "restore",
}


def _draw(p: QPainter, name: str, color: QColor) -> None:
    """Paint one outline glyph in a 24 by 24 logical coordinate space."""
    p.setPen(QPen(color, 1.65, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)

    def line(x1, y1, x2, y2):
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def rect(x, y, width, height, radius=1.2):
        p.drawRoundedRect(QRectF(x, y, width, height), radius, radius)

    def ellipse(x, y, width, height):
        p.drawEllipse(QRectF(x, y, width, height))

    def path(points, close=False):
        curve = QPainterPath(QPointF(*points[0]))
        for point in points[1:]:
            curve.lineTo(QPointF(*point))
        if close:
            curve.closeSubpath()
        p.drawPath(curve)

    def dot(x, y, radius=0.85):
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        ellipse(x - radius, y - radius, radius * 2, radius * 2)
        p.restore()

    if name == "open":
        path([(3, 8), (3, 5.5), (9, 5.5), (11, 8), (20, 8)])
        path([(3, 8), (5, 19), (20, 19), (22, 10), (7, 10), (5, 19)])
    elif name == "save":
        path([(5, 3.5), (17, 3.5), (20.5, 7), (20.5, 20.5), (3.5, 20.5), (3.5, 5), (5, 3.5)])
        rect(7, 3.5, 9, 6, 0.2)
        rect(7, 14, 10, 6.5, 0.4)
        line(14, 5.5, 14, 7.5)
    elif name == "export":
        path([(14, 3), (5, 3), (5, 21), (19, 21), (19, 14)])
        line(12, 12, 21, 3)
        path([(15, 3), (21, 3), (21, 9)])
        line(8, 15, 13, 15)
        line(8, 18, 15, 18)
    elif name in ("undo", "redo"):
        if name == "redo":
            p.translate(24, 0)
            p.scale(-1, 1)
        path([(8, 4), (3, 9), (8, 14)])
        curve = QPainterPath(QPointF(3, 9))
        curve.lineTo(14, 9)
        curve.cubicTo(22, 9, 23, 20, 13, 20)
        p.drawPath(curve)
    elif name == "text":
        rect(3, 4, 18, 16)
        line(8, 8, 16, 8)
        line(12, 8, 12, 17)
        line(9.5, 17, 14.5, 17)
    elif name == "select":
        path([(5, 3), (5, 19), (9, 15), (12, 21), (15, 19.5), (12, 13.5), (18, 13)], True)
    elif name in ("region", "crop"):
        if name == "region":
            for corners in [[(8, 3), (3, 3), (3, 8)], [(16, 3), (21, 3), (21, 8)],
                            [(3, 16), (3, 21), (8, 21)], [(21, 16), (21, 21), (16, 21)]]:
                path(corners)
            line(7, 9, 17, 9)
            line(7, 12, 15, 12)
            line(7, 15, 17, 15)
        else:
            path([(3, 6), (18, 6), (18, 21)])
            path([(6, 3), (6, 18), (21, 18)])
            line(9, 15, 21, 3)
    elif name == "translate":
        path([(3, 5), (16, 5)])
        line(9, 2.5, 9, 5)
        curve = QPainterPath(QPointF(13, 5))
        curve.cubicTo(12, 12, 8, 15, 3, 17)
        p.drawPath(curve)
        curve = QPainterPath(QPointF(5, 8))
        curve.cubicTo(7, 12, 9, 13, 12, 14)
        p.drawPath(curve)
        path([(13, 21), (17, 11), (21, 21)])
        line(14.5, 18, 19.5, 18)
    elif name == "source":
        path([(5, 3), (15, 3), (19, 7), (19, 20), (5, 20)], True)
        path([(15, 3), (15, 7), (19, 7)])
        for y, end in ((10, 15), (13, 15), (16, 12)):
            line(8, y, end, y)
    elif name == "compare":
        curve = QPainterPath(QPointF(2, 12))
        curve.cubicTo(7, 3, 17, 3, 22, 12)
        curve.cubicTo(17, 21, 7, 21, 2, 12)
        p.drawPath(curve)
        ellipse(8.5, 8.5, 7, 7)
        line(12, 8.5, 12, 15.5)
    elif name == "copy":
        rect(8, 7, 12, 14)
        path([(16, 4), (16, 3), (4, 3), (4, 17), (5, 17)])
    elif name == "duplicate":
        rect(8, 7, 13, 14)
        path([(16, 4), (16, 3), (3, 3), (3, 17), (5, 17)])
        line(11, 14, 18, 14)
        line(14.5, 10.5, 14.5, 17.5)
    elif name == "cut":
        ellipse(3, 15, 5.5, 5.5)
        ellipse(15.5, 15, 5.5, 5.5)
        line(8, 16, 19, 3)
        line(16, 16, 5, 3)
        ellipse(11, 11, 2, 2)
    elif name == "paste":
        path([(8, 5), (4, 5), (4, 21), (20, 21), (20, 5), (16, 5)])
        rect(8, 3, 8, 4, 1)
        line(8, 11, 16, 11)
        line(8, 15, 16, 15)
    elif name == "delete":
        path([(5, 7), (6, 21), (18, 21), (19, 7)])
        line(3, 6, 21, 6)
        path([(8, 6), (8, 3), (16, 3), (16, 6)])
        line(10, 10, 10, 17)
        line(14, 10, 14, 17)
    elif name == "image":
        rect(3, 4, 18, 16)
        ellipse(6.5, 7, 3, 3)
        path([(3.5, 17), (9, 12), (12, 15), (16, 10), (21, 16)])
    elif name == "shapes":
        rect(3, 3, 11, 11, 0.4)
        p.setBrush(Qt.NoBrush)
        ellipse(11, 11, 10, 10)
    elif name == "link":
        p.save()
        p.translate(12, 12)
        p.rotate(-40)
        rect(-10, -3.5, 10, 7, 3.5)
        rect(0, -3.5, 10, 7, 3.5)
        line(-5, 0, 5, 0)
        p.restore()
    elif name == "brush":
        path([(9, 14), (17, 3), (21, 6), (12, 17)], True)
        curve = QPainterPath(QPointF(9, 14))
        curve.cubicTo(3, 14, 7, 19, 2, 21)
        curve.cubicTo(9, 22, 13, 21, 12, 17)
        p.drawPath(curve)
    elif name == "stamp":
        path([(7, 14), (9, 10), (9, 5)])
        path([(17, 14), (15, 10), (15, 5)])
        p.drawArc(QRectF(9, 2, 6, 6), 0, 180 * 16)
        rect(4, 14, 16, 5)
        line(4, 22, 20, 22)
    elif name == "erase":
        path([(3, 14), (13, 4), (21, 12), (12, 21), (9, 21)], True)
        line(7, 10, 15, 18)
        line(12, 21, 22, 21)
    elif name in ("bold", "italic", "underline", "strikethrough"):
        if name == "bold":
            p.setPen(QPen(color, 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            line(7, 4, 7, 20)
            curve = QPainterPath(QPointF(7, 4))
            curve.lineTo(13, 4)
            curve.cubicTo(19, 4, 19, 12, 13, 12)
            curve.lineTo(7, 12)
            curve.moveTo(13, 12)
            curve.cubicTo(20, 12, 20, 20, 13, 20)
            curve.lineTo(7, 20)
            p.drawPath(curve)
        elif name == "italic":
            line(10, 4, 19, 4)
            line(5, 20, 14, 20)
            line(15, 4, 9, 20)
        elif name == "underline":
            curve = QPainterPath(QPointF(6, 3))
            curve.lineTo(6, 12)
            curve.cubicTo(6, 19, 18, 19, 18, 12)
            curve.lineTo(18, 3)
            p.drawPath(curve)
            line(5, 21, 19, 21)
        else:
            curve = QPainterPath(QPointF(18, 6))
            curve.cubicTo(14, 1, 5, 3, 6, 8)
            curve.cubicTo(7, 12, 18, 11, 18, 17)
            curve.cubicTo(18, 22, 7, 23, 5, 18)
            p.drawPath(curve)
            line(3, 12, 21, 12)
    elif name in ("font", "color"):
        path([(5, 19 if name == "font" else 17), (12, 3), (19, 19 if name == "font" else 17)])
        line(8, 12, 16, 12)
        if name == "color":
            p.setPen(QPen(color, 3, Qt.SolidLine, Qt.RoundCap))
            line(4, 21, 20, 21)
    elif name == "fill":
        path([(3, 12), (12, 3), (20, 11), (11, 20)], True)
        line(4, 12, 19, 12)
        line(8, 3, 12, 7)
        curve = QPainterPath(QPointF(21, 15))
        curve.cubicTo(17, 19, 18, 22, 21, 22)
        curve.cubicTo(24, 22, 23, 19, 21, 15)
        p.drawPath(curve)
    elif name in ("align-left", "align-center", "align-right"):
        for y, length in ((5, 18), (10, 12), (15, 18), (20, 12)):
            start = 3 if name == "align-left" else (12 - length / 2 if name == "align-center" else 21 - length)
            line(start, y, start + length, y)
    elif name == "paragraph":
        for y in (5, 10, 15, 20):
            line(11, y, 21, y)
        line(5, 4, 5, 21)
        path([(2, 7), (5, 4), (8, 7)])
        path([(2, 18), (5, 21), (8, 18)])
    elif name == "vertical":
        line(5, 4, 5, 20)
        path([(2, 17), (5, 20), (8, 17)])
        for y in (5, 11, 17):
            line(12, y, 21, y)
            line(12, y + 2.5, 18, y + 2.5)
    elif name == "format-painter":
        rect(3, 3, 15, 6)
        path([(18, 6), (21, 6), (21, 13), (12, 13), (12, 16)])
        rect(10, 16, 4, 6)
    elif name == "arrange":
        line(3, 3, 3, 21)
        line(3, 21, 21, 21)
        rect(7, 4, 13, 5, 0.5)
        rect(7, 13, 9, 5, 0.5)
    elif name in ("group", "ungroup"):
        rect(7, 7, 10, 10, 0.5)
        for x, y in ((3, 3), (17, 3), (3, 17), (17, 17)):
            rect(x, y, 4, 4, 0.4)
        if name == "group":
            for start, end in (((7, 5), (17, 5)), ((7, 19), (17, 19)), ((5, 7), (5, 17)), ((19, 7), (19, 17))):
                line(*start, *end)
    elif name in ("lock", "unlock"):
        rect(5, 10, 14, 11)
        curve = QPainterPath(QPointF(8, 10))
        curve.lineTo(8, 7)
        if name == "lock":
            curve.cubicTo(8, 1, 16, 1, 16, 7)
            curve.lineTo(16, 10)
        else:
            curve.cubicTo(8, 1, 17, 1, 17, 7)
        p.drawPath(curve)
        dot(12, 15, 1)
        line(12, 16, 12, 18)
    elif name == "grid":
        rect(3, 3, 18, 18, 0.5)
        for xy in (9, 15):
            line(xy, 3, xy, 21)
            line(3, xy, 21, xy)
    elif name == "styles":
        rect(3, 3, 14, 18)
        path([(7, 16), (10, 7), (13, 16)])
        line(8, 13, 12, 13)
        path([(20, 6), (21, 6), (21, 21)])
    elif name == "pages":
        rect(4, 3, 6, 7, 0.6)
        rect(4, 14, 6, 7, 0.6)
        rect(14, 3, 6, 18, 0.6)
    elif name == "panel":
        rect(3, 3, 18, 18, 1)
        line(14, 3, 14, 21)
        line(17, 7, 18, 7)
        line(17, 11, 18, 11)
        line(17, 15, 18, 15)
    elif name == "append":
        rect(3, 3, 13, 18)
        line(11, 15, 22, 15)
        line(17, 10, 17, 20)
    elif name == "star":
        points = []
        for index in range(10):
            angle = -pi / 2 + index * pi / 5
            radius = 9.5 if index % 2 == 0 else 4.25
            points.append((12 + radius * cos(angle), 12 + radius * sin(angle)))
        path(points, True)
    elif name in ("zoom-in", "zoom-out"):
        ellipse(3, 3, 13, 13)
        line(14.5, 14.5, 21, 21)
        line(6.5, 9.5, 12.5, 9.5)
        if name == "zoom-in":
            line(9.5, 6.5, 9.5, 12.5)
    elif name == "fit":
        for points in [[(8, 3), (3, 3), (3, 8)], [(16, 3), (21, 3), (21, 8)],
                       [(3, 16), (3, 21), (8, 21)], [(21, 16), (21, 21), (16, 21)]]:
            path(points)
        rect(8, 7, 8, 10, 0.5)
    elif name == "restore":
        path([(3, 4), (3, 10), (9, 10)])
        curve = QPainterPath(QPointF(3, 10))
        curve.cubicTo(6, 0, 21, 2, 21, 12)
        curve.cubicTo(21, 23, 5, 25, 3, 16)
        p.drawPath(curve)
    elif name == "options":
        for x, cy in ((5, 8), (12, 16), (19, 9)):
            line(x, 3, x, cy - 2.5)
            line(x, cy + 2.5, x, 21)
            ellipse(x - 2.5, cy - 2.5, 5, 5)
    elif name == "help":
        ellipse(3, 3, 18, 18)
        curve = QPainterPath(QPointF(9, 9))
        curve.cubicTo(9, 5, 16, 5, 16, 9)
        curve.cubicTo(16, 12, 12, 11, 12, 14)
        p.drawPath(curve)
        dot(12, 17)
    elif name == "done":
        path([(4, 12), (9, 17), (20, 6)])
    elif name == "close":
        line(6, 6, 18, 18)
        line(18, 6, 6, 18)
    elif name in ("down", "up", "left", "right"):
        points = {"down": [(6, 9), (12, 15), (18, 9)],
                  "up": [(6, 15), (12, 9), (18, 15)],
                  "left": [(15, 6), (9, 12), (15, 18)],
                  "right": [(9, 6), (15, 12), (9, 18)]}
        path(points[name])
    elif name == "plus":
        line(4, 12, 20, 12)
        line(12, 4, 12, 20)
    elif name == "minus":
        line(4, 12, 20, 12)
    else:
        for x in (5, 12, 19):
            dot(x, 12, 1.2)


@lru_cache(maxsize=192)
def _cached_icon(name: str, color: str | None, size: int) -> QIcon:
    result = QIcon()
    normal = color or "#3C4856"
    active = color or COLORS["accent"]
    disabled = COLORS["disabledText"]
    states = (
        (QIcon.Normal, QIcon.Off, normal),
        (QIcon.Normal, QIcon.On, active),
        (QIcon.Active, QIcon.Off, active),
        (QIcon.Active, QIcon.On, active),
        (QIcon.Selected, QIcon.Off, active),
        (QIcon.Selected, QIcon.On, active),
        (QIcon.Disabled, QIcon.Off, disabled),
        (QIcon.Disabled, QIcon.On, disabled),
    )
    for mode, state, ink in states:
        for dpr in (1.0, 1.5, 2.0, 3.0):
            pixels = round(size * dpr)
            pixmap = QPixmap(pixels, pixels)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.scale(pixels / 24, pixels / 24)
            _draw(painter, name, QColor(ink))
            painter.end()
            pixmap.setDevicePixelRatio(dpr)
            result.addPixmap(pixmap, mode, state)
    return result


def icon(name: str, color: str | None = None, size: int = 24) -> QIcon:
    """Return a DPI-aware icon; checked and active states use the accent blue.

    Pass color="#FFFFFF" for icons on a primary blue button. Unknown names
    display a neutral ellipsis so an action remains visible and usable.
    """
    key = str(name).strip().lower()
    key = _ALIASES.get(key, key)
    return QIcon(_cached_icon(key, color, max(12, int(size))))
