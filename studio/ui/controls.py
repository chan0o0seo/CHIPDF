"""Design-tool style inspector controls: sliders with values and colour swatches."""
from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QColorDialog, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QMenu,
                              QPushButton, QSlider, QToolButton, QVBoxLayout, QWidget, QWidgetAction)

BASIC_COLORS = (
    "#000000", "#545454", "#737373", "#a6a6a6", "#d9d9d9", "#ffffff",
    "#ff3131", "#ff5757", "#ff66c4", "#cb6ce6", "#8c52ff", "#5e17eb",
    "#0097b2", "#0cc0df", "#5ce1e6", "#38b6ff", "#5170ff", "#004aad",
    "#00bf63", "#7ed957", "#c1ff72", "#ffde59", "#ffbd59", "#ff914d",
)


class SliderField(QWidget):
    """A slider and its value; dragging previews, releasing commits once."""

    dragStarted = Signal()
    previewed = Signal(float)
    committed = Signal(float)

    def __init__(self, lower, upper, suffix="", decimals=0, step=1, live=True, parent=None):
        super().__init__(parent)
        self._factor = 10 ** decimals
        self._dragging = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(round(lower * self._factor), round(upper * self._factor))
        self.slider.setSingleStep(max(1, round(step * self._factor)))
        self.slider.setPageStep(max(1, round(step * self._factor * 10)))
        # Without live tracking the value arrives once, on release.
        self.slider.setTracking(live)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(lower, upper)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        self.spin.setSuffix(suffix)
        self.spin.setKeyboardTracking(False)
        self.spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.spin.setFixedWidth(76)
        self.spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.spin)
        self.slider.sliderPressed.connect(self._pressed)
        self.slider.sliderReleased.connect(self._released)
        self.slider.valueChanged.connect(self._slider_changed)
        self.spin.editingFinished.connect(self._spin_finished)

    def value(self):
        return self.slider.value() / self._factor

    def set_value(self, value):
        """Show a value without emitting; None shows a mixed selection."""
        for widget in (self.slider, self.spin):
            widget.blockSignals(True)
        if value is None:
            self.spin.clear()
            self.spin.lineEdit().setPlaceholderText("혼합")
        else:
            self.slider.setValue(round(value * self._factor))
            self.spin.setValue(value)
            self.spin.lineEdit().setPlaceholderText("")
        for widget in (self.slider, self.spin):
            widget.blockSignals(False)

    def _pressed(self):
        self._dragging = True
        if self.slider.hasTracking():
            self.dragStarted.emit()

    def _released(self):
        self._dragging = False
        self.committed.emit(self.value())

    def _slider_changed(self, raw):
        value = raw / self._factor
        self.spin.blockSignals(True)
        self.spin.setValue(value)
        self.spin.blockSignals(False)
        if self._dragging and self.slider.hasTracking():
            self.previewed.emit(value)
        elif not self._dragging:
            self.committed.emit(value)

    def _spin_finished(self):
        if not self.spin.lineEdit().text().strip():
            return
        value = self.spin.value()
        if round(value * self._factor) == self.slider.value():
            return
        self.slider.blockSignals(True)
        self.slider.setValue(round(value * self._factor))
        self.slider.blockSignals(False)
        self.committed.emit(value)


class SegmentedButtons(QWidget):
    """Exclusive icon buttons with the small QComboBox API the editor already uses.

    currentIndex()/setCurrentIndex(-1 for mixed)/activated(int)/setItemText keep
    existing alignment code working while the choice is shown as icons.
    """

    activated = Signal(int)

    def __init__(self, items, parent=None):
        super().__init__(parent)
        from .icons import icon
        self._icon = icon
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.buttons = []
        for index, (name, text) in enumerate(items):
            button = QToolButton(self)
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setIcon(icon(name))
            button.setIconSize(QSize(20, 20))
            button.setMinimumSize(32, 30)
            button.setToolTip(text)
            button.setAccessibleName(text)
            button.clicked.connect(lambda _=False, i=index: self._clicked(i))
            layout.addWidget(button)
            self.buttons.append(button)
        layout.addStretch()
        self._index = -1

    def _clicked(self, index):
        self.setCurrentIndex(index)
        self.activated.emit(index)

    def count(self):
        return len(self.buttons)

    def currentIndex(self):
        return self._index

    def setCurrentIndex(self, index):
        self._index = index if 0 <= index < len(self.buttons) else -1
        for position, button in enumerate(self.buttons):
            button.setChecked(position == self._index)

    def itemText(self, index):
        return self.buttons[index].toolTip()

    def setItemText(self, index, text):
        self.buttons[index].setToolTip(text)
        self.buttons[index].setAccessibleName(text)

    def setItemIcon(self, index, name):
        self.buttons[index].setIcon(self._icon(name))

    def setPlaceholderText(self, _text):
        """Mixed selections simply show no pressed button."""


TEXT_ALIGN_ITEMS = (("align-left", "왼쪽 정렬"), ("align-center", "가운데 정렬"), ("align-right", "오른쪽 정렬"))
VERTICAL_TEXT_ALIGN_ITEMS = (("obj-align-top", "위쪽 정렬"), ("obj-align-vcenter", "가운데 정렬"), ("obj-align-bottom", "아래쪽 정렬"))
BOX_ALIGN_ITEMS = (("text-top", "위 정렬"), ("text-middle", "세로 가운데 정렬"), ("text-bottom", "아래 정렬"))


