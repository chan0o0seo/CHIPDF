"""Selection inspector, composed around the editor's existing edit commands."""
from contextlib import contextmanager

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QFont, QTextCharFormat
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFontComboBox,
                              QFormLayout, QHBoxLayout, QLabel, QPushButton,
                              QScrollArea, QSizePolicy, QStackedWidget, QTabBar,
                              QToolButton, QVBoxLayout, QWidget)

from ..model import GroupBox, ImageBox, ShapeBox, TextBox


@contextmanager
def quiet(widget):
    previous = widget.blockSignals(True)
    try:
        yield widget
    finally:
        widget.blockSignals(previous)


def note(text, name="inspectorHint"):
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


def section(layout, title):
    label = QLabel(title)
    label.setObjectName("inspectorSectionTitle")
    layout.addWidget(label)


def action_button(action, parent):
    button = QToolButton(parent)
    button.setDefaultAction(action)
    button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    button.setMinimumHeight(30)
    button.setFocusPolicy(Qt.TabFocus)
    return button


class InspectorSpinBox(QDoubleSpinBox):
    """Only explicit typing or stepping commits a value to the document."""

    userValueChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._typed = False
        self.setKeyboardTracking(False)
        self.lineEdit().textEdited.connect(self._text_edited)
        self.editingFinished.connect(self._commit)

    def _text_edited(self, _text):
        self._typed = True

    def _commit(self):
        if self._typed and self.lineEdit().text().strip():
            self._typed = False
            self.userValueChanged.emit(self.value())

    def stepBy(self, steps):
        self._typed = False
        before = self.value()
        super().stepBy(steps)
        if self.value() != before:
            self.userValueChanged.emit(self.value())


