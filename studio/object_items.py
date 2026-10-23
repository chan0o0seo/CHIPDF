"""Shared object gestures and code-native shape/image painting."""
import base64
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import QApplication, QGraphicsItem

from .model import ImageBox, ShapeBox, GroupBox, TextBox


def decode_image(obj):
    data = base64.b64decode(obj.image_data, validate=True)
    image = QImage.fromData(data, "PNG")
    if image.isNull() or max(image.width(), image.height()) > 12000 or image.width()*image.height() > 24_000_000:
        raise ValueError("삽입 이미지가 손상되었거나 너무 큽니다.")
    return image


def adjusted_image(item):
    """The inserted image with brightness, contrast and saturation applied, cached per setting."""
    obj = item.model
    key = (id(item.image), obj.brightness, obj.contrast, obj.saturation)
    cached = getattr(item, '_adjusted', None)
    if cached and cached[0] == key:
        return cached[1]
    image = item.image
    if obj.brightness or obj.contrast or obj.saturation:
        from io import BytesIO
        from PIL import Image, ImageEnhance
        source = Image.open(BytesIO(base64.b64decode(obj.image_data))).convert('RGBA')
        alpha = source.getchannel('A')
        rgb = source.convert('RGB')
        for enhancer, value in ((ImageEnhance.Brightness, obj.brightness), (ImageEnhance.Contrast, obj.contrast),
                                (ImageEnhance.Color, obj.saturation)):
            if value:
                rgb = enhancer(rgb).enhance(1 + value/100)
        rgb.putalpha(alpha)
        encoded = BytesIO()
        rgb.save(encoded, 'PNG')
        image = QImage.fromData(encoded.getvalue(), 'PNG')
    item._adjusted = (key, image)
    return image


def validate_images(page):
    for obj in page.objects:
        if isinstance(obj, ImageBox):
            decode_image(obj)


_HANDLE_POINTS = {"tl": (0, 0), "t": (.5, 0), "tr": (1, 0), "r": (1, .5),
                  "br": (1, 1), "b": (.5, 1), "bl": (0, 1), "l": (0, .5)}