def show_text_alignment(control, vertical):
    """Vertical writing aligns along the column: show top/middle/bottom icons."""
    for index, (name, text) in enumerate(VERTICAL_TEXT_ALIGN_ITEMS if vertical else TEXT_ALIGN_ITEMS):
        control.setItemIcon(index, name)
        control.setItemText(index, text)


def swatch_icon(color, size=18):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    rect = QRectF(1, 1, size - 2, size - 2)
    if color in (None, "transparent"):
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(QPen(QColor("#9aa3ad"), 1))
        painter.drawEllipse(rect)
        painter.setPen(QPen(QColor("#d64545" if color == "transparent" else "#9aa3ad"), 1.5))
        if color == "transparent":
            painter.drawLine(rect.bottomLeft(), rect.topRight())
        else:
            painter.drawText(rect, Qt.AlignCenter, "?")
    else:
        painter.setBrush(QColor(color))
        # Light colours need a visible edge against the white panel.
        light = QColor(color).lightness() > 200
        painter.setPen(QPen(QColor(0, 0, 0, 150 if light else 60), 1))
        painter.drawEllipse(rect)
    painter.end()
    return QIcon(pixmap)


def text_color_icon(color, size=22):
    """A letter A over a bar of the current colour; mixed selections show a spectrum."""
    from PySide6.QtGui import QLinearGradient, QPainterPath
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size / 24, size / 24)
    painter.setPen(QPen(QColor("#3C4856"), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    letter = QPainterPath()
    letter.moveTo(6, 16)
    letter.lineTo(12, 3)
    letter.lineTo(18, 16)
    letter.moveTo(8.4, 11)
    letter.lineTo(15.6, 11)
    painter.drawPath(letter)
    bar = QRectF(4, 18.5, 16, 3.5)
    painter.setPen(Qt.NoPen)
    if color in (None, "transparent"):
        spectrum = QLinearGradient(bar.topLeft(), bar.topRight())
        for stop, hue in ((0, "#ff3131"), (.25, "#ffde59"), (.5, "#00bf63"), (.75, "#38b6ff"), (1, "#8c52ff")):
            spectrum.setColorAt(stop, QColor(hue))
        painter.setBrush(spectrum)
    else:
        painter.setBrush(QColor(color))
    painter.drawRoundedRect(bar, 1.2, 1.2)
    if color not in (None, "transparent") and QColor(color).lightness() > 200:
        painter.setPen(QPen(QColor(0, 0, 0, 110), .8))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(bar, 1.2, 1.2)
    painter.end()
    return QIcon(pixmap)


class ColorButton(QToolButton):
    """A swatch that opens a palette: document, recent and basic colours."""

    picked = Signal(str)

    def __init__(self, title, allow_none=False, colors=None, eyedropper=None, parent=None, text_glyph=False):
        super().__init__(parent)
        self.title = title
        self.text_glyph = text_glyph
        self.allow_none = allow_none
        self.colors = colors or (lambda: ([], []))
        self.eyedropper = eyedropper
        self.setText(title)
        self.setToolTip(title)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(18, 18))
        self.setMinimumHeight(30)
        self.setPopupMode(QToolButton.InstantPopup)
        self.menu_ = QMenu(self)
        self.menu_.aboutToShow.connect(self._build)
        self.setMenu(self.menu_)
        self.set_color(None)

    def set_color(self, color):
        self.current = color
        self.setIcon(text_color_icon(color) if self.text_glyph else swatch_icon(color))

    def _choose(self, color):
        self.menu_.close()
        self.picked.emit(color)

    def _grid(self, layout, title, colors):
        if not colors:
            return
        label = QLabel(title)
        label.setObjectName("paletteTitle")
        layout.addWidget(label)
        grid = QGridLayout()
        grid.setSpacing(4)
        for index, color in enumerate(colors):
            button = QToolButton()
            button.setIcon(swatch_icon(color, 22))
            button.setIconSize(QSize(22, 22))
            button.setAutoRaise(True)
            button.setToolTip(color)
            button.setAccessibleName(f"{title} {color}")
            button.clicked.connect(lambda _=False, c=color: self._choose(c))
            grid.addWidget(button, index // 8, index % 8)
        layout.addLayout(grid)

    def _build(self):
        self.menu_.clear()
        panel = QWidget()
        panel.setObjectName("colorPalette")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        document, recent = self.colors()
        self._grid(layout, "문서 색", document[:16])
        self._grid(layout, "최근 사용", recent[:8])
        self._grid(layout, "기본 색", BASIC_COLORS)
        row = QHBoxLayout()
        if self.allow_none:
            none = QPushButton("없음")
            none.clicked.connect(lambda: self._choose("transparent"))
            row.addWidget(none)
        custom = QPushButton("다른 색…")
        custom.clicked.connect(self._custom)
        row.addWidget(custom)
        if self.eyedropper:
            dropper = QPushButton("스포이트")
            dropper.setToolTip("문서에서 색을 클릭해 고릅니다 · Esc로 취소")
            dropper.clicked.connect(self._dropper)
            row.addWidget(dropper)
        layout.addLayout(row)
        action = QWidgetAction(self.menu_)
        action.setDefaultWidget(panel)
        self.menu_.addAction(action)

    def _custom(self):
        self.menu_.close()
        start = QColor(self.current) if self.current not in (None, "transparent") else QColor("#ffffff")
        color = QColorDialog.getColor(start, self.window(), self.title)
        if color.isValid():
            self.picked.emit(color.name())

    def _dropper(self):
        self.menu_.close()
        self.eyedropper(self.picked.emit)
