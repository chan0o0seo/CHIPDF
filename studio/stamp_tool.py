"""Aligned clone stamping on the page background, committed one stroke at a time."""
from base64 import b64encode
from io import BytesIO

from PIL import Image
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem

from .model import BackgroundPatch


TILE_SIZE = 256


def _pil_image(image, mode):
    image = image.convertToFormat(QImage.Format_RGBA8888 if mode == 'RGBA' else QImage.Format_Grayscale8)
    return Image.frombytes(mode, (image.width(), image.height()), bytes(image.constBits()),
                           'raw', mode, image.bytesPerLine())


def _encoded_png(image):
    stream = BytesIO()
    image.save(stream, 'PNG')
    return b64encode(stream.getvalue()).decode('ascii')


class CloneStamp:
    def init_stamp(self):
        self._stamp_page = None
        self._stamp_anchor = None
        self._stamp_offset = None
        self._stamp_last = None
        self._stamp_source = QImage()
        self._stamp_tiles = {}

    def _stamp_on_current_page(self):
        if not self.editor.project:
            return False
        return self._stamp_page == (self.editor.project.id, self.editor.current_page.id)

    def cancel_stamp_stroke(self):
        if not hasattr(self, '_stamp_tiles'):
            return
        for tile in self._stamp_tiles.values():
            self.scene().removeItem(tile['item'])
        self._stamp_tiles.clear()
        self._stamp_last = None
        self._stamp_source = QImage()

    def stamp_press(self, point, modifiers):
        if not self._page_rect().contains(point):
            return
        self._brush_cursor = point
        if not self._stamp_on_current_page():
            self._stamp_anchor = self._stamp_offset = None
            self._stamp_page = (self.editor.project.id, self.editor.current_page.id)
        if modifiers & Qt.AltModifier:
            self.cancel_stamp_stroke()
            self._stamp_anchor = point.toPoint()
            self._stamp_offset = None
            self.editor.status.setText('도장 원본 지정됨 · 복제할 위치에서 드래그하세요 · Alt+클릭으로 다시 지정')
            return
        if self._stamp_anchor is None:
            self.editor.status.setText('Alt를 누른 채 복제할 원본 지점을 먼저 클릭하세요')
            return
        if len(self.editor.current_page.background_patches) >= 2000:
            self.editor.status.setText('이 카드의 배경 편집 기록이 가득 찼습니다')
            return
        self.cancel_stamp_stroke()
        self.editor.refresh_background()
        # QImage shares immutable pixels here. Every tile samples the same
        # pre-stroke image so painting across the donor cannot feed back.
        self._stamp_source = QImage(self.editor.background_image)
        if self._stamp_source.isNull():
            return
        if self._stamp_offset is None:
            self._stamp_offset = self._stamp_anchor - point.toPoint()
        self._stamp_last = QPointF(point)
        self._paint_stamp_segment(point, point)

    def stamp_move(self, point, buttons):
        self._brush_cursor = point if self._page_rect().contains(point) else None
        if self._stamp_last is not None:
            if buttons & Qt.LeftButton:
                self._paint_stamp_segment(self._stamp_last, point)
                self._stamp_last = QPointF(point)
            else:
                self.cancel_stamp_stroke()

    def _paint_stamp_segment(self, start, end):
        offset = self._stamp_offset
        page = self._stamp_source.rect()
        valid = page.intersected(page.translated(-offset))
        radius = self.brush_size / 2 + 1
        bounds = QRectF(start, end).normalized().adjusted(-radius, -radius, radius, radius).toAlignedRect()
        bounds = bounds.intersected(valid)
        if bounds.isEmpty():
            return
        for y in range(bounds.top() // TILE_SIZE, bounds.bottom() // TILE_SIZE + 1):
            for x in range(bounds.left() // TILE_SIZE, bounds.right() // TILE_SIZE + 1):
                key = (x, y)
                tile = self._stamp_tiles.get(key)
                if tile is None:
                    if (len(self._stamp_tiles) >= 128 or
                            len(self.editor.current_page.background_patches) + len(self._stamp_tiles) >= 2000):
                        self.editor.status.setText('한 획의 범위가 큽니다 · 버튼을 놓은 뒤 이어서 칠해 주세요')
                        continue
                    rect = QRect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE).intersected(page)
                    mask = QImage(rect.size(), QImage.Format_Grayscale8)
                    mask.fill(0)
                    preview = self._stamp_source.copy(rect).convertToFormat(QImage.Format_ARGB32_Premultiplied)
                    sample = self._stamp_source.copy(rect.translated(offset)).convertToFormat(QImage.Format_RGBA8888)
                    item = QGraphicsPixmapItem()
                    item.setPos(rect.topLeft())
                    item.setZValue(-0.5)
                    item.setAcceptedMouseButtons(Qt.NoButton)
                    self.scene().addItem(item)
                    tile = {'rect': rect, 'mask': mask, 'preview': preview,
                            'sample': sample, 'brush': QBrush(QPixmap.fromImage(sample)), 'item': item}
                    self._stamp_tiles[key] = tile
                origin = tile['rect'].topLeft()
                a, b = start - QPointF(origin), end - QPointF(origin)
                for image, brush in ((tile['mask'], QBrush(QColor('white'))),
                                     (tile['preview'], tile['brush'])):
                    painter = QPainter(image)
                    painter.setCompositionMode(QPainter.CompositionMode_Source)
                    painter.setClipRect(valid.translated(-origin))
                    painter.setPen(QPen(brush, self.brush_size, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                    if a == b:
                        painter.drawPoint(a)
                    else:
                        painter.drawLine(a, b)
                    painter.end()
                tile['item'].setPixmap(QPixmap.fromImage(tile['preview']))

    def stamp_release(self, point):
        if self._stamp_last is None:
            return
        self._paint_stamp_segment(self._stamp_last, point)
        records = []
        try:
            for tile in self._stamp_tiles.values():
                mask = _pil_image(tile['mask'], 'L')
                if not mask.getbbox():
                    continue
                rect = tile['rect']
                records.append(BackgroundPatch(
                    rect=[rect.x(), rect.y(), rect.width(), rect.height()],
                    patch=_encoded_png(_pil_image(tile['sample'], 'RGBA')),
                    mask=_encoded_png(mask)))
        except (OSError, ValueError, MemoryError) as exc:
            self.editor.status.setText(f'도장 획을 적용하지 못했습니다 · {exc}')
            return
        finally:
            self.cancel_stamp_stroke()
        if not records:
            return
        self.editor.begin_operation()
        self.editor.current_page.background_patches.extend(records)
        self.editor.background_signature = None
        self.editor.refresh_background()
        self.editor.finish_operation('도장')
        self.editor.status.setText('도장 적용됨 · Ctrl+Z로 한 획 취소 · Alt+클릭으로 원본 다시 지정')

    def draw_stamp_source(self, painter):
        if not self._stamp_on_current_page() or self._stamp_anchor is None or self._pan_position is not None:
            return
        source = QPointF(self._stamp_anchor)
        if self._stamp_offset is not None and self._brush_cursor is not None:
            source = self._brush_cursor + QPointF(self._stamp_offset)
        arm = 7 / max(.05, self.transform().m11())
        for color, width in (('white', 3), ('#226f92', 1)):
            pen = QPen(QColor(color), width)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawLine(source - QPointF(arm, 0), source + QPointF(arm, 0))
            painter.drawLine(source - QPointF(0, arm), source + QPointF(0, arm))
            painter.drawEllipse(source, self.brush_size / 2, self.brush_size / 2)
