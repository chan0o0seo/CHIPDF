"""Selection inspector, composed around the editor's existing edit commands."""
from contextlib import contextmanager
import math

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFontComboBox,
                              QFormLayout, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                              QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QTabBar,
                              QToolButton, QVBoxLayout, QWidget)

from ..model import GroupBox, ImageBox, ShapeBox, TextBox
from ..richtext import letter_spacing_from, letter_spacing_percent
from .controls import (BOX_ALIGN_ITEMS, TEXT_ALIGN_ITEMS, ColorButton, SegmentedButtons, SliderField,
                       show_text_alignment)
from .icons import icon


@contextmanager
def quiet(widget):
    previous = widget.blockSignals(True)
    try:
        yield widget
    finally:
        widget.blockSignals(previous)


def same(values):
    """The shared value of a selection, or None when it is mixed or empty."""
    return values[0] if values and all(value == values[0] for value in values[1:]) else None


def note(text, name="inspectorHint"):
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


def section(layout, title):
    label = QLabel(title)
    label.setObjectName("inspectorSectionTitle")
    layout.addWidget(label)


def icon_row(actions, parent):
    """Icon-only buttons for actions; names stay in tooltips and for screen readers."""
    row = QHBoxLayout()
    row.setSpacing(4)
    for action in actions:
        button = QToolButton(parent)
        button.setDefaultAction(action)
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        button.setIconSize(QSize(20, 20))
        button.setAutoRaise(True)
        button.setToolTip(action.toolTip() or action.text())
        button.setAccessibleName(action.text())
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.setMinimumHeight(32)
        row.addWidget(button)
    return row


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
                ("layout", "배치"), ("layers", "레이어"), ("links", "링크"))

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
        self.recent_colors = []
        self.inspector.add_page(self._make_format_page())
        self.inspector.add_page(self._make_layout_page())
        self.inspector.add_page(self._make_layers_page())
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
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setSpacing(8)
        return form

    def _slider(self, form, label, name, lower, upper, suffix="", factor=1.0, decimals=0, step=1, title=None):
        """A property slider: dragging previews, release records one undo step."""
        field = SliderField(lower, upper, suffix, decimals, step)
        field.setAccessibleName(label)
        field.dragStarted.connect(self.begin_operation)
        field.previewed.connect(lambda value: self.preview_properties({name: value * factor}))
        field.committed.connect(lambda value: self._commit_properties({name: value * factor}, title or label))
        form.addRow(label, field)
        return field

    def _commit_properties(self, values, label):
        self.set_properties(values, label)
        if self.operation_before is not None:
            self.finish_operation(label)

    def _color_button(self, title, allow_none=False):
        button = ColorButton(title, allow_none, self.palette_colors, self.canvas.start_color_pick)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return button

    def palette_colors(self):
        """Colours already used on this page, then recently picked ones."""
        found = []
        page = self.current_page if self.project else None
        for obj in page.objects if page else []:
            values = [getattr(obj, key, "") for key in ("fill", "stroke", "highlight", "outline_color", "border_color")]
            if isinstance(obj, TextBox):
                values += [run.style.color for paragraph in obj.paragraphs for run in paragraph.runs]
            for value in values:
                if isinstance(value, str) and value.startswith("#") and value.lower() not in found:
                    found.append(value.lower())
        return found, list(self.recent_colors)

    def remember_color(self, color):
        if color.startswith("#"):
            self.recent_colors = [color] + [c for c in self.recent_colors if c != color][:9]

    def _picked(self, name, label):
        def apply(color):
            self.remember_color(color)
            self.set_property(name, color, label)
        return apply

    def _text_color_picked(self, color):
        self.remember_color(color)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        self.apply_format(fmt)

    def _letter_spacing_committed(self, value):
        fmt = QTextCharFormat()
        fmt.setFontLetterSpacingType(QFont.PercentageSpacing)
        fmt.setFontLetterSpacing(100 + letter_spacing_percent(value))
        self.apply_format(fmt)

    def _shadow_offset(self):
        distance = self.inspector_shadow_distance.value()
        angle = math.radians(self.inspector_shadow_angle.value())
        return {"shadow_dx": round(distance * math.cos(angle), 2), "shadow_dy": round(distance * math.sin(angle), 2)}

    def _shadow_slider(self, form, label, lower, upper, suffix):
        field = SliderField(lower, upper, suffix)
        field.setAccessibleName(label)
        field.dragStarted.connect(self.begin_operation)
        field.previewed.connect(lambda _value: self.preview_properties(self._shadow_offset()))
        field.committed.connect(lambda _value: self._commit_properties(self._shadow_offset(), "그림자 위치"))
        form.addRow(label, field)
        return field

    def _subsection(self, layout, title):
        label = QLabel(title)
        label.setObjectName("inspectorSubTitle")
        layout.addWidget(label)

    def _make_format_page(self):
        page, layout = self._inspector_page()
        self.inspector_format_state = note("텍스트, 그림 또는 도형을 선택하세요.", "inspectorNotice")
        layout.addWidget(self.inspector_format_state)
        self.inspector_text_controls = QWidget()
        text_layout = QVBoxLayout(self.inspector_text_controls)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(10)
        section(text_layout, "글꼴")
        self.inspector_font = QFontComboBox()
        self.inspector_font.setMinimumWidth(0)
        self.inspector_font.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.inspector_font.setAccessibleName("글꼴")
        self.inspector_font.setToolTip("목록의 글꼴 이름은 그 글꼴로 미리 보여 줍니다.")
        self.inspector_font.activated.connect(self._inspector_font_changed)
        text_layout.addWidget(self.inspector_font)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.inspector_size = InspectorSpinBox()
        self.inspector_size.setRange(1, 400)
        self.inspector_size.setDecimals(1)
        self.inspector_size.setSuffix(" pt")
        self.inspector_size.setKeyboardTracking(False)
        self.inspector_size.setAccessibleName("글자 크기")
        self.inspector_size.userValueChanged.connect(self.format_size)
        row.addWidget(self.inspector_size, 1)
        self.inspector_text_color = self._color_button("글자색")
        self.inspector_text_color.picked.connect(self._text_color_picked)
        row.addWidget(self.inspector_text_color, 1)
        text_layout.addLayout(row)
        text_layout.addLayout(icon_row([getattr(self, name) for name in
                                        ("bold_action", "italic_action", "underline_action", "strike_action")
                                        if getattr(self, name, None)], page))
        section(text_layout, "문단")
        row = QHBoxLayout()
        row.setSpacing(12)
        self.inspector_align = SegmentedButtons(TEXT_ALIGN_ITEMS)
        self.inspector_align.setAccessibleName("문단 정렬")
        self.inspector_align.activated.connect(self.format_alignment)
        row.addWidget(self.inspector_align)
        self.inspector_vertical_align = SegmentedButtons(BOX_ALIGN_ITEMS)
        self.inspector_vertical_align.setAccessibleName("상자 안 글자 세로 정렬")
        self.inspector_vertical_align.setToolTip("가로쓰기 상자 안의 글자 전체를 위·가운데·아래로 맞춥니다.")
        self.inspector_vertical_align.activated.connect(self.format_vertical_alignment)
        row.addWidget(self.inspector_vertical_align)
        text_layout.addLayout(row)
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
        self.inspector_letter_spacing = SliderField(-200, 800, "", step=10, live=False)
        self.inspector_letter_spacing.setAccessibleName("자간")
        self.inspector_letter_spacing.setToolTip("글자 사이 간격 · 1/1000 em")
        self.inspector_letter_spacing.committed.connect(self._letter_spacing_committed)
        form.addRow("자간", self.inspector_letter_spacing)
        text_layout.addLayout(form)

        section(text_layout, "효과")
        form = self._inspector_form()
        self.inspector_outline_color = self._color_button("외곽선 색")
        self.inspector_outline_color.picked.connect(self._picked("outline_color", "외곽선 색"))
        form.addRow("외곽선", self.inspector_outline_color)
        self.inspector_outline_width = self._slider(form, "두께", "outline_width", 0, 20, " px", decimals=1, step=.5, title="외곽선 두께")
        self.inspector_shadow = QCheckBox("그림자")
        self.inspector_shadow.toggled.connect(lambda checked: self.set_property("shadow_enabled", checked, "그림자"))
        self.inspector_shadow_color = self._color_button("그림자 색")
        self.inspector_shadow_color.picked.connect(self._picked("shadow_color", "그림자 색"))
        form.addRow(self.inspector_shadow, self.inspector_shadow_color)
        self.inspector_shadow_opacity = self._slider(form, "진하기", "shadow_opacity", 0, 100, " %", .01, title="그림자 진하기")
        self.inspector_shadow_distance = self._shadow_slider(form, "거리", 0, 60, " px")
        self.inspector_shadow_angle = self._shadow_slider(form, "방향", 0, 359, "°")
        self.inspector_shadow_blur = self._slider(form, "흐림", "shadow_blur", 0, 40, " px", title="그림자 흐림")
        self.inspector_highlight = self._color_button("글자 배경", allow_none=True)
        self.inspector_highlight.picked.connect(self._picked("highlight", "글자 배경"))
        form.addRow("글자 배경", self.inspector_highlight)
        text_layout.addLayout(form)

        section(text_layout, "투명도")
        form = self._inspector_form()
        self.inspector_text_opacity = self._slider(form, "글자", "text_opacity", 0, 100, " %", .01, title="글자 불투명도")
        self.inspector_fill = self._color_button("상자 배경", allow_none=True)
        self.inspector_fill.picked.connect(self._picked("fill", "상자 배경"))
        form.addRow("상자 배경", self.inspector_fill)
        self.inspector_fill_opacity = self._slider(form, "배경", "fill_opacity", 0, 100, " %", .01, title="배경 불투명도")
        text_layout.addLayout(form)
        self._subsection(text_layout, "세로쓰기 · 서식 복사 · 서식 붙여넣기")
        text_layout.addLayout(icon_row([getattr(self, name) for name in
                                        ("vertical_action", "copy_style_action", "paste_style_action")
                                        if getattr(self, name, None)], page))
        layout.addWidget(self.inspector_text_controls)

        self.inspector_shape_controls = QWidget()
        shapes = QVBoxLayout(self.inspector_shape_controls)
        shapes.setContentsMargins(0, 0, 0, 0)
        shapes.setSpacing(8)
        section(shapes, "도형 서식")
        form = self._inspector_form()
        self.inspector_shape_fill = self._color_button("채우기", allow_none=True)
        self.inspector_shape_fill.picked.connect(self._picked("fill", "도형 색"))
        form.addRow("채우기", self.inspector_shape_fill)
        self.inspector_shape_stroke = self._color_button("테두리")
        self.inspector_shape_stroke.picked.connect(self._picked("stroke", "도형 테두리"))
        form.addRow("테두리", self.inspector_shape_stroke)
        self.inspector_stroke = self._slider(form, "선 두께", "stroke_width", 0, 30, " px", decimals=1, step=.5)
        self.inspector_shape_opacity = self._slider(form, "불투명도", "opacity", 0, 100, " %", .01)
        shapes.addLayout(form)
        layout.addWidget(self.inspector_shape_controls)

        self.inspector_image_controls = QWidget()
        images = QVBoxLayout(self.inspector_image_controls)
        images.setContentsMargins(0, 0, 0, 0)
        images.setSpacing(8)
        section(images, "그림 서식")
        for action in self.image_tools:
            images.addWidget(action_button(action, page))
        self._subsection(images, "조정")
        form = self._inspector_form()
        self.inspector_image_adjust = {}
        for key, label in (("brightness", "밝기"), ("contrast", "대비"), ("saturation", "채도")):
            self.inspector_image_adjust[key] = self._slider(form, label, key, -100, 100, "", title=f"이미지 {label}")
        self.inspector_image_opacity = self._slider(form, "불투명도", "opacity", 0, 100, " %", .01)
        images.addLayout(form)
        self._subsection(images, "모양")
        form = self._inspector_form()
        self.inspector_corner = self._slider(form, "모서리", "corner_radius", 0, 300, " px", title="모서리 둥글게")
        self.inspector_border_width = self._slider(form, "테두리", "border_width", 0, 30, " px", decimals=1, step=.5, title="테두리 두께")
        self.inspector_border_color = self._color_button("테두리 색")
        self.inspector_border_color.picked.connect(self._picked("border_color", "테두리 색"))
        form.addRow("테두리 색", self.inspector_border_color)
        images.addLayout(form)
        layout.addWidget(self.inspector_image_controls)
        layout.addStretch()
        return page

    def _geometry_changed(self, key, value):
        items = self.mutable_selection()
        if len(items) == 1:
            self.apply_geometry(items[0].model, {key: value})

    def _icon_buttons(self, rows, handler, columns=4):
        grid = QGridLayout()
        grid.setSpacing(4)
        buttons = []
        for index, (name, mode, tip) in enumerate(rows):
            button = QToolButton()
            button.setIcon(icon(name))
            button.setIconSize(QSize(20, 20))
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.setAutoRaise(True)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setMinimumHeight(32)
            button.clicked.connect(lambda _=False, m=mode: handler(m))
            grid.addWidget(button, index // columns, index % columns)
            buttons.append(button)
        return grid, buttons

    def _make_layout_page(self):
        page, layout = self._inspector_page()
        self.inspector_layout_state = note("위치와 크기를 확인할 대상을 선택하세요.", "inspectorNotice")
        layout.addWidget(self.inspector_layout_state)
        section(layout, "위치와 크기")
        form = self._inspector_form()
        self.inspector_geometry = {}
        for key, label, suffix in (("x", "가로 위치", " px"), ("y", "세로 위치", " px"), ("width", "너비", " px"),
                                   ("height", "높이", " px"), ("rotation", "회전", "°")):
            field = InspectorSpinBox()
            field.setRange(24 if key in ("width", "height") else -360 if key == "rotation" else -16000,
                           360 if key == "rotation" else 16000)
            field.setDecimals(1)
            field.setSuffix(suffix)
            field.setAccessibleName(label)
            field.userValueChanged.connect(lambda value, k=key: self._geometry_changed(k, value))
            form.addRow(label, field)
            self.inspector_geometry[key] = field
        self.inspector_opacity = self._slider(form, "불투명도", "opacity", 0, 100, " %", .01)
        layout.addLayout(form)
        section(layout, "정렬")
        grid, self.inspector_align_buttons = self._icon_buttons((
            ("obj-align-left", "left", "왼쪽 맞춤"), ("obj-align-hcenter", "hcenter", "가로 가운데 맞춤"),
            ("obj-align-right", "right", "오른쪽 맞춤"), ("distribute-h", "horizontal", "가로 간격 같게 (3개 이상)"),
            ("obj-align-top", "top", "위쪽 맞춤"), ("obj-align-vcenter", "vcenter", "세로 가운데 맞춤"),
            ("obj-align-bottom", "bottom", "아래쪽 맞춤"), ("distribute-v", "vertical", "세로 간격 같게 (3개 이상)")),
            self.arrange)
        layout.addLayout(grid)
        layout.addWidget(note("하나만 선택하면 페이지(그룹 안에서는 그룹)를 기준으로 맞춥니다."))
        section(layout, "순서")
        grid, self.inspector_order_buttons = self._icon_buttons((
            ("layer-front", "front", "맨 앞으로"), ("layer-forward", "raise", "한 단계 앞으로"),
            ("layer-backward", "lower", "한 단계 뒤로"), ("layer-back", "back", "맨 뒤로")), self.reorder)
        layout.addLayout(grid)
        self._subsection(layout, "그룹 · 그룹 해제 · 잠금 · 모두 잠금 해제")
        layout.addLayout(icon_row([getattr(self, name) for name in
                                   ("group_action", "ungroup_action", "lock_action", "unlock_all_action")], page))
        layout.addWidget(note("위치와 크기는 문서 픽셀 기준입니다. 그룹 안에서는 그룹을 기준으로 표시합니다."))
        layout.addStretch()
        return page

    def _make_layers_page(self):
        page, layout = self._inspector_page()
        layout.addWidget(note("위가 앞쪽입니다. 끌어서 순서를 바꾸고, 클릭해서 선택하세요.", "inspectorNotice"))
        self.inspector_layers = QListWidget()
        self.inspector_layers.setObjectName("layerList")
        self.inspector_layers.setAccessibleName("레이어 목록")
        self.inspector_layers.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.inspector_layers.setDragDropMode(QAbstractItemView.InternalMove)
        self.inspector_layers.setDefaultDropAction(Qt.MoveAction)
        self.inspector_layers.setMinimumHeight(260)
        self.inspector_layers.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.inspector_layers.setTextElideMode(Qt.ElideRight)
        self.inspector_layers.setUniformItemSizes(True)
        self.inspector_layers.itemSelectionChanged.connect(self._layer_selection_changed)
        self.inspector_layers.model().rowsMoved.connect(self._layers_moved)
        self.inspector_layers.itemDoubleClicked.connect(self._layer_double_clicked)
        layout.addWidget(self.inspector_layers, 1)
        grid, self.inspector_layer_buttons = self._icon_buttons((
            ("layer-front", "front", "맨 앞으로"), ("layer-forward", "raise", "한 단계 앞으로"),
            ("layer-backward", "lower", "한 단계 뒤로"), ("layer-back", "back", "맨 뒤로")), self.reorder)
        layout.addLayout(grid)
        layout.addWidget(action_button(self.lock_action, page))
        self._layer_signature = None
        return page

    def _layer_label(self, obj):
        if isinstance(obj, TextBox):
            text = " ".join(obj.text.split()) or "(빈 텍스트)"
            label = "텍스트 · " + (text[:24] + "…" if len(text) > 24 else text)
        elif isinstance(obj, ImageBox):
            label = "그림"
        elif isinstance(obj, ShapeBox):
            label = {"rect": "사각형", "roundrect": "둥근 사각형", "ellipse": "원", "line": "선", "arrow": "화살표"}.get(obj.shape, "도형")
        else:
            label = "그룹"
        return label + (" · 잠김" if obj.locked else "")

    def _update_layers(self, objects):
        if not hasattr(self, "inspector_layers"):
            return
        scope = sorted(self.scope_objects(), key=lambda obj: -obj.z) if self.project else []
        signature = [(obj.id, self._layer_label(obj)) for obj in scope]
        selected = {obj.id for obj in objects}
        with quiet(self.inspector_layers):
            if signature != self._layer_signature:
                self.inspector_layers.clear()
                for key, label in signature:
                    row = QListWidgetItem(label)
                    row.setData(Qt.UserRole, key)
                    self.inspector_layers.addItem(row)
                self._layer_signature = signature
            for index in range(self.inspector_layers.count()):
                row = self.inspector_layers.item(index)
                row.setSelected(row.data(Qt.UserRole) in selected)

    def _layer_selection_changed(self):
        ids = {row.data(Qt.UserRole) for row in self.inspector_layers.selectedItems()}
        scene = self.canvas.scene()
        scene.blockSignals(True)
        try:
            scene.clearSelection()
            for key in ids:
                if key in self.items_by_id:
                    self.items_by_id[key].setSelected(True)
        finally:
            scene.blockSignals(False)
        scene.selectionChanged.emit()

    def _layer_double_clicked(self, row):
        item = self.items_by_id.get(row.data(Qt.UserRole))
        if item is not None:
            self.canvas.centerOn(item)

    def _layers_moved(self, *_args):
        ids = [self.inspector_layers.item(i).data(Qt.UserRole) for i in range(self.inspector_layers.count())]
        objects = {obj.id: obj for obj in self.scope_objects()}
        if set(ids) != set(objects):
            return
        self.finish_edit()
        self.begin_operation()
        # The list runs front to back; z runs back to front.
        for z, key in enumerate(reversed(ids)):
            objects[key].z = z
            self.items_by_id[key].setZValue(z + 1)
        self._layer_signature = None
        self.finish_operation("레이어 순서")

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
        values = {obj.vertical_align for obj in objects} if all_text else set()
        for field in (self.inspector_vertical_align, self.vertical_align_box):
            with quiet(field):
                field.setCurrentIndex(["top", "center", "bottom"].index(next(iter(values))) if len(values) == 1 else -1)
            field.setEnabled(mutable and all_text and all(obj.writing_mode == "horizontal" for obj in objects))
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
                show_text_alignment(self.inspector_align, all(obj.writing_mode == "vertical-rl" for obj in objects))
            for key, field in self.inspector_paragraph.items():
                self._inspector_value(field, [getattr(value, key) for value in (objects if key == "margin" else paragraphs)])
            self.inspector_letter_spacing.set_value(same([style.letter_spacing for style in styles]))
            colors = {style.color for style in styles}
            self.inspector_text_color.set_color(next(iter(colors)) if len(colors) == 1 else None)
            self._update_text_effects(objects)
        if all_shape:
            self.inspector_stroke.set_value(same([obj.stroke_width for obj in objects]))
            self.inspector_shape_opacity.set_value(same([obj.opacity * 100 for obj in objects]))
            self.inspector_shape_fill.set_color(same([obj.fill for obj in objects]))
            self.inspector_shape_stroke.set_color(same([obj.stroke for obj in objects]))
        if all_image:
            for key, field in self.inspector_image_adjust.items():
                field.set_value(same([getattr(obj, key) for obj in objects]))
            self.inspector_image_opacity.set_value(same([obj.opacity * 100 for obj in objects]))
            self.inspector_corner.set_value(same([obj.corner_radius for obj in objects]))
            self.inspector_border_width.set_value(same([obj.border_width for obj in objects]))
            self.inspector_border_color.set_color(same([obj.border_color for obj in objects]))
        self.inspector_opacity.setEnabled(mutable)
        self.inspector_opacity.set_value(same([obj.opacity * 100 for obj in objects]))
        single = len(objects) == 1 and mutable
        for key, field in self.inspector_geometry.items():
            field.setEnabled(single)
            if len(objects) == 1:
                obj = objects[0]
                self._inspector_value(field, [getattr(obj, key) * (obj.scale if key in ("width", "height") else 1)])
            else:
                self._inspector_value(field, [] if not objects else [0, 1])
        for button in self.inspector_align_buttons + self.inspector_order_buttons + self.inspector_layer_buttons:
            button.setEnabled(mutable)
        self._update_layers(objects)
        self._update_inspector_links(objects, mutable)

    def _update_text_effects(self, objects):
        self.inspector_outline_color.set_color(same([obj.outline_color for obj in objects]))
        self.inspector_outline_width.set_value(same([obj.outline_width for obj in objects]))
        shadows = {obj.shadow_enabled for obj in objects}
        with quiet(self.inspector_shadow):
            self.inspector_shadow.setTristate(len(shadows) > 1)
            self.inspector_shadow.setCheckState(Qt.PartiallyChecked if len(shadows) > 1 else
                                                Qt.Checked if True in shadows else Qt.Unchecked)
        self.inspector_shadow_color.set_color(same([obj.shadow_color for obj in objects]))
        self.inspector_shadow_opacity.set_value(same([obj.shadow_opacity * 100 for obj in objects]))
        offsets = {(obj.shadow_dx, obj.shadow_dy) for obj in objects}
        if len(offsets) == 1:
            dx, dy = next(iter(offsets))
            self.inspector_shadow_distance.set_value(round(math.hypot(dx, dy), 1))
            self.inspector_shadow_angle.set_value(round(math.degrees(math.atan2(dy, dx)) % 360))
        else:
            self.inspector_shadow_distance.set_value(None)
            self.inspector_shadow_angle.set_value(None)
        self.inspector_shadow_blur.set_value(same([obj.shadow_blur for obj in objects]))
        for field in (self.inspector_shadow_color, self.inspector_shadow_opacity, self.inspector_shadow_distance,
                      self.inspector_shadow_angle, self.inspector_shadow_blur):
            field.setEnabled(True in shadows)
        self.inspector_highlight.set_color(same([obj.highlight for obj in objects]))
        self.inspector_text_opacity.set_value(same([obj.text_opacity * 100 for obj in objects]))
        self.inspector_fill.set_color(same([obj.fill for obj in objects]))
        self.inspector_fill_opacity.set_value(same([obj.fill_opacity * 100 for obj in objects]))

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
