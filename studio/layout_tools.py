"""Group editing, magnetic guides, and paragraph controls in the existing canvas."""
from copy import deepcopy

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel, QVBoxLayout

from .model import GroupBox, TextBox, Project, uid


def move_in_scene(item, delta):
    parent = item.parentItem()
    if parent:
        origin = item.mapToScene(QPointF())
        delta = parent.mapFromScene(origin+delta)-parent.mapFromScene(origin)
    item.moveBy(delta.x(), delta.y())


def keep_anchor(item, scene_anchor):
    move_in_scene(item, scene_anchor-item.mapToScene(QPointF()))


class LayoutTools:
    def init_layout_tools(self):
        self.group_action = self.action("그룹", self.group_selected, "Ctrl+G")
        self.ungroup_action = self.action("그룹 해제", self.ungroup_selected, "Ctrl+Shift+G")
        first = self.arrange_menu.actions()[0]
        self.arrange_menu.insertAction(first, self.group_action)
        self.arrange_menu.insertAction(first, self.ungroup_action)
        self.arrange_menu.insertSeparator(first)
        self.snap_action = self.action("안내선에 맞춤", self.toggle_snap, checkable=True)
        self.snap_action.setChecked(True)
        self.snap_action.setToolTip("드래그할 때 페이지와 다른 대상의 가장자리·가운데에 맞춥니다. Alt를 누르면 잠시 끕니다.")
        self.arrange_menu.addSeparator()
        self.arrange_menu.addAction(self.snap_action)
        self.leave_group_action = self.action("그룹 편집 끝내기", self.leave_group)
        self.main_toolbar.insertAction(self.undo_action, self.leave_group_action)
        self.paragraph_action = self.action("문단 간격·여백…", self.paragraph_dialog)
        self.text_format_menu.addSeparator()
        self.text_format_menu.addAction(self.paragraph_action)
        self.update_layout_tools()

    def scope_objects(self):
        return [o for o in self.current_page.objects if o.parent_id == self.active_group_id] if self.project else []

    def effective_locked(self, obj):
        by_id = {o.id: o for o in self.current_page.objects}
        while obj:
            if obj.locked:
                return True
            obj = by_id.get(obj.parent_id)
        return False

    def can_interact(self, obj):
        return bool(self.project) and not self.comparing and obj.parent_id == self.active_group_id and not self.effective_locked(obj)

    def descendants(self, ids):
        ids = set(ids)
        if not self.project:
            return ids
        while True:
            expanded = ids | {o.id for o in self.current_page.objects if o.parent_id in ids}
            if expanded == ids:
                return ids
            ids = expanded

    def update_layout_tools(self):
        if not hasattr(self, "group_action"):
            return
        items = self.mutable_selection()
        self.group_action.setEnabled(len(items) >= 2)
        self.ungroup_action.setEnabled(bool(items) and all(isinstance(i.model, GroupBox) for i in items))
        self.leave_group_action.setVisible(bool(self.active_group_id))
        self.leave_group_action.setEnabled(not self.comparing)
        self.paragraph_action.setEnabled(bool(items) and all(isinstance(i.model, TextBox) for i in items))

    def configure_scope(self):
        ancestors = set()
        key = self.active_group_id
        while key and key in self.items_by_id:
            ancestors.add(key)
            key = self.items_by_id[key].model.parent_id
        for item in self.items_by_id.values():
            in_scope = item.model.parent_id == self.active_group_id
            item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, in_scope)
            item.setFlag(item.GraphicsItemFlag.ItemIsMovable, in_scope and not self.effective_locked(item.model) and not item.editing)
            if isinstance(item.model, GroupBox):
                item.setHandlesChildEvents(item.model.id not in ancestors)

    def enter_group(self, group_id):
        item = self.items_by_id.get(group_id)
        if not item or not isinstance(item.model, GroupBox) or not self.can_interact(item.model):
            return
        self.finish_edit()
        self.scene.clearSelection()
        self.active_group_id = group_id
        self.configure_scope()
        self.scene.update()
        self.update_tools()
        self.status.setText("그룹 안 편집 · 요소를 선택하세요 · Esc로 끝내기")

    def leave_group(self):
        if not self.active_group_id or self.comparing:
            return
        self.finish_edit()
        old = self.items_by_id[self.active_group_id]
        self.scene.clearSelection()
        self.active_group_id = old.model.parent_id
        self.configure_scope()
        old.setSelected(True)
        self.scene.snap_guides = []
        self.scene.update()
        self.update_tools()

    def group_selected(self):
        self.finish_edit()
        selected = self.mutable_selection()
        if len(selected) < 2:
            return
        rect = QRectF()
        for item in selected:
            box = item.mapRectToParent(QRectF(0, 0, item.model.width, item.model.height))
            rect = box if rect.isNull() else rect.united(box)
        group = GroupBox(x=rect.x(), y=rect.y(), width=max(24, rect.width()), height=max(24, rect.height()),
                         parent_id=self.active_group_id, z=max(i.model.z for i in selected))
        trial = deepcopy(self.project)
        trial.pages[self.page_index].objects.append(group)
        ids = {i.model.id for i in selected}
        for obj in trial.pages[self.page_index].objects:
            if obj.id in ids:
                obj.x -= rect.x()
                obj.y -= rect.y()
                obj.parent_id = group.id
        try:
            Project.from_dict(trial.to_dict())
        except ValueError as exc:
            self.status.setText("그룹 만들기 실패 · " + str(exc))
            return
        self.begin_operation()
        self.project = trial
        self.rebuild_scene([group.id])
        self.finish_operation("그룹")

    def ungroup_selected(self):
        self.finish_edit()
        selected = self.mutable_selection()
        if not selected or not all(isinstance(i.model, GroupBox) for i in selected):
            return
        self.begin_operation()
        objects = self.current_page.objects
        groups = {i.model.id: i for i in selected}
        root_order = sorted(self.scope_objects(), key=lambda o: o.z)
        new_order, selected_ids = [], []
        for obj in root_order:
            if obj.id not in groups:
                new_order.append(obj)
                continue
            group_item = groups[obj.id]
            for child in sorted((o for o in objects if o.parent_id == obj.id), key=lambda o: o.z):
                center = group_item.mapToParent(QPointF(child.x+child.width/2, child.y+child.height/2))
                child.x, child.y = center.x()-child.width/2, center.y()-child.height/2
                child.rotation += obj.rotation
                child.scale *= obj.scale
                child.opacity *= obj.opacity
                child.parent_id = obj.parent_id
                new_order.append(child)
                selected_ids.append(child.id)
        self.current_page.objects = [o for o in objects if o.id not in groups]
        for index, obj in enumerate(new_order):
            obj.z = index
        self.rebuild_scene(selected_ids)
        self.finish_operation("그룹 해제")

    def reframe_groups(self):
        """Normalize changed child bounds without changing their scene transforms."""
        if not self.project:
            return
        def depth(item):
            level, parent = 0, item.parentItem()
            while parent:
                level, parent = level+1, parent.parentItem()
            return level
        groups = sorted((i for i in self.items_by_id.values() if isinstance(i.model, GroupBox)), key=depth, reverse=True)
        for item in groups:
            children = [i for i in item.childItems() if hasattr(i, "model")]
            if not children:
                continue
            bounds = QRectF()
            for child in children:
                rect = child.mapRectToParent(QRectF(0, 0, child.model.width, child.model.height))
                bounds = rect if bounds.isNull() else bounds.united(rect)
            bounds.setWidth(max(24, bounds.width()))
            bounds.setHeight(max(24, bounds.height()))
            obj = item.model
            if max(abs(bounds.x()), abs(bounds.y()), abs(bounds.width()-obj.width), abs(bounds.height()-obj.height)) < 1e-7:
                continue
            center = item.mapToParent(bounds.center())
            item.prepareGeometryChange()
            for child in children:
                child.setPos(child.pos()-bounds.topLeft())
            obj.width, obj.height = bounds.width(), bounds.height()
            item.setTransformOriginPoint(obj.width/2, obj.height/2)
            item.setPos(center-QPointF(obj.width/2, obj.height/2))
            item.update()

    def clone_selection(self, label="복제"):
        roots = self.mutable_selection()
        if not roots:
            return
        self.finish_edit()
        self.begin_operation()
        ids = self.descendants(i.model.id for i in roots)
        clones = [deepcopy(o) for o in self.current_page.objects if o.id in ids]
        mapping = {o.id: uid() for o in clones}
        top = max((o.z for o in self.scope_objects()), default=-1)
        selected_ids = []
        root_ids = {i.model.id for i in roots}
        for obj in sorted(clones, key=lambda o: o.z):
            old = obj.id
            obj.id = mapping[old]
            if old in root_ids:
                obj.x += 20
                obj.y += 20
                top += 1
                obj.z = top
                selected_ids.append(obj.id)
            else:
                obj.parent_id = mapping[obj.parent_id]
        self.current_page.objects.extend(clones)
        self.rebuild_scene(selected_ids)
        self.finish_operation(label)

    def toggle_snap(self, checked):
        self.scene.snap_guides = []
        self.scene.update()

    def snap_drag(self, modifiers=Qt.NoModifier):
        self.scene.snap_guides = []
        if not hasattr(self, "snap_action") or not self.snap_action.isChecked() or modifiers & Qt.AltModifier:
            self.scene.update()
            return
        items = self.mutable_selection()
        if not items:
            return
        selected_ids = {i.model.id for i in items}
        bounds = QRectF()
        for item in items:
            box = item.mapRectToScene(QRectF(0, 0, item.model.width, item.model.height))
            bounds = box if bounds.isNull() else bounds.united(box)
        page = self.current_page
        if self.active_group_id:
            group = self.items_by_id[self.active_group_id]
            target = group.mapRectToScene(QRectF(0, 0, group.model.width, group.model.height))
        else:
            target = QRectF(0, 0, page.width, page.height)
        targets = [target]
        targets += [self.items_by_id[o.id].mapRectToScene(QRectF(0, 0, o.width, o.height)) for o in self.scope_objects() if o.id not in selected_ids]
        threshold = 6 / max(.05, self.canvas.transform().m11())
        deltas = []
        for axis in ("x", "y"):
            anchors = lambda rect: (rect.left(), rect.center().x(), rect.right()) if axis == "x" else (rect.top(), rect.center().y(), rect.bottom())
            candidates = [(abs(dst-src), dst-src, dst) for src in anchors(bounds) for rect in targets for dst in anchors(rect) if abs(dst-src) <= threshold]
            if candidates:
                _, delta, value = min(candidates, key=lambda row: row[0])
                deltas.append(delta)
                self.scene.snap_guides.append((axis, value))
            else:
                deltas.append(0)
        for item in items:
            move_in_scene(item, QPointF(*deltas))
        self.scene.update()

    def paragraph_dialog(self):
        self.finish_edit()
        items = self.mutable_selection()
        if not items or not all(isinstance(i.model, TextBox) for i in items):
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("문단 간격·여백")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("선택한 텍스트 상자의 모든 문단에 적용합니다."))
        form = QFormLayout()
        first = items[0].model
        values = {"line_spacing": first.paragraphs[0].line_spacing, "space_before": first.paragraphs[0].space_before,
                  "space_after": first.paragraphs[0].space_after, "margin": first.margin}
        fields = {}
        for key, label in [("line_spacing", "줄 간격 (배)"), ("space_before", "문단 앞 간격 (px)"), ("space_after", "문단 뒤 간격 (px)"), ("margin", "안쪽 여백 (px)")]:
            field = QDoubleSpinBox()
            field.setRange(.5 if key == "line_spacing" else 0, 4 if key == "line_spacing" else 200 if key == "margin" else 500)
            field.setDecimals(2 if key == "line_spacing" else 1)
            field.setSingleStep(.1 if key == "line_spacing" else 1)
            field.setValue(values[key])
            form.addRow(label, field)
            fields[key] = field
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("적용")
        buttons.button(QDialogButtonBox.Cancel).setText("취소")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.Accepted:
            self.apply_paragraph_settings({key: field.value() for key, field in fields.items()})

    def apply_paragraph_settings(self, settings):
        self.finish_edit()
        items = self.mutable_selection()
        if not items or not all(isinstance(i.model, TextBox) for i in items):
            return
        trial = deepcopy(self.project)
        ids = {i.model.id for i in items}
        for obj in trial.pages[self.page_index].objects:
            if obj.id in ids:
                if "margin" in settings:
                    obj.margin = settings["margin"]
                for paragraph in obj.paragraphs:
                    for key in ("line_spacing", "space_before", "space_after"):
                        if key in settings:
                            setattr(paragraph, key, settings[key])
        Project.from_dict(trial.to_dict())
        self.begin_operation()
        self.project = trial
        self.rebuild_scene(ids)
        self.finish_operation("문단 간격·여백")