class InspectorPanel(QWidget):
    """Four persistent pages; a selector replaces tabs when space is tight."""

    sections = (("source", "원문·번역"), ("format", "서식"),
                ("layout", "배치"), ("links", "링크"))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("inspectorPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.tabs = QTabBar()
        self.tabs.setObjectName("inspectorTabs")
        self.tabs.setExpanding(True)
        self.tabs.setDrawBase(False)
        self.tabs.setUsesScrollButtons(False)
        self.selector = QComboBox()
        self.selector.setObjectName("inspectorSelector")
        self.selector.setAccessibleName("속성 종류")
        for key, title in self.sections:
            self.tabs.addTab(title)
            self.selector.addItem(title, key)
        layout.addWidget(self.tabs)
        layout.addWidget(self.selector)
        self.selector.hide()
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self.tabs.currentChanged.connect(self.set_index)
        self.selector.activated.connect(self.set_index)

    def add_page(self, page):
        scroll = QScrollArea()
        scroll.setObjectName("inspectorScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        self.stack.addWidget(scroll)

    def set_index(self, index):
        with quiet(self.tabs), quiet(self.selector):
            self.tabs.setCurrentIndex(index)
            self.selector.setCurrentIndex(index)
        self.stack.setCurrentIndex(index)

    def select(self, key):
        self.set_index(next((i for i, row in enumerate(self.sections) if row[0] == key), 0))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < max(290, self.tabs.sizeHint().width())
        self.tabs.setVisible(not compact)
        self.selector.setVisible(compact)


class Inspector:
    def init_inspector(self):
        # The source page and its callbacks were created by init_workflow.
        # Reparent it before replacing the old dock widget.
        self.source_panel.setParent(None)
        self.inspector = InspectorPanel(self.source_dock)
        self.inspector.add_page(self.source_panel)
        self.inspector.add_page(self._make_format_page())
        self.inspector.add_page(self._make_layout_page())
        self.inspector.add_page(self._make_links_page())
        self.source_dock.setWidget(self.inspector)
        self.source_dock.setMinimumWidth(280)
        self.source_dock.setWindowTitle("속성")
        self.source_dock.toggleViewAction().setText("속성 창")
        self.resizeDocks([self.source_dock], [304], Qt.Horizontal)
        self.update_inspector()
        self.source_dock.show()

    def show_inspector(self, section="source"):
        if not hasattr(self, "inspector"):
            return
        view = self.capture_canvas_view()
        self.inspector.select(section)
        self.source_dock.show()
        self.source_dock.raise_()
        self.update_inspector()
        self.restore_canvas_view(view)

    def _inspector_page(self):
        page = QWidget()
        page.setObjectName("inspectorPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        return page, layout

    def _inspector_form(self):
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setSpacing(8)
        return form

    def _make_format_page(self):
        page, layout = self._inspector_page()
        self.inspector_format_state = note("텍스트, 그림 또는 도형을 선택하세요.", "inspectorNotice")
        layout.addWidget(self.inspector_format_state)
        self.inspector_text_controls = QWidget()
        text_layout = QVBoxLayout(self.inspector_text_controls)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(10)
        section(text_layout, "글꼴")
        form = self._inspector_form()
        self.inspector_font = QFontComboBox()
        self.inspector_font.setMinimumWidth(0)
        self.inspector_font.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.inspector_font.activated.connect(self._inspector_font_changed)
        form.addRow("글꼴", self.inspector_font)
        self.inspector_size = InspectorSpinBox()
        self.inspector_size.setRange(1, 400)
        self.inspector_size.setDecimals(1)
        self.inspector_size.setSuffix(" pt")
        self.inspector_size.setKeyboardTracking(False)
        self.inspector_size.userValueChanged.connect(self.format_size)
        form.addRow("크기", self.inspector_size)
        text_layout.addLayout(form)
        flags = QHBoxLayout()
        flags.setSpacing(4)
        for name in ("bold_action", "italic_action", "underline_action", "strike_action"):
            action = getattr(self, name, None)
            if action:
                flags.addWidget(action_button(action, page))
        text_layout.addLayout(flags)
        color = QPushButton("글자색 선택…")
        color.clicked.connect(self.choose_color)
        text_layout.addWidget(color)
        section(text_layout, "문단")
        self.inspector_align = QComboBox()
        self.inspector_align.addItems(["왼쪽 정렬", "가운데 정렬", "오른쪽 정렬"])
        self.inspector_align.activated.connect(self.format_alignment)
        text_layout.addWidget(self.inspector_align)
        form = self._inspector_form()
        self.inspector_paragraph = {}
        for key, label, lower, upper, step, suffix in (
                ("line_spacing", "줄 간격", .5, 4, .1, " 배"),
                ("space_before", "문단 앞", 0, 500, 1, " px"),
                ("space_after", "문단 뒤", 0, 500, 1, " px"),
                ("margin", "안쪽 여백", 0, 200, 1, " px")):
            field = InspectorSpinBox()
            field.setRange(lower, upper)
            field.setDecimals(2 if key == "line_spacing" else 1)
            field.setSingleStep(step)
            field.setSuffix(suffix)
            field.setKeyboardTracking(False)
            field.userValueChanged.connect(lambda value, k=key: self.apply_paragraph_settings({k: value}))
            self.inspector_paragraph[key] = field
            form.addRow(label, field)
        text_layout.addLayout(form)
        text_layout.addWidget(note("간격과 여백은 선택한 상자의 모든 문단에 적용됩니다."))
        for name in ("vertical_action", "fill_action", "copy_style_action", "paste_style_action"):
            action = getattr(self, name, None)
            if action:
                text_layout.addWidget(action_button(action, page))
        layout.addWidget(self.inspector_text_controls)

        self.inspector_shape_controls = QWidget()
        shapes = QVBoxLayout(self.inspector_shape_controls)
        shapes.setContentsMargins(0, 0, 0, 0)
        shapes.setSpacing(8)
        section(shapes, "도형 서식")
        for name in ("shape_fill", "shape_clear", "shape_stroke"):
            shapes.addWidget(action_button(getattr(self, name), page))
        self.inspector_stroke = InspectorSpinBox()
        self.inspector_stroke.setRange(0, 30)
        self.inspector_stroke.setSuffix(" px")
        self.inspector_stroke.setKeyboardTracking(False)
        self.inspector_stroke.userValueChanged.connect(lambda value: self.set_property("stroke_width", value, "선 두께"))
        form = self._inspector_form()
        form.addRow("선 두께", self.inspector_stroke)
        shapes.addLayout(form)
        layout.addWidget(self.inspector_shape_controls)

        self.inspector_image_controls = QWidget()
        images = QVBoxLayout(self.inspector_image_controls)
        images.setContentsMargins(0, 0, 0, 0)
        images.setSpacing(8)
        section(images, "그림 서식")
        for action in self.image_tools:
            images.addWidget(action_button(action, page))
        layout.addWidget(self.inspector_image_controls)
        layout.addStretch()
        return page

    def _make_layout_page(self):
        page, layout = self._inspector_page()
        self.inspector_layout_state = note("위치와 크기를 확인할 대상을 선택하세요.", "inspectorNotice")
        layout.addWidget(self.inspector_layout_state)
        section(layout, "위치와 크기")
        form = self._inspector_form()
        self.inspector_geometry = {}
        for key, label in (("x", "가로 위치"), ("y", "세로 위치"), ("width", "너비"),
                           ("height", "높이"), ("rotation", "회전")):
            value = QLabel("—")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(label, value)
            self.inspector_geometry[key] = value
        self.inspector_opacity = InspectorSpinBox()
        self.inspector_opacity.setRange(0, 100)
        self.inspector_opacity.setDecimals(0)
        self.inspector_opacity.setSuffix(" %")
        self.inspector_opacity.setKeyboardTracking(False)
        self.inspector_opacity.userValueChanged.connect(lambda value: self.set_property("opacity", value / 100, "불투명도"))
        form.addRow("불투명도", self.inspector_opacity)
        layout.addLayout(form)
        layout.addWidget(action_button(self.geometry_action, page))
        section(layout, "정렬과 순서")
        arrange = QToolButton()
        arrange.setText("위치 맞춤 · 앞뒤 순서")
        arrange.setMenu(self.arrange_menu)
        arrange.setPopupMode(QToolButton.InstantPopup)
        arrange.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        arrange.setMinimumHeight(32)
        layout.addWidget(arrange)
        for name in ("group_action", "ungroup_action", "lock_action", "unlock_all_action"):
            layout.addWidget(action_button(getattr(self, name), page))
        layout.addWidget(note("위치와 크기는 문서 픽셀 기준입니다. 그룹 안에서는 그룹을 기준으로 표시합니다."))
        layout.addStretch()
        return page

    def _make_links_page(self):
        page, layout = self._inspector_page()
        self.inspector_link_state = note("페이지 링크를 지정할 텍스트 상자 하나를 선택하세요.", "inspectorNotice")
        layout.addWidget(self.inspector_link_state)
        section(layout, "페이지 이동")
        self.inspector_link_mode = QComboBox()
        for label, mode in (("원본 링크 자동 유지", "auto"), ("페이지 직접 지정", "page"), ("이 상자 링크 없음", "none")):
            self.inspector_link_mode.addItem(label, mode)
        self.inspector_link_mode.setAccessibleName("페이지 링크 방식")
        self.inspector_link_mode.activated.connect(self._inspector_link_mode_changed)
        layout.addWidget(self.inspector_link_mode)
        self.inspector_link_target = QComboBox()
        self.inspector_link_target.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.inspector_link_target.setMinimumContentsLength(8)
        self.inspector_link_target.setAccessibleName("이동할 페이지")
        layout.addWidget(QLabel("이동할 페이지"))
        layout.addWidget(self.inspector_link_target)
        self.inspector_link_apply = QPushButton("링크 적용")
        self.inspector_link_apply.setObjectName("primaryButton")
        self.inspector_link_apply.clicked.connect(self._inspector_apply_link)
        layout.addWidget(self.inspector_link_apply)
        self.inspector_link_detail = note("")
        layout.addWidget(self.inspector_link_detail)
        section(layout, "PDF 저장 안내")
        layout.addWidget(note("링크는 완성본을 PDF로 저장했을 때 동작합니다. PNG에는 링크가 포함되지 않습니다."))
        layout.addWidget(note("일부 페이지만 저장할 때는 이동할 페이지도 함께 포함해야 합니다. 자동 유지는 문장 선택 영역에 있던 원본 링크를 따릅니다."))
        layout.addStretch()
        return page

    def _inspector_font_changed(self, _index):
        fmt = QTextCharFormat()
        fmt.setFontFamilies([self.inspector_font.currentFont().family()])
        self.apply_format(fmt)

    def _inspector_link_mode_changed(self, _index):
        self.inspector_link_target.setEnabled(self.inspector_link_mode.currentData() == "page")

    def _inspector_apply_link(self):
        mode = self.inspector_link_mode.currentData()
        target = self.inspector_link_target.currentData() or ""
        if mode == "page" and not target:
            return
        self.set_page_link(mode, target)

    def _inspector_value(self, field, values):
        mixed = not values or any(value != values[0] for value in values[1:])
        with quiet(field):
            field._typed = False
            if mixed:
                field.lineEdit().clear()
                field.lineEdit().setPlaceholderText("혼합" if values else "—")
            else:
                field.setValue(values[0])
                # setValue is a no-op for the same numeric value; restore text
                # after a mixed selection cleared the editor explicitly.
                field.lineEdit().setText(field.textFromValue(field.value()) + field.suffix())
                field.lineEdit().setPlaceholderText("")

    def update_inspector(self):
        if not hasattr(self, "inspector"):
            return
        selected = self.selected()
        objects = [item.model for item in selected]
        mutable = bool(self.mutable_selection())
        all_text = bool(objects) and all(isinstance(obj, TextBox) for obj in objects)
        all_shape = bool(objects) and all(isinstance(obj, ShapeBox) for obj in objects)
        all_image = bool(objects) and all(isinstance(obj, ImageBox) for obj in objects)
        if not objects:
            summary = "문서에서 편집할 대상을 선택하세요."
        else:
            kind = "텍스트" if all_text else "도형" if all_shape else "그림" if all_image else "대상"
            summary = f"{kind} {len(objects)}개 선택"
            if any(self.effective_locked(obj) for obj in objects):
                summary += " · 잠김"
            if self.comparing:
                summary += " · 원본 비교 중"
        self.inspector_format_state.setText(summary)
        self.inspector_layout_state.setText(summary)
        for widget, visible in ((self.inspector_text_controls, all_text),
                                (self.inspector_shape_controls, all_shape),
                                (self.inspector_image_controls, all_image)):
            widget.setVisible(visible)
            widget.setEnabled(mutable)
        if all_text:
            styles = [run.style for obj in objects for paragraph in obj.paragraphs for run in paragraph.runs]
            families = {style.family for style in styles}
            with quiet(self.inspector_font):
                if len(families) == 1:
                    self.inspector_font.setCurrentFont(QFont(next(iter(families))))
                else:
                    self.inspector_font.setCurrentIndex(-1)
                    self.inspector_font.lineEdit().setPlaceholderText("혼합")
            self._inspector_value(self.inspector_size, [style.size for style in styles])
            paragraphs = [paragraph for obj in objects for paragraph in obj.paragraphs]
            with quiet(self.inspector_align):
                aligns = {paragraph.align for paragraph in paragraphs}
                self.inspector_align.setCurrentIndex(["left", "center", "right"].index(next(iter(aligns))) if len(aligns) == 1 else -1)
                vertical = all(obj.writing_mode == "vertical-rl" for obj in objects)
                labels = ["위쪽 정렬", "가운데 정렬", "아래쪽 정렬"] if vertical else ["왼쪽 정렬", "가운데 정렬", "오른쪽 정렬"]
                for index, label in enumerate(labels):
                    self.inspector_align.setItemText(index, label)
            for key, field in self.inspector_paragraph.items():
                self._inspector_value(field, [getattr(value, key) for value in (objects if key == "margin" else paragraphs)])
        if all_shape:
            self._inspector_value(self.inspector_stroke, [obj.stroke_width for obj in objects])
        self.inspector_opacity.setEnabled(mutable)
        self._inspector_value(self.inspector_opacity, [obj.opacity * 100 for obj in objects])
        for key, label in self.inspector_geometry.items():
            if len(objects) == 1:
                obj = objects[0]
                value = getattr(obj, key) * (obj.scale if key in ("width", "height") else 1)
                label.setText(f"{value:,.1f}" + ("°" if key == "rotation" else " px"))
            else:
                label.setText("혼합" if objects else "—")
        self._update_inspector_links(objects, mutable)

    def _update_inspector_links(self, objects, mutable):
        obj = objects[0] if len(objects) == 1 and isinstance(objects[0], TextBox) else None
        editable = obj is not None and mutable
        self.inspector_link_mode.setEnabled(editable)
        self.inspector_link_apply.setEnabled(editable)
        with quiet(self.inspector_link_mode), quiet(self.inspector_link_target):
            mode = obj.link_mode if obj else "auto"
            self.inspector_link_mode.setCurrentIndex(self.inspector_link_mode.findData(mode))
            pages = self.project.pages if self.project else []
            rows = [(page.id, f"{index + 1}페이지 · {page.name}") for index, page in enumerate(pages)]
            existing = [(self.inspector_link_target.itemData(i), self.inspector_link_target.itemText(i)) for i in range(self.inspector_link_target.count())]
            if existing != rows:
                self.inspector_link_target.clear()
                for key, name in rows:
                    self.inspector_link_target.addItem(name, key)
            target = obj.link_page_id if obj and mode == "page" else (pages[0].id if pages else "")
            self.inspector_link_target.setCurrentIndex(self.inspector_link_target.findData(target))
        self.inspector_link_target.setEnabled(editable and mode == "page")
        if obj is None:
            self.inspector_link_state.setText("페이지 링크를 지정할 텍스트 상자 하나를 선택하세요.")
            self.inspector_link_detail.clear()
            return
        self.inspector_link_state.setText("선택한 텍스트 상자의 링크" + (" · 잠김" if self.effective_locked(obj) else " · 원본 비교 중" if self.comparing else ""))
        if mode == "none":
            detail = "이 텍스트 상자에는 페이지 링크를 넣지 않습니다."
        elif mode == "page":
            destination = next((name for key, name in rows if key == target), "이동할 페이지를 다시 지정하세요.")
            detail = "현재 목적지: " + destination
        else:
            from ..pdf_links import link_owner
            destinations = set()
            for link in self.current_page.pdf_links:
                owner = link_owner(self.current_page, QRectF(*link["rect"]))
                if owner is not None and owner.id == obj.id:
                    destinations.add(link["page_id"])
            names = [name for key, name in rows if key in destinations]
            detail = "원본에서 연결된 목적지: " + ", ".join(names) if names else "이 문장 영역에서 연결된 원본 링크가 없습니다. 페이지를 직접 지정할 수 있습니다."
        self.inspector_link_detail.setText(detail)
