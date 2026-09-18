"""Contextual object tools, placement and structured clipboard commands."""
from copy import deepcopy
from dataclasses import asdict
import base64
import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QMimeData, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QImageReader, QTextCursor
from PySide6.QtWidgets import (QApplication, QColorDialog, QDialog, QDialogButtonBox, QDoubleSpinBox,
                              QFileDialog, QFormLayout, QLabel, QMenu, QToolBar, QToolButton, QVBoxLayout)

from .model import GroupBox, ImageBox, Paragraph, Project, Run, ShapeBox, TextBox, uid
from .layout_tools import move_in_scene
from .object_items import decode_image, validate_images
from .recognition import validate_patches
from .richtext import char_format

MIME = "application/x-translation-studio-objects-v6"
OBJECT_MIMES = (MIME, "application/x-translation-studio-objects-v4", "application/x-translation-studio-objects-v3")


class Editing:
    def menu_button(self, text, menu, bar):
        button = QToolButton()
        button.setText(text)
        button.setMenu(menu)
        button.setPopupMode(QToolButton.InstantPopup)
        bar.addWidget(button)
        return button

    def init_editing(self):
        self.copied_style = None
        self.insert_menu = QMenu("삽입", self)
        self.insert_menu.addAction(self.add_action)
        for name, kind in [("사각형", "rect"), ("둥근 사각형", "roundrect"), ("타원 / 원", "ellipse"), ("선", "line"), ("화살표", "arrow")]:
            self.insert_menu.addAction(self.action(name, lambda checked=False, k=kind: self.add_shape(k)))
        self.image_action = self.action("이미지…", self.choose_image, "Ctrl+Shift+I")
        self.insert_menu.addAction(self.image_action)
        insert = QToolButton()
        insert.setText("＋ 삽입")
        insert.setMenu(self.insert_menu)
        insert.setPopupMode(QToolButton.InstantPopup)
        self.main_toolbar.insertWidget(self.add_action, insert)
        self.main_toolbar.removeAction(self.add_action)
        self.insert_button = insert
        self.copy_action = self.action("복사", self.copy_objects, "Ctrl+C")
        self.cut_action = self.action("잘라내기", lambda: self.copy_objects(cut=True), "Ctrl+X")
        self.paste_action = self.action("붙여넣기", self.paste_objects, "Ctrl+V")
        self.select_all_action = self.action("전체 선택", self.select_all, "Ctrl+A")
        self.edit_menu.addActions([self.copy_action, self.cut_action, self.paste_action, self.select_all_action])
        self.arrange_menu = QMenu("배치", self)
        self.alignment_actions = []
        for label, mode in [("왼쪽 맞춤", "left"), ("가로 가운데 맞춤", "hcenter"), ("오른쪽 맞춤", "right"),
                            ("위쪽 맞춤", "top"), ("세로 가운데 맞춤", "vcenter"), ("아래쪽 맞춤", "bottom"),
                            ("가로 간격 같게", "horizontal"), ("세로 간격 같게", "vertical")]:
            action = self.action(label, lambda checked=False, m=mode: self.arrange(m))
            self.arrange_menu.addAction(action)
            self.alignment_actions.append((action, mode))
        self.arrange_menu.addSeparator()
        self.layer_actions = []
        for label, mode in [("맨 앞으로", "front"), ("한 단계 앞으로", "raise"), ("한 단계 뒤로", "lower"), ("맨 뒤로", "back")]:
            action = self.action(label, lambda checked=False, m=mode: self.reorder(m))
            self.arrange_menu.addAction(action)
            self.layer_actions.append(action)
        self.arrange_menu.addSeparator()
        self.lock_action = self.action("잠금", self.toggle_lock, "Ctrl+L")
        self.unlock_all_action = self.action("모두 잠금 해제", self.unlock_all)
        self.geometry_action = self.action("위치·크기…", self.geometry_dialog)
        self.arrange_menu.addActions([self.lock_action, self.unlock_all_action, self.geometry_action])
        help_action = self.menuBar().actions()[-1]
        self.menuBar().insertMenu(help_action, self.insert_menu)
        self.menuBar().insertMenu(help_action, self.arrange_menu)
        self.menu_button("배치", self.arrange_menu, self.format_bar)
        more = QMenu(self)
        self.text_format_menu = more
        self.strike_action = self.action("취소선", lambda value: self.format_flag("strike", value), checkable=True)
        self.copy_style_action = self.action("서식 복사", self.copy_style)
        self.paste_style_action = self.action("서식 붙여넣기", self.paste_style)
        self.vertical_action = self.action("세로쓰기", lambda value: self.set_writing_mode('vertical-rl' if value else 'horizontal'), checkable=True)
        self.vertical_action.setToolTip('위에서 아래로, 오른쪽 열에서 왼쪽 열로 씁니다. 선택한 상자 전체에 적용합니다.')
        more.addAction(self.vertical_action)
        more.addSeparator()
        more.addActions([self.strike_action, self.copy_style_action, self.paste_style_action])
        self.menu_button("서식", more, self.format_bar)
        self.object_bar = QToolBar("대상 서식")
        self.object_bar.setMovable(False)
        self.context_stack.addWidget(self.object_bar)
        self.shape_fill = self.action("채우기", lambda: self.color_object("fill"))
        self.shape_clear = self.action("채우기 없음", lambda: self.set_property("fill", "transparent", "채우기 없음"))
        self.shape_stroke = self.action("테두리", lambda: self.color_object("stroke"))
        self.object_bar.addActions([self.shape_fill, self.shape_clear, self.shape_stroke])
        self.stroke_box = QDoubleSpinBox()
        self.stroke_box.setRange(0, 30)
        self.stroke_box.setSuffix(" px 선")
        self.stroke_box.editingFinished.connect(lambda: self.set_property("stroke_width", self.stroke_box.value(), "선 두께"))
        self.stroke_widget = self.object_bar.addWidget(self.stroke_box)
        self.image_tools = []
        for label, callback in [("교체", lambda: self.choose_image(replace=True)), ("자르기", self.crop_image),
                                ("좌우 뒤집기", lambda: self.flip_image("flip_h")), ("상하 뒤집기", lambda: self.flip_image("flip_v"))]:
            action = self.action(label, callback)
            self.object_bar.addAction(action)
            self.image_tools.append(action)
        self.aspect_action = self.action("비율 고정", lambda value: self.set_property("aspect_locked", value, "비율 고정"), checkable=True)
        self.object_bar.addAction(self.aspect_action)
        self.image_tools.append(self.aspect_action)
        self.opacity_box = QDoubleSpinBox()
        self.opacity_box.setRange(0, 100)
        self.opacity_box.setSuffix(" % 불투명도")
        self.opacity_box.setDecimals(0)
        self.opacity_box.editingFinished.connect(lambda: self.set_property("opacity", self.opacity_box.value()/100, "불투명도"))
        self.object_bar.addWidget(self.opacity_box)
        self.menu_button("배치", self.arrange_menu, self.object_bar)
        self.object_bar.addActions([self.duplicate_action, self.delete_action])
        QApplication.clipboard().dataChanged.connect(self.update_tools)
        self.update_editing_tools()

    def mutable_selection(self):
        items = self.selected()
        return items if items and not self.comparing and all(self.can_interact(i.model) for i in items) else []

    def update_editing_tools(self):
        if not hasattr(self, "object_bar"):
            return
        selected = self.selected()
        editable = bool(self.project) and not self.comparing
        mutable = bool(self.mutable_selection())
        all_text = bool(selected) and all(isinstance(i.model, TextBox) for i in selected)
        all_shape = bool(selected) and all(isinstance(i.model, ShapeBox) for i in selected)
        all_image = bool(selected) and all(isinstance(i.model, ImageBox) for i in selected)
        self.insert_button.setEnabled(editable)
        self.image_action.setEnabled(editable)
        self.insert_menu.setEnabled(editable)
        panel = self.context_empty
        if editable and selected:
            panel = self.format_bar if all_text and mutable else self.object_bar
        self.context_stack.setCurrentWidget(panel)
        for action in (self.shape_fill, self.shape_clear, self.shape_stroke, self.stroke_widget):
            action.setVisible(all_shape)
            action.setEnabled(mutable)
        for action in self.image_tools:
            action.setVisible(all_image)
            action.setEnabled(mutable and len(selected) == 1)
        self.opacity_box.setEnabled(mutable)
        if selected:
            self.opacity_box.setValue(selected[0].model.opacity*100)
        if all_shape:
            self.stroke_box.setValue(selected[0].model.stroke_width)
        if all_image:
            self.aspect_action.setChecked(selected[0].model.aspect_locked)
        for action, mode in self.alignment_actions:
            action.setEnabled(mutable and (len(selected) >= 3 if mode in ("horizontal", "vertical") else True))
        for action in self.layer_actions:
            action.setEnabled(mutable)
        self.lock_action.setEnabled(editable and bool(selected))
        self.lock_action.setText("잠금 해제" if selected and all(i.model.locked for i in selected) else "잠금")
        self.unlock_all_action.setEnabled(editable and any(o.locked for o in self.current_page.objects) if self.project else False)
        self.geometry_action.setEnabled(mutable and len(selected) == 1)
        self.copy_action.setEnabled(editable and bool(selected))
        self.cut_action.setEnabled(editable and mutable)
        mime = QApplication.clipboard().mimeData()
        self.paste_action.setEnabled(editable and bool(mime) and (any(mime.hasFormat(kind) for kind in OBJECT_MIMES) or mime.hasText() or mime.hasImage()))
        self.select_all_action.setEnabled(editable)
        self.copy_style_action.setEnabled(mutable and all_text and len(selected) == 1)
        self.paste_style_action.setEnabled(mutable and all_text and self.copied_style is not None)
        self.strike_action.setEnabled(mutable and all_text)
        self.vertical_action.setEnabled(mutable and all_text)
        if all_text:
            self.strike_action.setChecked(selected[0].model.paragraphs[0].runs[0].style.strike)

    def add_object(self, obj, label):
        if not self.project or self.comparing:
            return
        self.canvas.cancel_tool()
        self.finish_edit()
        self.begin_operation()
        page = self.current_page
        frame = self.items_by_id[self.active_group_id].model if self.active_group_id else page
        obj.parent_id = self.active_group_id
        obj.x, obj.y = (frame.width-obj.width)/2, (frame.height-obj.height)/2
        obj.z = max((o.z for o in self.scope_objects()), default=-1) + 1
        page.objects.append(obj)
        self.rebuild_scene([obj.id])
        self.finish_operation(label)
        self.canvas.setFocus()
        return obj

    def add_shape(self, kind):
        if self.project:
            page = self.current_page
            width = max(24, min(260, page.width*.45))
            height = 36 if kind in ("line", "arrow") else max(24, min(140, page.height*.25))
            return self.add_object(ShapeBox(shape=kind, width=width, height=height), "도형 추가")

    def choose_image(self, checked=False, replace=False):
        if not self.project:
            return
        path, _ = QFileDialog.getOpenFileName(self, "이미지 교체" if replace else "이미지 삽입", "", "이미지 (*.png *.jpg *.jpeg *.bmp)")
        if path:
            try:
                self.insert_image(Path(path), replace=replace)
            except (OSError, ValueError) as exc:
                self.report_error("이미지를 추가하지 못했습니다", exc)

    def insert_image(self, path, replace=False):
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        size = reader.size()
        if not size.isValid() or max(size.width(), size.height()) > 12000 or size.width()*size.height() > 24_000_000:
            raise ValueError("삽입 이미지는 한 변 12,000px, 총 2,400만 픽셀까지 지원합니다.")
        image = reader.read()
        if image.isNull():
            raise ValueError("이미지를 읽지 못했습니다.")
        return self.insert_qimage(image, replace)

    def insert_qimage(self, image, replace=False):
        from .window import png_bytes
        if not self.project or self.comparing:
            return
        if image.isNull() or max(image.width(), image.height()) > 12000 or image.width()*image.height() > 24_000_000:
            raise ValueError("삽입 이미지는 한 변 12,000px, 총 2,400만 픽셀까지 지원합니다.")
        encoded = base64.b64encode(png_bytes(image)).decode("ascii")
        if len(encoded) > 12_000_000:
            raise ValueError("삽입 이미지 용량이 큽니다. 크기를 줄여 다시 넣어 주세요.")
        if replace:
            items = self.mutable_selection()
            if len(items) != 1 or not isinstance(items[0].model, ImageBox):
                return
            self.finish_edit()
            self.begin_operation()
            obj = items[0].model
            center_y = obj.y + obj.height/2
            obj.image_data, obj.crop = encoded, None
            if obj.aspect_locked:
                obj.height = max(24, min(16000, obj.width*image.height()/image.width()))
                obj.y = center_y-obj.height/2
            self.rebuild_scene([obj.id])
            self.finish_operation("이미지 교체")
            return obj
        page = self.current_page
        scale = min(1, page.width*.45/image.width(), page.height*.45/image.height())
        w, h = image.width()*scale, image.height()*scale
        # Extremely thin assets still need a usable selection handle.
        return self.add_object(ImageBox(width=max(24, w), height=max(24, h), image_data=encoded), "이미지 삽입")

    def set_property(self, name, value, label):
        self.finish_edit()
        items = self.mutable_selection()
        if not items or any(not hasattr(i.model, name) for i in items):
            return
        self.begin_operation()
        for item in items:
            setattr(item.model, name, value)
            if isinstance(item.model, GroupBox) and name == "opacity":
                item.setOpacity(value)
            item.update()
        self.finish_operation(label)

    def color_object(self, key):
        items = self.mutable_selection()
        if not items or not all(isinstance(i.model, ShapeBox) for i in items):
            return
        value = getattr(items[0].model, key)
        color = QColorDialog.getColor(QColor(value if value != "transparent" else "#ffffff"), self, "채우기" if key == "fill" else "테두리")
        if color.isValid():
            self.set_property(key, color.name(), "도형 색")

    def flip_image(self, key):
        items = self.mutable_selection()
        if len(items) == 1 and isinstance(items[0].model, ImageBox):
            self.set_property(key, not getattr(items[0].model, key), "이미지 뒤집기")

    def crop_image(self):
        from .crop_dialog import CropDialog
        items = self.mutable_selection()
        if len(items) != 1 or not isinstance(items[0].model, ImageBox):
            return
        obj = items[0].model
        dialog = CropDialog(decode_image(obj), obj.crop, self)
        if dialog.exec() == QDialog.Accepted:
            self.apply_crop(obj.id, dialog.canvas.crop)

    def apply_crop(self, object_id, crop):
        obj = self.items_by_id[object_id].model
        if self.effective_locked(obj) or self.comparing:
            return
        self.finish_edit()
        trial = deepcopy(self.project)
        next(o for o in trial.pages[self.page_index].objects if o.id == object_id).crop = list(crop)
        Project.from_dict(trial.to_dict())
        self.begin_operation()
        obj.crop = list(crop)
        if obj.aspect_locked:
            image = decode_image(obj)
            center_y = obj.y+obj.height/2
            obj.height = max(24, min(16000, obj.width*image.height()*crop[3]/(image.width()*crop[2])))
            obj.y = center_y-obj.height/2
        self.rebuild_scene([obj.id])
        self.finish_operation("이미지 자르기")

    def arrange(self, mode):
        self.finish_edit()
        items = self.mutable_selection()
        if not items:
            return
        rects = {i: i.mapRectToScene(QRectF(0, 0, i.model.width, i.model.height)) for i in items}
        self.begin_operation()
        if mode in ("horizontal", "vertical"):
            if len(items) < 3:
                self.finish_operation("간격 맞춤")
                return
            horizontal = mode == "horizontal"
            axis = lambda r: r.left() if horizontal else r.top()
            size = lambda r: r.width() if horizontal else r.height()
            ordered = sorted(items, key=lambda i: axis(rects[i]))
            first, last = rects[ordered[0]], rects[ordered[-1]]
            gap = (axis(last)+size(last)-axis(first)-sum(size(r) for r in rects.values()))/(len(items)-1)
            cursor = axis(first)
            for item in ordered:
                delta = cursor-axis(rects[item])
                move_in_scene(item, QPointF(delta if horizontal else 0, 0 if horizontal else delta))
                cursor += size(rects[item])+gap
        else:
            if len(items) == 1:
                if self.active_group_id:
                    group = self.items_by_id[self.active_group_id]
                    target = group.mapRectToScene(QRectF(0, 0, group.model.width, group.model.height))
                else:
                    page = self.current_page
                    target = QRectF(0, 0, page.width, page.height)
            else:
                target = QRectF(rects[items[0]])
                for rect in rects.values():
                    target = target.united(rect)
            for item, rect in rects.items():
                dx = target.left()-rect.left() if mode == "left" else target.right()-rect.right() if mode == "right" else target.center().x()-rect.center().x() if mode == "hcenter" else 0
                dy = target.top()-rect.top() if mode == "top" else target.bottom()-rect.bottom() if mode == "bottom" else target.center().y()-rect.center().y() if mode == "vcenter" else 0
                move_in_scene(item, QPointF(dx, dy))
        self.finish_operation("간격 맞춤" if mode in ("horizontal", "vertical") else "대상 정렬")

    def reorder(self, mode):
        self.finish_edit()
        items = self.mutable_selection()
        if not items:
            return
        self.begin_operation()
        ids = {i.model.id for i in items}
        ordered = sorted(self.scope_objects(), key=lambda o: o.z)
        if mode == "front":
            ordered = [o for o in ordered if o.id not in ids]+[o for o in ordered if o.id in ids]
        elif mode == "back":
            ordered = [o for o in ordered if o.id in ids]+[o for o in ordered if o.id not in ids]
        else:
            indices = range(len(ordered)-2, -1, -1) if mode == "raise" else range(1, len(ordered))
            delta = 1 if mode == "raise" else -1
            for i in indices:
                j = i+delta
                if ordered[i].id in ids and ordered[j].id not in ids:
                    ordered[i], ordered[j] = ordered[j], ordered[i]
        for z, obj in enumerate(ordered):
            obj.z = z
            self.items_by_id[obj.id].setZValue(z+1)
        self.finish_operation("앞뒤 순서")

    def toggle_lock(self):
        self.finish_edit()
        items = self.selected()
        if not items or self.comparing:
            return
        self.begin_operation()
        locked = not all(i.model.locked for i in items)
        for item in items:
            item.model.locked = locked
        ids = [i.model.id for i in items]
        self.rebuild_scene(ids)
        self.finish_operation("잠금" if locked else "잠금 해제")

    def unlock_all(self):
        if not self.project or self.comparing:
            return
        self.finish_edit()
        self.begin_operation()
        for obj in self.current_page.objects:
            obj.locked = False
        self.rebuild_scene()
        self.finish_operation("모두 잠금 해제")

    def geometry_dialog(self):
        items = self.mutable_selection()
        if len(items) != 1:
            return
        obj = items[0].model
        dialog = QDialog(self)
        dialog.setWindowTitle("위치·크기")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        fields = {}
        for key, label in [("x", "가로 위치"), ("y", "세로 위치"), ("width", "너비"), ("height", "높이"), ("rotation", "회전"), ("opacity", "불투명도 %")]:
            field = QDoubleSpinBox()
            field.setRange(24 if key in ("width", "height") else 0 if key == "opacity" else -16000, 100 if key == "opacity" else 16000)
            field.setValue(getattr(obj, key)*(100 if key == "opacity" else obj.scale if key in ("width", "height") else 1))
            fields[key] = field
            form.addRow(label, field)
        layout.addLayout(form)
        if isinstance(obj, GroupBox) or isinstance(obj, ImageBox) and obj.aspect_locked:
            layout.addWidget(QLabel("비율 고정: 너비를 바꾸면 높이도 같은 비율로 바뀝니다."))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.Accepted:
            self.finish_edit()
            self.begin_operation()
            values = {key: field.value() for key, field in fields.items()}
            if isinstance(obj, GroupBox):
                values["scale"] = max(.0001, min(10000, values["width"]/obj.width if abs(values["width"]-obj.width*obj.scale) > .01 else values["height"]/obj.height))
                del values["width"], values["height"]
            else:
                values["width"] /= obj.scale
                values["height"] /= obj.scale
            if isinstance(obj, ImageBox) and obj.aspect_locked:
                if values["width"] != obj.width:
                    values["height"] = max(24, min(16000, values["width"]*obj.height/obj.width))
                else:
                    values["width"] = max(24, min(16000, values["height"]*obj.width/obj.height))
            values["opacity"] /= 100
            for key, value in values.items():
                setattr(obj, key, value)
            self.rebuild_scene([obj.id])
            self.finish_operation("위치·크기")

    def select_all(self):
        item = self.editing_item()
        if item:
            cursor = item.textCursor()
            cursor.select(QTextCursor.Document)
            item.setTextCursor(cursor)
        elif not self.comparing:
            for obj in self.scope_objects():
                self.items_by_id[obj.id].setSelected(True)

    def copy_objects(self, checked=False, cut=False):
        editing = self.editing_item()
        if editing:
            cursor = editing.textCursor()
            if cursor.hasSelection():
                QApplication.clipboard().setText(cursor.selectedText().replace("\u2029", "\n"))
                if cut:
                    cursor.removeSelectedText()
            return
        items = self.mutable_selection() if cut else self.selected()
        if not items or self.comparing:
            return
        self.sync_positions()
        mime = QMimeData()
        ids = self.descendants(i.model.id for i in items)
        copied = [deepcopy(o) for o in self.current_page.objects if o.id in ids]
        for obj in copied:
            if obj.parent_id not in ids:
                obj.parent_id = ""
        mime.setData(MIME, json.dumps({"background": hashlib.sha256(self.original).hexdigest(), "objects": [asdict(o) for o in sorted(copied, key=lambda o: o.z)]}, ensure_ascii=False).encode("utf-8"))
        mime.setText("\n".join(o.text for o in copied if isinstance(o, TextBox)))
        QApplication.clipboard().setMimeData(mime)
        if cut:
            self.delete_selected()

    def paste_objects(self):
        if not self.project or self.comparing:
            return
        mime = QApplication.clipboard().mimeData()
        if not mime:
            return
        editing = self.editing_item()
        if editing:
            if mime.hasText():
                cursor = editing.textCursor()
                cursor.insertText(mime.text())
                editing.setTextCursor(cursor)
            return
        try:
            object_mime = next((kind for kind in OBJECT_MIMES if mime.hasFormat(kind)), None)
            if object_mime:
                raw = bytes(mime.data(object_mime))
                if len(raw) > 60_000_000:
                    raise ValueError("복사한 대상이 너무 큽니다.")
                data = json.loads(raw)
                trial = self.project.to_dict()
                page_ids = {p['id'] for p in trial['pages']}
                for page in trial['pages']:
                    page['objects'] = []
                for obj in data['objects']:
                    if obj.get('kind', 'text') == 'text' and obj.get('link_mode') == 'page' and obj.get('link_page_id') not in page_ids:
                        obj['link_mode'], obj['link_page_id'] = 'none', ''
                trial['pages'][self.page_index]['objects'] = data['objects']
                copied = Project.from_dict(trial).pages[self.page_index]
                same = data.get("background") == hashlib.sha256(self.original).hexdigest()
                for obj in copied.objects:
                    if isinstance(obj, TextBox) and not same:
                        obj.source_text = obj.candidate_text = obj.candidate_source = obj.erase_patch = obj.erase_mask = ""
                        obj.source_rect = obj.erase_rect = None
                        obj.source_confirmed = obj.reviewed = False
                        obj.source_method = obj.candidate_engine = ""
                        obj.speaker = obj.translation_context = ""
                        obj.erase_when_empty = False
                validate_images(copied)
                validate_patches(copied)
                merged = deepcopy(self.project)
                page = merged.pages[self.page_index]
                z = max((o.z for o in self.scope_objects()), default=-1)
                ids = []
                mapping = {o.id: uid() for o in copied.objects}
                for obj in sorted(copied.objects, key=lambda o: o.z):
                    obj.id, obj.locked = mapping[obj.id], False
                    if obj.parent_id:
                        obj.parent_id = mapping[obj.parent_id]
                    else:
                        obj.parent_id = self.active_group_id
                        obj.x, obj.y = obj.x+20, obj.y+20
                        z += 1
                        obj.z = z
                        ids.append(obj.id)
                    page.objects.append(obj)
                Project.from_dict(merged.to_dict())
                self.begin_operation()
                self.project = merged
                self.rebuild_scene(ids)
                self.finish_operation("붙여넣기")
            elif mime.hasImage():
                image = QImage(mime.imageData())
                if not image.isNull():
                    self.insert_qimage(image)
            elif mime.hasText() and mime.text().strip():
                self.add_object(TextBox(paragraphs=[Paragraph([Run(line)]) for line in mime.text().splitlines()]), "텍스트 붙여넣기")
        except (ValueError, TypeError, KeyError) as exc:
            self.status.setText("붙여넣기 실패 · " + str(exc))

    def copy_style(self):
        items = self.mutable_selection()
        if len(items) == 1 and isinstance(items[0].model, TextBox):
            self.copied_style = deepcopy(items[0].model.paragraphs[0].runs[0].style)
            self.update_tools()

    def paste_style(self):
        if self.copied_style:
            self.apply_format(char_format(self.copied_style))

    def object_context_menu(self, position):
        if not self.project or self.comparing:
            return
        menu = QMenu(self)
        menu.addActions([self.copy_action, self.cut_action, self.paste_action, self.duplicate_action, self.delete_action])
        if self.selected():
            menu.addSeparator()
            menu.addMenu(self.arrange_menu)
            if self.current_source():
                menu.addAction(self.source_action)
        menu.exec(position)
