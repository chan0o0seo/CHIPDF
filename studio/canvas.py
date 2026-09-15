from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QTextCursor
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsTextItem, QGraphicsView, QStyle

from . import richtext
from .object_items import BoxInteraction, VisualItem, GroupItem
from .vertical_editing import VerticalEditing


class CardScene(QGraphicsScene):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.show_controls = True
        self.snap_guides = []

    def drawForeground(self, painter, rect):
        if not self.show_controls or self.editor.comparing:
            return
        painter.save()
        pen = QPen(QColor("#428c91"), 1, Qt.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        if self.editor.active_group_id in self.editor.items_by_id:
            item = self.editor.items_by_id[self.editor.active_group_id]
            polygon = item.mapToScene(QRectF(0, 0, item.model.width, item.model.height))
            painter.setBrush(Qt.NoBrush)
            painter.drawPolygon(polygon)
        pen.setColor(QColor("#d05287"))
        painter.setPen(pen)
        for axis, value in self.snap_guides:
            if axis == "x":
                painter.drawLine(QPointF(value, rect.top()), QPointF(value, rect.bottom()))
            else:
                painter.drawLine(QPointF(rect.left(), value), QPointF(rect.right(), value))
        painter.restore()

    def mousePressEvent(self, event):
        target = self.itemAt(event.scenePos(), self.views()[0].transform())
        if hasattr(target, "model"):
            while target.parentItem() and target.model.parent_id != self.editor.active_group_id:
                target = target.parentItem()
        editing = self.editor.editing_item()
        if editing and target is not editing:
            editing.finish_edit()
        if isinstance(target, (TextItem, VisualItem, GroupItem)) and target.model.parent_id == self.editor.active_group_id and not target.editing and event.modifiers() & Qt.ShiftModifier:
            target.setSelected(not target.isSelected())
            target.setFocus(Qt.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)


class TextItem(VerticalEditing, BoxInteraction, QGraphicsTextItem):
    def __init__(self, model, editor):
        super().__init__()
        self.model = model
        self.editor = editor
        self.editing = False
        self.preedit = False
        self.gesture = None
        self.init_vertical()
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable |
                      QGraphicsItem.ItemIsFocusable | QGraphicsItem.ItemAcceptsInputMethod)
        self.setFlag(QGraphicsItem.ItemIsMovable, not model.locked)
        self.setDefaultTextColor(QColor(model.paragraphs[0].runs[0].style.color))
        richtext.populate(self.document(), model.paragraphs, model.margin)
        self.setTextWidth(model.width)
        self.setPos(model.x, model.y)
        self.setTransformOriginPoint(model.width / 2, model.height / 2)
        self.setRotation(model.rotation)
        self.setScale(model.scale)
        self.setZValue(model.z + 1)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.setAcceptHoverEvents(True)
        if model.source_text:
            self.setToolTip("원문 영역 · 클릭해서 선택하거나 더블클릭해 번역문 입력")
        self.document().contentsChanged.connect(self.content_changed)

    def contains(self, point):
        # QGraphicsTextItem's optimized contains() uses its horizontal text
        # control bounds, even when our shape() covers the full card box.
        return self.shape().contains(point)


    def paint(self, painter, option, widget=None):
        box = QRectF(0, 0, self.model.width, self.model.height)
        painter.save()
        painter.setOpacity(painter.opacity()*self.model.opacity)
        painter.setClipRect(box)
        if self.model.fill != "transparent":
            painter.fillRect(box, QColor(self.model.fill))
        option.state &= ~QStyle.State_Selected
        if self.is_vertical:
            self.paint_vertical(painter)
        else:
            super().paint(painter, option, widget)
        painter.restore()
        self.paint_controls(painter, self.has_overflow())

    def content_changed(self):
        self.model.paragraphs = richtext.extract(self.document(), self.defaultTextColor().name())
        if self.editing:
            self.model.target_origin = "manual"
            self.model.reviewed = False
        self.editor.changed()
        self.update()

    def begin_edit(self):
        if not self.editor.can_interact(self.model):
            return
        self.editor.canvas.cancel_tool()
        previous = self.editor.editing_item()
        if previous and previous is not self:
            previous.finish_edit()
        if not self.editing:
            self.editor.begin_operation()
            self.editing = True
            self.setFlag(QGraphicsItem.ItemIsMovable, False)
            self.setTextInteractionFlags(Qt.TextEditorInteraction)
            self.scene().clearSelection()
            self.setSelected(True)
            self.setFocus(Qt.MouseFocusReason)
            self.editor.update_tools()
            self.update()

    def finish_edit(self):
        if not self.editing:
            return
        # Commit pending OS composition before serializing or switching selection.
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.inputMethod().commit()
        self.clear_vertical_composition()
        self.editing = False
        self.preedit = False
        cursor = self.textCursor()
        cursor.clearSelection()
        self.setTextCursor(cursor)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.content_changed()
        self.editor.finish_operation("글자 편집")
        self.update()

