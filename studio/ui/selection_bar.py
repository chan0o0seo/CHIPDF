"""A formatting bar fixed above the canvas whose tools follow the selection.

It sits in a strip reserved by the canvas' viewport margins, so the canvas stays
the central widget. Every control routes to the editor's existing commands.
"""
from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QAction, QFont, QTextCharFormat
from PySide6.QtWidgets import (QDoubleSpinBox, QFontComboBox, QFormLayout, QLabel, QMenu, QSizePolicy,
                              QToolBar, QToolButton, QWidget, QWidgetAction)

from ..model import ImageBox, ShapeBox, TextBox
from .controls import TEXT_ALIGN_ITEMS, VERTICAL_TEXT_ALIGN_ITEMS, ColorButton, SliderField, text_box_options
from .icons import icon
from .inspector import same

BAR_HEIGHT = 46


class SelectionBar(QToolBar):
    def __init__(self, editor):
        super().__init__(editor.canvas)
        self.editor = editor
        self.setObjectName("selectionBar")
        self.setMovable(False)
        self.setFloatable(False)
        self.setIconSize(QSize(20, 20))
        self.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.groups = {"empty": [], "text": [], "image": [], "shape": [], "common": []}
        self.painting = False
        self._paint_source = None
        self._build()
        canvas = editor.canvas
        canvas.setViewportMargins(0, BAR_HEIGHT, 0, 0)
        canvas.installEventFilter(self)
        editor.scene.selectionChanged.connect(self._paint_style)
        self._place()

    # Layout -----------------------------------------------------------------

    def eventFilter(self, watched, event):
        if watched is self.editor.canvas and event.type() == QEvent.Resize:
            self._place()
        return False

    def _place(self):
        self.setGeometry(0, 0, self.editor.canvas.width(), BAR_HEIGHT)
        self.raise_()

    def _add(self, group, widget):
        self.groups[group].append(self.addWidget(widget))
        return widget

    def _separator(self, group):
        self.groups[group].append(self.addSeparator())

    def _tool(self, group, name=None, tip=None, handler=None, action=None, text=None):
        button = QToolButton(self)
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.NoFocus)
        button.setIconSize(QSize(20, 20))
        if action is not None:
            button.setDefaultAction(action)
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            button.setToolTip(action.toolTip() or action.text())
            button.setAccessibleName(action.text())
        else:
            if text:
                button.setText(text)
                button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            else:
                button.setIcon(icon(name))
                button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            if handler is not None:
                button.clicked.connect(handler)
        return self._add(group, button)

    def _popover(self, group, name, tip, build):
        button = self._tool(group, name, tip)
        button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(button)
        menu.aboutToShow.connect(lambda: self._fill(menu, build))
        button.setMenu(menu)
        return button

    def _fill(self, menu, build):
        menu.clear()
        panel = QWidget()
        panel.setObjectName("barPopover")
        panel.setMinimumWidth(280)
        form = QFormLayout(panel)
        form.setContentsMargins(14, 12, 14, 12)
        form.setSpacing(10)
        build(form)
        action = QWidgetAction(menu)
        action.setDefaultWidget(panel)
        menu.addAction(action)

    def _build(self):
        editor = self.editor
        hint = QLabel("대상을 선택하면 서식 도구가 나타납니다")
        hint.setObjectName("selectionBarHint")
        self.hint = self._add("empty", hint)

        # Text ----------------------------------------------------------------
        self.font_box = QFontComboBox(self)
        self.font_box.setAccessibleName("글꼴")
        self.font_box.setToolTip("글꼴 · 목록의 이름은 그 글꼴로 미리 보입니다")
        self.font_box.setFixedWidth(170)
        self.font_box.activated.connect(self._font_chosen)
        self._add("text", self.font_box)
        self._tool("text", "minus", "글자 작게", lambda: self._step_size(-1))
        self.size_box = QDoubleSpinBox(self)
        self.size_box.setRange(1, 400)
        self.size_box.setDecimals(1)
        self.size_box.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.size_box.setAlignment(Qt.AlignCenter)
        self.size_box.setKeyboardTracking(False)
        self.size_box.setFixedWidth(56)
        self.size_box.setAccessibleName("글자 크기")
        self.size_box.editingFinished.connect(lambda: editor.format_size(self.size_box.value()))
        self._add("text", self.size_box)
        self._tool("text", "plus", "글자 크게", lambda: self._step_size(1))
        self.text_color = ColorButton("글자색", colors=editor.palette_colors,
                                      eyedropper=editor.canvas.start_color_pick, text_glyph=True)
        self.text_color.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.text_color.setIconSize(QSize(22, 22))
        self.text_color.picked.connect(editor._text_color_picked)
        self._add("text", self.text_color)
        for name in ("bold_action", "italic_action", "underline_action", "strike_action"):
            self._tool("text", action=getattr(editor, name))
        self.align_button = self._tool("text", "align-left", "정렬 · 누를 때마다 바뀝니다", self._cycle_alignment)
        self.list_button = self._tool("text", "list", "목록 · 없음 → 글머리표 → 번호", editor.toggle_list)
        self.list_button.setCheckable(True)
        self._popover("text", "spacing", "간격 · 자간과 줄 간격", self._spacing_panel)
        self._tool("text", action=editor.vertical_action)
        self._separator("text")

        # Image ---------------------------------------------------------------
        for action in editor.image_tools:
            self._tool("image", action=action)
        self._popover("image", "options", "조정 · 밝기·대비·채도", self._adjust_panel)
        self._popover("image", "corner", "모양 · 모서리·테두리", self._shape_panel)
        self._separator("image")

        # Shape ---------------------------------------------------------------
        self.shape_fill = ColorButton("채우기", allow_none=True, colors=editor.palette_colors,
                                      eyedropper=editor.canvas.start_color_pick)
        self.shape_fill.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.shape_fill.picked.connect(editor._picked("fill", "도형 색"))
        self._add("shape", self.shape_fill)
        self.shape_stroke = ColorButton("테두리 색", colors=editor.palette_colors,
                                        eyedropper=editor.canvas.start_color_pick)
        self.shape_stroke.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.shape_stroke.picked.connect(editor._picked("stroke", "도형 테두리"))
        self._add("shape", self.shape_stroke)
        self._popover("shape", "paragraph", "선 두께", self._stroke_panel)
        self._separator("shape")

        # Shared --------------------------------------------------------------
        self._popover("common", "transparency", "투명도", self._transparency_panel)
        self.effects_button = self._tool("text", tip="효과 · 외곽선·그림자·글자 배경", text="효과",
                                         handler=editor.show_effects)
        self._tool("common", tip="위치 · 정렬·순서·레이어", text="위치", handler=lambda: editor.show_inspector("layout"))
        self.painter = self._tool("text", "format-painter", "서식 복사 · 누른 뒤 다른 텍스트를 클릭하면 같은 서식이 적용됩니다")
        self.painter.setCheckable(True)
        self.painter.toggled.connect(self._painter_toggled)
        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._add("common", spacer)
        more = self._tool("common", "more", "더보기 · 복제·삭제·잠금·순서·그룹")
        more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(more)
        menu.addActions([editor.duplicate_action, editor.delete_action, editor.lock_action])
        menu.addSeparator()
        for name, mode, text in (("layer-front", "front", "맨 앞으로"), ("layer-forward", "raise", "한 단계 앞으로"),
                                 ("layer-backward", "lower", "한 단계 뒤로"), ("layer-back", "back", "맨 뒤로")):
            action = QAction(icon(name), text, menu)
            action.triggered.connect(lambda _=False, m=mode: editor.reorder(m))
            menu.addAction(action)
        menu.addSeparator()
        menu.addActions([editor.group_action, editor.ungroup_action])
        more.setMenu(menu)

    # Popover contents --------------------------------------------------------

    def _models(self):
        return [item.model for item in self.editor.mutable_selection()]

    def _property_slider(self, form, label, name, lower, upper, suffix="", factor=1.0, decimals=0, step=1):
        editor = self.editor
        field = SliderField(lower, upper, suffix, decimals, step)
        field.setAccessibleName(label)
        field.set_value(same([getattr(obj, name) / factor for obj in self._models() if hasattr(obj, name)]))
        field.dragStarted.connect(editor.begin_operation)
        field.previewed.connect(lambda value: editor.preview_properties({name: value * factor}))
        field.committed.connect(lambda value: editor._commit_properties({name: value * factor}, label))
        form.addRow(label, field)
        return field

    def _spacing_panel(self, form):
        editor = self.editor
        texts = [obj for obj in self._models() if isinstance(obj, TextBox)]
        letters = SliderField(-200, 800, "", step=10, live=False)
        letters.set_value(same([run.style.letter_spacing for obj in texts for p in obj.paragraphs for run in p.runs]))
        letters.committed.connect(editor._letter_spacing_committed)
        form.addRow("자간", letters)
        lines = SliderField(.5, 4, " 배", decimals=2, step=.05, live=False)
        lines.set_value(same([p.line_spacing for obj in texts for p in obj.paragraphs]))
        lines.committed.connect(lambda value: editor.apply_paragraph_settings({"line_spacing": value}))
        form.addRow("줄 간격", lines)
        for box in text_box_options(editor, texts):
            form.addRow(box)

    def _transparency_panel(self, form):
        editor = self.editor
        objects = self._models()
        if objects and all(isinstance(obj, TextBox) for obj in objects):
            self._property_slider(form, "글자", "text_opacity", 0, 100, " %", .01)
            fill = ColorButton("상자 배경", allow_none=True, colors=editor.palette_colors,
                               eyedropper=editor.canvas.start_color_pick)
            fill.set_color(same([obj.fill for obj in objects]))
            fill.picked.connect(editor._picked("fill", "상자 배경"))
            form.addRow("상자 배경", fill)
            self._property_slider(form, "배경", "fill_opacity", 0, 100, " %", .01)
        else:
            self._property_slider(form, "불투명도", "opacity", 0, 100, " %", .01)

    def _adjust_panel(self, form):
        for name, label in (("brightness", "밝기"), ("contrast", "대비"), ("saturation", "채도")):
            self._property_slider(form, label, name, -100, 100)

    def _shape_panel(self, form):
        editor = self.editor
        self._property_slider(form, "모서리", "corner_radius", 0, 300, " px")
        self._property_slider(form, "테두리", "border_width", 0, 30, " px", decimals=1, step=.5)
        color = ColorButton("테두리 색", colors=editor.palette_colors, eyedropper=editor.canvas.start_color_pick)
        color.set_color(same([obj.border_color for obj in self._models() if isinstance(obj, ImageBox)]))
        color.picked.connect(editor._picked("border_color", "테두리 색"))
        form.addRow("테두리 색", color)

    def _stroke_panel(self, form):
        self._property_slider(form, "선 두께", "stroke_width", 0, 30, " px", decimals=1, step=.5)

    # Commands ----------------------------------------------------------------

    def _font_chosen(self, _index):
        fmt = QTextCharFormat()
        fmt.setFontFamilies([self.font_box.currentFont().family()])
        self.editor.apply_format(fmt)

    def _step_size(self, delta):
        value = max(1, min(400, round(self.size_box.value()) + delta))
        self.size_box.setValue(value)
        self.editor.format_size(value)

    def _cycle_alignment(self):
        texts = [obj for obj in self._models() if isinstance(obj, TextBox)]
        if not texts:
            return
        current = ["left", "center", "right"].index(texts[0].paragraphs[0].align)
        self.editor.format_alignment((current + 1) % 3)

    def _painter_toggled(self, checked):
        editor = self.editor
        if checked:
            items = editor.mutable_selection()
            editor.copy_style()
            if len(items) != 1 or not editor.copied_style:
                self.painter.setChecked(False)
                return
            self.painting, self._paint_source = True, items[0].model.id
            editor.status.setText("서식을 적용할 텍스트를 클릭하세요 · 서식 복사 버튼을 다시 누르면 취소")
        else:
            self.painting, self._paint_source = False, None

    def _paint_style(self):
        if not self.painting:
            return
        items = self.editor.mutable_selection()
        if items and all(isinstance(i.model, TextBox) for i in items) and items[0].model.id != self._paint_source:
            self.editor.paste_style()
            self.painter.setChecked(False)
            self.editor.status.setText("서식을 적용했습니다")

    # State -------------------------------------------------------------------

    def sync(self):
        editor = self.editor
        objects = self._models() if editor.project else []
        if not objects:
            kind = "empty"
        elif all(isinstance(obj, TextBox) for obj in objects):
            kind = "text"
        elif all(isinstance(obj, ImageBox) for obj in objects):
            kind = "image"
        elif all(isinstance(obj, ShapeBox) for obj in objects):
            kind = "shape"
        else:
            kind = "mixed"
        shown = {"empty": {"empty"}, "text": {"text", "common"}, "image": {"image", "common"},
                 "shape": {"shape", "common"}, "mixed": {"common"}}[kind]
        if kind == "empty" and editor.selected():
            self.hint.setText("잠긴 대상입니다 · 잠금을 풀면 서식 도구가 나타납니다")
        else:
            self.hint.setText("대상을 선택하면 서식 도구가 나타납니다")
        for group, actions in self.groups.items():
            for action in actions:
                action.setVisible(group in shown)
        if kind == "text":
            styles = [run.style for obj in objects for p in obj.paragraphs for run in p.runs]
            families = {style.family for style in styles}
            self.font_box.blockSignals(True)
            if len(families) == 1:
                self.font_box.setCurrentFont(QFont(next(iter(families))))
            else:
                self.font_box.setCurrentIndex(-1)
            self.font_box.blockSignals(False)
            size = same([style.size for style in styles])
            self.size_box.blockSignals(True)
            if size is None:
                self.size_box.clear()
            else:
                self.size_box.setValue(size)
            self.size_box.blockSignals(False)
            self.text_color.set_color(same([style.color for style in styles]))
            vertical = all(obj.writing_mode == "vertical-rl" for obj in objects)
            aligns = {p.align for obj in objects for p in obj.paragraphs}
            index = ["left", "center", "right"].index(next(iter(aligns))) if len(aligns) == 1 else 0
            name, text = (VERTICAL_TEXT_ALIGN_ITEMS if vertical else TEXT_ALIGN_ITEMS)[index]
            self.align_button.setIcon(icon(name))
            self.align_button.setToolTip(f"정렬: {text} · 누를 때마다 바뀝니다")
            styles_of_lists = {p.list_style for obj in objects for p in obj.paragraphs}
            self.list_button.setEnabled(bool(editor.list_targets()))
            self.list_button.setChecked(styles_of_lists != {""})
            labels = {"": "없음", "disc": "글머리표", "decimal": "번호"}
            current = next(iter(styles_of_lists)) if len(styles_of_lists) == 1 else None
            self.list_button.setToolTip("목록" + (f": {labels[current]}" if current is not None else "") +
                                        " · 없음 → 글머리표 → 번호")
            self.painter.setEnabled(len(objects) == 1 or self.painting)
        elif kind == "shape":
            self.shape_fill.set_color(same([obj.fill for obj in objects]))
            self.shape_stroke.set_color(same([obj.stroke for obj in objects]))
