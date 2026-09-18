"""Shared object gestures and code-native shape/image painting."""
import base64
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import QApplication, QGraphicsItem

from .model import ImageBox, ShapeBox, GroupBox


def decode_image(obj):
    data = base64.b64decode(obj.image_data, validate=True)
    image = QImage.fromData(data, "PNG")
    if image.isNull() or max(image.width(), image.height()) > 12000 or image.width()*image.height() > 24_000_000:
        raise ValueError("삽입 이미지가 손상되었거나 너무 큽니다.")
    return image


def validate_images(page):
    for obj in page.objects:
        if isinstance(obj, ImageBox):
            decode_image(obj)


class BoxInteraction:
    def boundingRect(self):
        return QRectF(-8, -34, self.model.width + 16, self.model.height + 60)

    def shape(self):
        path = QPainterPath()
        path.addRect(QRectF(0, 0, self.model.width, self.model.height))
        if self.isSelected() and not self.editing and not self.model.locked:
            path.addRect(self.resize_handle())
            path.addEllipse(self.rotate_handle())
        return path

    def resize_handle(self):
        return QRectF(self.model.width - 7, self.model.height - 7, 14, 14)

    def rotate_handle(self):
        return QRectF(self.model.width / 2 - 7, -30, 14, 14)

    def paint_controls(self, painter, overflow=False):
        if not self.scene() or not self.scene().show_controls or not self.isSelected():
            return
        pen = QPen(QColor("#9B6C35" if overflow else "#8A95A3" if self.model.locked else "#0F6CBD"), 1.5)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(0, 0, self.model.width, self.model.height))
        if self.model.locked:
            painter.drawText(QPointF(3, -8), "잠금")
        elif not self.editing:
            painter.drawLine(QPointF(self.model.width / 2, 0), QPointF(self.model.width / 2, -16))
            painter.setBrush(QColor("white"))
            painter.drawRect(self.resize_handle())
            painter.drawEllipse(self.rotate_handle())
        if overflow:
            painter.drawText(QPointF(3, self.model.height + 19), "글자 넘침 · 상자를 늘려 주세요")

    def mousePressEvent(self, event):
        if self.editing or not self.editor.can_interact(self.model) or event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        self._drag_press_position = event.screenPos()
        self._drag_started = False
        self.gesture = None
        self.start_size = (self.model.width, self.model.height)
        self.start_scale = self.model.scale
        self.start_transform = QTransform(self.sceneTransform())
        self.start_anchor = self.mapToScene(QPointF())
        if self.isSelected() and self.resize_handle().contains(event.pos()):
            self.gesture = "resize"
        elif self.isSelected() and self.rotate_handle().contains(event.pos()):
            self.gesture = "rotate"
        if self.gesture:
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        from .layout_tools import keep_anchor
        if self.editing:
            super().mouseMoveEvent(event)
            return
        if not self.editor.can_interact(self.model):
            event.accept()
            return
        press_position = getattr(self, "_drag_press_position", None)
        if press_position is None or not event.buttons() & Qt.LeftButton:
            event.accept()
            return
        if not self._drag_started:
            # Measure the pointer in screen pixels so selection jitter cannot
            # move or snap a box, even when the page is zoomed out.
            if (event.screenPos() - press_position).manhattanLength() < QApplication.startDragDistance():
                event.accept()
                return
            self.editor.begin_operation()
            self._drag_started = True
        if self.gesture == "resize":
            if isinstance(self.model, GroupBox):
                local = self.start_transform.inverted()[0].map(event.scenePos())
                factor = max(local.x()/self.start_size[0], local.y()/self.start_size[1])
                self.model.scale = max(.01, min(100, self.start_scale*factor))
                self.setScale(self.model.scale)
                keep_anchor(self, self.start_anchor)
                self.editor.changed()
                return
            self.prepareGeometryChange()
            anchor = self.mapToScene(QPointF(0, 0))
            width = max(24, min(16000, event.pos().x()))
            height = max(24, min(16000, event.pos().y()))
            aspect = isinstance(self.model, ImageBox) and self.model.aspect_locked
            if aspect or event.modifiers() & Qt.ShiftModifier:
                ratio = self.start_size[0] / self.start_size[1]
                width = max(width, 24 * ratio)
                height = width / ratio
                if max(width, height) > 16000:
                    factor = 16000 / max(width, height)
                    width, height = width * factor, height * factor
            self.model.width, self.model.height = width, height
            if hasattr(self, "setTextWidth"):
                self.setTextWidth(width)
            self.setTransformOriginPoint(width / 2, height / 2)
            keep_anchor(self, anchor)
            self.update()
            self.editor.changed()
        elif self.gesture == "rotate":
            pointer = self.parentItem().mapFromScene(event.scenePos()) if self.parentItem() else event.scenePos()
            delta = pointer - (self.pos()+self.transformOriginPoint())
            degrees = math.degrees(math.atan2(delta.y(), delta.x())) + 90
            if event.modifiers() & Qt.ShiftModifier:
                degrees = round(degrees / 15) * 15
            self.setRotation(degrees)
            self.model.rotation = degrees
            self.editor.changed()
        else:
            super().mouseMoveEvent(event)
            self.editor.snap_drag(event.modifiers())

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            super().mouseReleaseEvent(event)
            return
        gesture, self.gesture = self.gesture, None
        dragged = getattr(self, "_drag_started", False)
        self._drag_press_position = None
        self._drag_started = False
        self.scene().snap_guides = []
        super().mouseReleaseEvent(event)
        if dragged and not self.editing:
            self.editor.finish_operation("크기 변경" if gesture == "resize" else "회전" if gesture else "이동")

    def hoverMoveEvent(self, event):
        if self.isSelected() and not self.editing and not self.model.locked:
            self.setCursor(Qt.SizeFDiagCursor if self.resize_handle().contains(event.pos()) else
                           Qt.CrossCursor if self.rotate_handle().contains(event.pos()) else Qt.SizeAllCursor)
        else:
            self.setCursor(Qt.IBeamCursor if self.editing else Qt.ArrowCursor)
        super().hoverMoveEvent(event)


