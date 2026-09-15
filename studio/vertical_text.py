"""Vertical rich text geometry shared by the canvas and exported pages.

QTextDocument remains the text/undo authority. This view uses UTF-16 positions,
as QTextCursor does, and never places a caret inside a grapheme cluster.
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt, QTextBoundaryFinder
from PySide6.QtGui import (QColor, QFontMetricsF, QPen, QTextBlockFormat,
                          QTextCursor, QTextLayout)


_ROTATED = frozenset("()[]{}（）［］｛｝〈〉《》「」『』【】〔〕〖〗〘〙〚〛ー―—–─…‥〜～")
_CORNER = frozenset("、。，．")


def grapheme_spans(text):
    """Yield (UTF-16 start, UTF-16 end, text) without Python/Qt index mixing."""
    encoded = text.encode("utf-16-le")
    finder = QTextBoundaryFinder(QTextBoundaryFinder.Grapheme, text)
    start = 0
    while (end := finder.toNextBoundary()) != -1:
        yield start, end, encoded[start * 2:end * 2].decode("utf-16-le")
        start = end


@dataclass
class _Glyph:
    start: int
    end: int
    text: str
    layout: QTextLayout
    width: float
    advance: float
    color: QColor
    background: QColor | None
    underline: bool
    strike: bool
    rect: QRectF = field(default_factory=QRectF)


@dataclass
class _Column:
    start: int
    end: int
    width: float
    used: float
    alignment: object
    glyphs: list[_Glyph] = field(default_factory=list)
    rect: QRectF = field(default_factory=QRectF)
    carets: list[tuple[int, QRectF]] = field(default_factory=list)
    separator: int | None = None


class VerticalLayout:
    """Lay upright graphemes top-to-bottom in columns ordered right-to-left.

    ``left/center/right`` paragraph alignment maps to top/center/bottom. Line
    spacing controls the column pitch, and paragraph spacing is horizontal.
    Latin letters and digits remain upright, one grapheme per cell. Brackets
    and long marks rotate; Japanese commas/stops sit at the upper right.
    """

    def __init__(self, document, width, height, margin):
        self.document = document
        self.width, self.height = float(width), float(height)
        self.margin = max(0.0, float(margin))
        self.columns: list[_Column] = []
        self.glyphs: list[_Glyph] = []
        self._carets = {}
        self._position_columns = {}
        self.overflow = False
        available = max(0.0, self.height - self.margin * 2)
        right = self.width - self.margin
        block = document.begin()
        while block.isValid():
            fmt = block.blockFormat()
            spacing = (fmt.lineHeight() / 100 if fmt.lineHeightType() ==
                       QTextBlockFormat.ProportionalHeight.value else 1.0)
            spacing = max(0.01, spacing)
            right -= fmt.topMargin()
            fragments = []
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    fragments.append((fragment.position(), fragment.position() +
                                      fragment.length(), fragment.charFormat()))
                iterator += 1
            default_format = QTextCursor(block).charFormat()
            default_font = default_format.font().resolve(document.defaultFont())
            default_width = max(1.0, QFontMetricsF(default_font).horizontalAdvance("\u3000"))
            column = _Column(block.position(), block.position(), default_width,
                             0.0, fmt.alignment())
            columns = [column]
            fragment_index = 0
            for start, end, text in grapheme_spans(block.text()):
                start += block.position()
                end += block.position()
                while fragment_index + 1 < len(fragments) and start >= fragments[fragment_index][1]:
                    fragment_index += 1
                char_fmt = fragments[fragment_index][2] if fragments else default_format
                if text == "\u2028":
                    # Shift+Enter starts a column within the same paragraph.
                    # Keep both sides of the separator as cursor positions,
                    # including consecutive breaks and a final empty column.
                    column.end = start
                    column.separator = start
                    font = char_fmt.font().resolve(document.defaultFont())
                    cell = max(1.0, QFontMetricsF(font).horizontalAdvance("\u3000"))
                    column = _Column(end, end, cell, 0.0, fmt.alignment())
                    columns.append(column)
                    continue
                glyph = self._make_glyph(start, end, text, char_fmt)
                if column.glyphs and column.used + glyph.advance > available + 0.001:
                    column = _Column(start, start, glyph.width, 0.0, fmt.alignment())
                    columns.append(column)
                column.glyphs.append(glyph)
                column.width = max(column.width, glyph.width)
                column.used += glyph.advance
                column.end = end
            # Empty blocks have a real, clickable line, including a trailing Enter.
            if block.next().isValid():
                columns[-1].separator = block.position() + block.length() - 1
            for column in columns:
                self._place_column(column, right, available)
                self.columns.append(column)
                right -= column.width * spacing
            # Paragraph spacing follows the final column's physical edge.
            right += columns[-1].width * (spacing - 1)
            right -= fmt.bottomMargin()
            block = block.next()
        self.boundaries = tuple(sorted(self._carets))
        self.content_width = max(0.0, self.width - self.margin - right)
        self.content_height = max((column.used for column in self.columns), default=0.0)

    def _make_glyph(self, start, end, text, fmt):
        font = fmt.font().resolve(self.document.defaultFont())
        underline, strike = font.underline(), font.strikeOut()
        # Decorations follow the vertical writing direction instead of being
        # drawn as a separate horizontal dash under every character.
        font.setUnderline(False)
        font.setStrikeOut(False)
        layout = QTextLayout(text if text != "\t" else "\u3000", font)
        option = self.document.defaultTextOption()
        option.setUseDesignMetrics(True)
        layout.setTextOption(option)
        layout.setCacheEnabled(True)
        layout.beginLayout()
        line = layout.createLine()
        line.setLineWidth(100000)
        layout.endLayout()
        em = max(1.0, QFontMetricsF(font).horizontalAdvance("\u3000"))
        cell = max(em, line.naturalTextWidth())
        color = fmt.foreground().color() if fmt.foreground().style() != Qt.NoBrush else QColor("#253345")
        background = fmt.background().color() if fmt.background().style() != Qt.NoBrush else None
        return _Glyph(start, end, text, layout, cell, cell, color, background, underline, strike)

    def _place_column(self, column, right, available):
        spare = max(0.0, available - column.used)
        offset = spare / 2 if column.alignment & Qt.AlignHCenter else spare if column.alignment & Qt.AlignRight else 0
        y = self.margin + offset
        # A blank paragraph still occupies one visible cell for alignment/hit tests.
        if not column.glyphs:
            spare = max(0.0, available - column.width)
            y = self.margin + (spare / 2 if column.alignment & Qt.AlignHCenter else
                               spare if column.alignment & Qt.AlignRight else 0)
        column.rect = QRectF(right - column.width, y, column.width, column.used or column.width)
        column_index = len(self.columns)
        positions = [(column.start, y)]
        for glyph in column.glyphs:
            glyph.rect = QRectF(right - column.width, y, column.width, glyph.advance)
            self.glyphs.append(glyph)
            y += glyph.advance
            positions.append((glyph.end, y))
        for position, caret_y in positions:
            caret = QRectF(column.rect.left(), caret_y, column.width, 1.5)
            column.carets.append((position, caret))
            # At an automatic wrap, prefer the next column's start.
            self._carets[position] = caret
            self._position_columns[position] = column_index
        if column.rect.left() < self.margin - 0.001 or column.used > available + 0.001:
            self.overflow = True

    def normalize_position(self, position):
        """Clamp/snap an external QTextCursor position to a grapheme boundary."""
        if not self.boundaries:
            return 0
        index = bisect_left(self.boundaries, int(position))
        if index == len(self.boundaries):
            return self.boundaries[-1]
        if index and position - self.boundaries[index - 1] < self.boundaries[index] - position:
            return self.boundaries[index - 1]
        return self.boundaries[index]

    def caret_rect(self, position):
        return QRectF(self._carets.get(self.normalize_position(position),
                                     QRectF(self.width - self.margin - 20, self.margin, 20, 1.5)))

    def hit_test(self, point):
        if not self.columns:
            return 0
        column = min(self.columns, key=lambda value: abs(value.rect.center().x() - point.x()))
        return min(column.carets, key=lambda value: abs(value[1].top() - point.y()))[0]

    def move_cursor(self, position, direction):
        position = self.normalize_position(position)
        if not self.boundaries:
            return position
        if direction in ("up", "down"):
            index = self.boundaries.index(position) + (-1 if direction == "up" else 1)
            return self.boundaries[max(0, min(len(self.boundaries) - 1, index))]
        column_index = self._position_columns[position]
        column = self.columns[column_index]
        if direction in ("home", "end"):
            return column.carets[0 if direction == "home" else -1][0]
        if direction in ("left", "right"):
            target_index = column_index + (1 if direction == "left" else -1)
            if 0 <= target_index < len(self.columns):
                y = self._carets[position].top()
                return min(self.columns[target_index].carets,
                           key=lambda value: abs(value[1].top() - y))[0]
        return position

    def paint(self, painter, selection_start=None, selection_end=None):
        low, high = sorted((selection_start or 0, selection_end or 0))
        selection_color = QColor("#3478c4")
        painter.save()
        for glyph in self.glyphs:
            selected = low < glyph.end and high > glyph.start
            if selected or glyph.background is not None:
                painter.fillRect(glyph.rect, selection_color if selected else glyph.background)
            painter.save()
            painter.setPen(QColor("white") if selected else glyph.color)
            line = glyph.layout.lineAt(0)
            center = glyph.rect.center()
            painter.translate(center)
            if glyph.text in _ROTATED:
                painter.rotate(90)
            x = -line.naturalTextWidth() / 2
            y = -line.height() / 2
            if glyph.text in _CORNER:
                # Move the original glyph's lower-left ink into the upper-right
                # corner, without depending on rare vertical-form font glyphs.
                x += glyph.width * 0.48
                y -= glyph.advance * 0.48
            glyph.layout.draw(painter, QPointF(x, y))
            painter.restore()
            painter.setPen(QPen(QColor("white") if selected else glyph.color, max(1.0, glyph.width / 22)))
            if glyph.underline:
                x = glyph.rect.right() - 1
                painter.drawLine(QPointF(x, glyph.rect.top()), QPointF(x, glyph.rect.bottom()))
            if glyph.strike:
                x = glyph.rect.center().x()
                painter.drawLine(QPointF(x, glyph.rect.top()), QPointF(x, glyph.rect.bottom()))
        for column in self.columns:
            if column.separator is not None and low <= column.separator < high:
                caret = column.carets[-1][1]
                painter.fillRect(QRectF(caret.x(), caret.y(), caret.width(), 4), selection_color)
        painter.restore()