_HANDLE_CURSORS = {"tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor, "tr": Qt.SizeBDiagCursor,
                   "bl": Qt.SizeBDiagCursor, "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
                   "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor}


class BoxInteraction:
    # Handles keep the same size on screen at every zoom level.
    HANDLE_PIXELS = 10
    ROTATE_PIXELS = 26

    def _screen_scale(self):
        scene = self.scene()
        views = scene.views() if scene else []
        transform = self.sceneTransform()
        scale = math.hypot(transform.m11(), transform.m12()) or 1
        if views:
            view = views[0].transform()
            scale *= math.hypot(view.m11(), view.m12()) or 1
        return max(1e-4, scale)

    def boundingRect(self):
        scale = self._screen_scale()
        pad = max(8, self.HANDLE_PIXELS / scale)
        top = max(34, (self.ROTATE_PIXELS + self.HANDLE_PIXELS) / scale)
        return QRectF(-pad, -top, self.model.width + pad * 2, self.model.height + top + max(26, pad))

    def refresh(self):
        self.prepareGeometryChange()
        self.update()

    def shape(self):
        path = QPainterPath()
        # Handles overlap the box edge; odd-even filling would hollow out the overlap.
        path.setFillRule(Qt.WindingFill)
        path.addRect(QRectF(0, 0, self.model.width, self.model.height))
        if self.isSelected() and not self.editing and not self.model.locked:
            for rect in self.handle_rects().values():
                path.addRect(rect)
            path.addEllipse(self.rotate_handle())
        return path

    def handle_names(self):
        # Groups scale and locked-ratio images keep their proportions: corners only.
        if isinstance(self.model, GroupBox) or (isinstance(self.model, ImageBox) and self.model.aspect_locked):
            return ("tl", "tr", "br", "bl")
        return tuple(_HANDLE_POINTS)

    def handle_rects(self):
        size = self.HANDLE_PIXELS / self._screen_scale()
        rects = {}
        for name in self.handle_names():
            fx, fy = _HANDLE_POINTS[name]
            rects[name] = QRectF(fx * self.model.width - size / 2, fy * self.model.height - size / 2, size, size)
        return rects

    def handle_at(self, position):
        for name, rect in self.handle_rects().items():
            grow = rect.width() * .35
            if rect.adjusted(-grow, -grow, grow, grow).contains(position):
                return name
        return None

    def resize_handle(self):
        return self.handle_rects()["br"]

    def rotate_handle(self):
        scale = self._screen_scale()
        size = self.HANDLE_PIXELS * 1.2 / scale
        return QRectF(self.model.width / 2 - size / 2, -self.ROTATE_PIXELS / scale - size / 2, size, size)

    def hoverEnterEvent(self, event):
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def paint_controls(self, painter, overflow=False):
        if not self.scene() or not self.scene().show_controls:
            return
        box = QRectF(0, 0, self.model.width, self.model.height)
        if not self.isSelected():
            if getattr(self, "_hovered", False) and not self.editing:
                pen = QPen(QColor("#5aa0e6"), 1.2)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(box)
            return
        pen = QPen(QColor("#9B6C35" if overflow else "#8A95A3" if self.model.locked else "#0F6CBD"), 1.5)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(box)
        if self.model.locked:
            painter.drawText(QPointF(3, -8), "잠금")
        elif not self.editing:
            rotate = self.rotate_handle()
            painter.drawLine(QPointF(self.model.width / 2, 0), QPointF(self.model.width / 2, rotate.bottom()))
            painter.setBrush(QColor("white"))
            for name, rect in self.handle_rects().items():
                if len(name) == 2:
                    painter.drawEllipse(rect)
                else:
                    radius = rect.width() * .3
                    painter.drawRoundedRect(rect, radius, radius)
            painter.drawEllipse(rotate)
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
        handle = self.handle_at(event.pos()) if self.isSelected() else None
        if handle:
            self.gesture, self.resize_from = "resize", handle
        elif self.isSelected() and self.rotate_handle().contains(event.pos()):
            self.gesture = "rotate"
        if self.gesture:
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        from .layout_tools import move_in_scene
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
            name = getattr(self, "resize_from", "br")
            start_width, start_height = self.start_size
            local = self.start_transform.inverted()[0].map(event.scenePos())
            # The opposite corner or edge stays where it was on the page.
            fixed = QPointF(start_width if "l" in name else 0, start_height if "t" in name else 0)
            target = self.start_transform.map(fixed)
            if isinstance(self.model, GroupBox):
                ratios = [abs(local.x()-fixed.x())/start_width if name[-1] in "lr" else 0,
                          abs(local.y()-fixed.y())/start_height if name[0] in "tb" else 0]
                self.model.scale = max(.01, min(100, self.start_scale*(max(ratios) or 1)))
                self.setScale(self.model.scale)
                move_in_scene(self, target-self.mapToScene(fixed))
                self.editor.changed()
                return
            self.prepareGeometryChange()
            if isinstance(self.model, TextBox):
                # A width chosen by hand wins over growing with the text.
                self.model.auto_width = False
            width = start_width-local.x() if "l" in name else local.x() if "r" in name else start_width
            height = start_height-local.y() if "t" in name else local.y() if "b" in name else start_height
            width, height = max(24, min(16000, width)), max(24, min(16000, height))
            aspect = isinstance(self.model, ImageBox) and self.model.aspect_locked
            if len(name) == 2 and (aspect or event.modifiers() & Qt.ShiftModifier):
                ratio = start_width / start_height
                if width / ratio >= height:
                    height = width / ratio
                else:
                    width = height * ratio
                if min(width, height) < 24:
                    factor = 24 / min(width, height)
                    width, height = width * factor, height * factor
                if max(width, height) > 16000:
                    factor = 16000 / max(width, height)
                    width, height = width * factor, height * factor
            self.model.width, self.model.height = width, height
            if hasattr(self, "setTextWidth"):
                self.setTextWidth(width)
            self.setTransformOriginPoint(width / 2, height / 2)
            moved = QPointF(width if "l" in name else 0, height if "t" in name else 0)
            move_in_scene(self, target-self.mapToScene(moved))
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
            handle = self.handle_at(event.pos())
            self.setCursor(_HANDLE_CURSORS[handle] if handle else
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
            image = adjusted_image(self)
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
            radius = min(obj.corner_radius, target.width()/2, target.height()/2)
            if radius > 0:
                outline = QPainterPath()
                outline.addRoundedRect(target, radius, radius)
                painter.save()
                painter.setClipPath(outline, Qt.IntersectClip)
                painter.drawImage(target, image, area)
                painter.restore()
            else:
                painter.drawImage(target, image, area)
            if obj.border_width > 0:
                inset = obj.border_width/2
                frame = target.adjusted(inset, inset, -inset, -inset)
                painter.setPen(QPen(QColor(obj.border_color), obj.border_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.setBrush(Qt.NoBrush)
                corner = max(0, radius-inset)
                painter.drawRoundedRect(frame, corner, corner)
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