class VisualItem(BoxInteraction, QGraphicsItem):
    def __init__(self, model, editor):
        super().__init__()
        self.model, self.editor = model, editor
        self.editing = False
        self.gesture = None
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsFocusable)
        self.setFlag(QGraphicsItem.ItemIsMovable, not model.locked)
        self.setAcceptHoverEvents(True)
        self.setPos(model.x, model.y)
        self.setTransformOriginPoint(model.width / 2, model.height / 2)
        self.setRotation(model.rotation)
        self.setScale(model.scale)
        self.setZValue(model.z + 1)
        self.image = decode_image(model) if isinstance(model, ImageBox) else None

    def paint(self, painter, option, widget=None):
        obj = self.model
        box = QRectF(0, 0, obj.width, obj.height)
        painter.save()
        painter.setOpacity(painter.opacity()*obj.opacity)
        if isinstance(obj, ImageBox):
            image = self.image
            crop = obj.crop or [0, 0, 1, 1]
            area = QRectF(crop[0]*image.width(), crop[1]*image.height(), crop[2]*image.width(), crop[3]*image.height())
            if obj.flip_h or obj.flip_v:
                painter.translate(obj.width if obj.flip_h else 0, obj.height if obj.flip_v else 0)
                painter.scale(-1 if obj.flip_h else 1, -1 if obj.flip_v else 1)
            target = QRectF(box)
            if obj.aspect_locked:
                fitted = area.size()
                fitted.scale(box.size(), Qt.KeepAspectRatio)
                target = QRectF((box.width()-fitted.width())/2, (box.height()-fitted.height())/2, fitted.width(), fitted.height())
            painter.drawImage(target, image, area)
        else:
            painter.setPen(QPen(QColor(obj.stroke), obj.stroke_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin) if obj.stroke_width else Qt.NoPen)
            painter.setBrush(QColor(obj.fill) if obj.fill != "transparent" else Qt.NoBrush)
            inset = obj.stroke_width / 2
            inner = box.adjusted(inset, inset, -inset, -inset)
            if obj.shape == "ellipse":
                painter.drawEllipse(inner)
            elif obj.shape == "roundrect":
                painter.drawRoundedRect(inner, min(18, obj.width/5), min(18, obj.height/5))
            elif obj.shape in ("line", "arrow"):
                y = obj.height/2
                painter.drawLine(QPointF(inset, y), QPointF(obj.width-inset, y))
                if obj.shape == "arrow":
                    head = min(obj.height/2-inset, max(9, obj.stroke_width*4))
                    painter.drawLine(QPointF(obj.width-inset-head, y-head), QPointF(obj.width-inset, y))
                    painter.drawLine(QPointF(obj.width-inset-head, y+head), QPointF(obj.width-inset, y))
            else:
                painter.drawRect(inner)
        painter.restore()
        self.paint_controls(painter)


class GroupItem(BoxInteraction, QGraphicsItem):
    def __init__(self, model, editor):
        super().__init__()
        self.model, self.editor = model, editor
        self.editing, self.gesture = False, None
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsFocusable)
        self.setPos(model.x, model.y)
        self.setTransformOriginPoint(model.width/2, model.height/2)
        self.setRotation(model.rotation)
        self.setScale(model.scale)
        self.setOpacity(model.opacity)
        self.setZValue(model.z+1)
        self.setHandlesChildEvents(True)
        self.setAcceptHoverEvents(True)
        self.setToolTip("그룹 · 더블클릭해서 안쪽 편집")

    def paint(self, painter, option, widget=None):
        self.paint_controls(painter)

    def mouseDoubleClickEvent(self, event):
        self.editor.enter_group(self.model.id)
        event.accept()