class Canvas(QGraphicsView):
    zoom_changed = Signal(int)
    file_dropped = Signal(str)
    files_dropped = Signal(list)
    region_selected = Signal(QRectF)
    brush_selection_changed = Signal(bool)
    tool_changed = Signal(str)

    def __init__(self, scene, editor):
        super().__init__(scene)
        self.editor = editor
        self.tool = "select"
        self.brush_size = 32.0
        self._region_start = None
        self._region_end = None
        self._brush_last = None
        self._brush_cursor = None
        self._brush_mask = QImage()
        self._brush_overlay = QImage()
        self._has_brush_selection = False
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor("#e8ebe9"))
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)

    def _tool_available(self):
        return (bool(getattr(self.editor, "project", None)) and
                not getattr(self.editor, "comparing", False) and
                not getattr(self.editor, "job", None) and
                not getattr(self.editor, "io_job", None))

    def _page_rect(self):
        if not getattr(self.editor, "project", None):
            return QRectF()
        page = self.editor.current_page
        return QRectF(0, 0, page.width, page.height)

    def _clamp_to_page(self, point):
        bounds = self._page_rect()
        return QPointF(max(bounds.left(), min(bounds.right(), point.x())),
                       max(bounds.top(), min(bounds.bottom(), point.y())))

    def set_tool(self, tool):
        if tool not in ("select", "ocr", "brush"):
            raise ValueError("Unknown canvas tool: " + str(tool))
        if tool != "select" and not self._tool_available():
            return False
        if tool == self.tool:
            return True
        self.clear_tool_selection()
        editing = self.editor.editing_item()
        if editing:
            editing.finish_edit()
        self.tool = tool
        self.setDragMode(QGraphicsView.RubberBandDrag if tool == "select" else QGraphicsView.NoDrag)
        if tool == "select":
            self.viewport().unsetCursor()
        else:
            self.scene().clearSelection()
            self.viewport().setCursor(Qt.CrossCursor if tool == "ocr" else Qt.BlankCursor)
        self.viewport().update()
        self.tool_changed.emit(tool)
        return True

    def set_brush_size(self, size):
        size = float(size)
        if not math.isfinite(size):
            raise ValueError("Brush size must be finite")
        self.brush_size = max(1.0, min(512.0, size))
        self.viewport().update()

    def brush_mask_image(self):
        return self._brush_mask.copy() if self._has_brush_selection else QImage()

    def clear_tool_selection(self):
        self._region_start = self._region_end = None
        self._brush_last = self._brush_cursor = None
        self._brush_mask = QImage()
        self._brush_overlay = QImage()
        had_selection = self._has_brush_selection
        self._has_brush_selection = False
        if had_selection:
            self.brush_selection_changed.emit(False)
        self.viewport().update()

    def cancel_tool(self):
        self.clear_tool_selection()
        self.set_tool("select")

    def _paint_brush_segment(self, start, end):
        bounds = self._page_rect()
        radius = self.brush_size / 2
        stroke_bounds = QRectF(start, end).normalized().adjusted(-radius, -radius, radius, radius)
        if not bounds.intersects(stroke_bounds):
            return
        if self._brush_mask.isNull():
            width, height = math.ceil(bounds.width()), math.ceil(bounds.height())
            self._brush_mask = QImage(width, height, QImage.Format_Grayscale8)
            self._brush_mask.fill(0)
            self._brush_overlay = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
            self._brush_overlay.fill(Qt.transparent)
        # Keep a single binary page mask and update only the latest stroke segment.
        # The separate tinted image avoids recolouring every page pixel on movement.
        for image, color in ((self._brush_mask, QColor("white")),
                             (self._brush_overlay, QColor(220, 66, 103, 95))):
            painter = QPainter(image)
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            painter.setClipRect(bounds)
            painter.setPen(QPen(color, self.brush_size, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            if start == end:
                painter.drawPoint(start)
            else:
                painter.drawLine(start, end)
            painter.end()
        if not self._has_brush_selection:
            self._has_brush_selection = True
            self.brush_selection_changed.emit(True)

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if self.tool == "select" or not self._tool_available():
            return
        painter.save()
        painter.setClipRect(self._page_rect())
        if self.tool == "ocr" and self._region_start is not None:
            pen = QPen(QColor("#258780"), 1, Qt.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(QColor(37, 135, 128, 35))
            painter.drawRect(QRectF(self._region_start, self._region_end).normalized())
        elif self.tool == "brush":
            if not self._brush_overlay.isNull():
                painter.drawImage(QPointF(), self._brush_overlay)
            if self._brush_cursor is not None:
                pen = QPen(QColor("white"), 3)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                radius = self.brush_size / 2
                painter.drawEllipse(self._brush_cursor, radius, radius)
                pen.setColor(QColor("#6b2440"))
                pen.setWidth(1)
                painter.setPen(pen)
                painter.drawEllipse(self._brush_cursor, radius, radius)
        painter.restore()

    def mousePressEvent(self, event):
        if self.tool == "select":
            super().mousePressEvent(event)
            return
        event.accept()
        if not self._tool_available():
            return
        if event.button() != Qt.LeftButton:
            return
        self.setFocus(Qt.MouseFocusReason)
        point = self.mapToScene(event.position().toPoint())
        if self.tool == "ocr":
            self._region_start = self._clamp_to_page(point)
            self._region_end = QPointF(self._region_start)
        elif self._page_rect().contains(point):
            self._brush_last = point
            self._brush_cursor = point
            self._paint_brush_segment(point, point)
        self.viewport().update()

    def mouseMoveEvent(self, event):
        if self.tool == "select":
            super().mouseMoveEvent(event)
            return
        event.accept()
        if not self._tool_available():
            return
        point = self.mapToScene(event.position().toPoint())
        if self.tool == "ocr" and self._region_start is not None:
            self._region_end = self._clamp_to_page(point)
        elif self.tool == "brush":
            self._brush_cursor = point if self._page_rect().contains(point) else None
            if self._brush_last is not None:
                self._paint_brush_segment(self._brush_last, point)
                self._brush_last = point
        self.viewport().update()

    def mouseReleaseEvent(self, event):
        if self.tool == "select":
            super().mouseReleaseEvent(event)
            return
        event.accept()
        if not self._tool_available():
            return
        if event.button() != Qt.LeftButton:
            return
        point = self.mapToScene(event.position().toPoint())
        if self.tool == "ocr" and self._region_start is not None:
            region = QRectF(self._region_start, self._clamp_to_page(point)).normalized()
            self.set_tool("select")
            if region.width() >= 24 and region.height() >= 24:
                self.region_selected.emit(region)
            else:
                self.editor.status.setText('문장 범위가 너무 작습니다 · 가로·세로 24px 이상으로 선택해 주세요')
        elif self.tool == "brush" and self._brush_last is not None:
            self._paint_brush_segment(self._brush_last, point)
            self._brush_last = None
        self.viewport().update()

    def mouseDoubleClickEvent(self, event):
        if self.tool == "select":
            super().mouseDoubleClickEvent(event)
        else:
            self.mousePressEvent(event)

    def leaveEvent(self, event):
        self._brush_cursor = None
        self.viewport().update()
        super().leaveEvent(event)

    def event(self, event):
        if (event.type() == QEvent.ShortcutOverride and getattr(self, "tool", "select") != "select"
                and event.key() in (Qt.Key_Delete, Qt.Key_Backspace, Qt.Key_Left,
                                    Qt.Key_Right, Qt.Key_Up, Qt.Key_Down, Qt.Key_Escape)):
            event.accept()
            return True
        return super().event(event)

    def fit_page(self):
        if self.editor.project:
            page = self.editor.current_page
            self.fitInView(QRectF(-40, -40, page.width + 80, page.height + 80), Qt.KeepAspectRatio)
            self.zoom_changed.emit(round(self.transform().m11() * 100))

    def zoom(self, factor):
        scale = max(0.05, min(8, self.transform().m11() * factor))
        self.scale(scale / self.transform().m11(), scale / self.transform().m11())
        self.zoom_changed.emit(round(scale * 100))

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self.zoom(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
            event.accept()
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event):
        if self.tool != "select":
            if event.key() == Qt.Key_Escape:
                self.cancel_tool()
            event.accept()
            return
        if self.editor.editing_item():
            super().keyPressEvent(event)
            return
        key = event.key()
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            self.editor.delete_selected()
        elif key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            step = 10 if event.modifiers() & Qt.ShiftModifier else 1
            dx = step if key == Qt.Key_Right else -step if key == Qt.Key_Left else 0
            dy = step if key == Qt.Key_Down else -step if key == Qt.Key_Up else 0
            self.editor.nudge(dx, dy)
        elif key == Qt.Key_Escape:
            if self.editor.active_group_id:
                self.editor.leave_group()
            else:
                self.scene().clearSelection()
        else:
            super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and all(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def contextMenuEvent(self, event):
        if self.tool != "select":
            event.accept()
        elif self.editor.editing_item():
            super().contextMenuEvent(event)
        else:
            self.editor.object_context_menu(event.globalPos())

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls and all(url.isLocalFile() for url in urls):
            self.files_dropped.emit([url.toLocalFile() for url in urls])
            event.acceptProposedAction()
