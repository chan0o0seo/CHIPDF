"""Shared Blue Office styling, deliberately separate from document styles.

This stylesheet is installed on the editor window, never on QApplication.  It
targets UI controls and named surfaces: it does not assign a font, background,
or text color to every QWidget or to the graphics scene's text items.
"""
from __future__ import annotations

from string import Template

from PySide6.QtWidgets import QWidget


COLORS = {
    "accent": "#0F6CBD",
    "accentHover": "#115EA3",
    "accentPressed": "#0C3B5E",
    "accentSoft": "#EAF3FC",
    "accentBorder": "#B4D6F2",
    "appBackground": "#F5F7FA",
    "titleSurface": "#EDF4FC",
    "panelSurface": "#FFFFFF",
    "workspace": "#E8ECF1",
    "text": "#242424",
    "textSecondary": "#616161",
    "disabledText": "#9BA5B1",
    "divider": "#DDE3EA",
    "controlBorder": "#8A95A3",
    "hoverSurface": "#F0F4F8",
    "pressedSurface": "#E1EAF3",
    "danger": "#B42318",
}

TOKENS = {
    **COLORS,
    "controlHeight": 30,
    "controlRadius": 4,
    "surfaceRadius": 8,
    "iconSize": 20,
    "largeIconSize": 28,
    "smallIconSize": 16,
    "groupSpacing": 16,
    "controlSpacing": 6,
    "pagePanelWidth": 196,
    "inspectorWidth": 304,
    "ribbonHeight": 96,
    "ribbonTabHeight": 32,
}


_STYLESHEET = Template("""
QMainWindow, QDialog {
    background: $appBackground;
    color: $text;
}
QLabel, QAbstractButton, QComboBox, QAbstractSpinBox, QLineEdit,
QMenu, QMenuBar, QTabBar, QGroupBox, QStatusBar, QDockWidget,
QListWidget, QTreeWidget, QTableWidget, QHeaderView {
    color: $text;
    font-family: "Malgun Gothic", "Segoe UI";
    font-size: ${uiFontSize}pt;
}
QWidget#documentHeader, QToolBar#documentHeader, QWidget#ribbonTabsSurface {
    background: $titleSurface;
    border: 0;
}
QLabel#appBrand {
    color: $accent;
    font-size: 15pt;
    font-weight: 700;
    padding: 0 8px 0 0;
}
QLabel#documentTitle {
    color: $text;
    font-weight: 600;
    padding: 0 4px;
}
QLabel#saveState, QLabel#secondaryText, QLabel[role="secondary"] {
    color: $textSecondary;
    font-size: ${smallFontSize}pt;
}
QLabel#saveState {
    background: transparent;
    padding: 3px 8px;
}
QLabel[role="title"], QLabel#panelTitle, QLabel#dialogTitle {
    font-size: ${titleFontSize}pt;
    font-weight: 600;
    padding: 5px 0;
}
QLabel[role="accent"], QLabel#selectionStatus {
    color: $accent;
}
QLabel#dialogTitle {
    font-size: ${dialogTitleFontSize}pt;
    padding: 4px 0 8px 0;
}
QFrame#infoCard, QWidget#infoCard, QLabel#infoCard {
    background: $accentSoft;
    color: $accentPressed;
    border: 1px solid $accentBorder;
    border-radius: 6px;
    padding: 10px 12px;
}
QWidget#ribbonShell, QWidget#ribbonPage, QWidget#ribbonGroup,
QFrame#ribbonGroup, QStackedWidget#ribbonStack {
    background: $panelSurface;
    border: 0;
}
QWidget#ribbonShell {
    border-bottom: 1px solid $divider;
}
QFrame#ribbonGroup {
    border-right: 1px solid $divider;
}
QToolButton[ribbonSmall="true"] {
    min-height: 18px;
    padding: 2px 4px;
    border-width: 1px;
}
QWidget#ribbonShell QComboBox, QWidget#ribbonShell QAbstractSpinBox {
    min-height: 18px;
    padding: 2px 6px;
}
QLabel#ribbonGroupTitle, QLabel[role="groupTitle"] {
    color: $textSecondary;
    font-size: ${smallFontSize}pt;
    padding: 1px 2px 0 2px;
}
QFrame#ribbonDivider {
    background: $divider;
    border: 0;
    max-width: 1px;
}
QToolBar {
    background: $panelSurface;
    border: 0;
    spacing: 4px;
    padding: 4px 6px;
}
QToolBar::separator {
    background: $divider;
    width: 1px;
    margin: 5px 7px;
}
QToolBar#contextTools {
    padding: 0;
    spacing: 0;
}
QTabWidget#ribbonTabs::pane {
    border: 0;
    background: $panelSurface;
}
QTabBar#ribbonTabs, QTabWidget#ribbonTabs QTabBar {
    background: $titleSurface;
}
QTabBar#ribbonTabs::tab, QTabWidget#ribbonTabs QTabBar::tab {
    background: transparent;
    color: $text;
    min-height: 26px;
    padding: 1px 16px 3px 16px;
    border: 0;
    border-bottom: 3px solid transparent;
    margin: 0 2px;
}
QTabBar#ribbonTabs::tab:hover, QTabWidget#ribbonTabs QTabBar::tab:hover {
    background: $accentSoft;
    color: $accent;
}
QTabBar#ribbonTabs::tab:selected, QTabWidget#ribbonTabs QTabBar::tab:selected {
    color: $accent;
    border-bottom-color: $accent;
    font-weight: 600;
}
QTabBar#ribbonTabs::tab:disabled, QTabWidget#ribbonTabs QTabBar::tab:disabled {
    color: $disabledText;
}
QToolButton, QPushButton {
    background: transparent;
    border: 2px solid transparent;
    border-radius: 4px;
    padding: 4px 9px;
    min-height: 20px;
}
QPushButton {
    background: $panelSurface;
    border: 1px solid $controlBorder;
    padding: 5px 12px;
}
QToolButton:hover, QPushButton:hover {
    background: $hoverSurface;
    border-color: $divider;
}
QToolButton:pressed, QPushButton:pressed {
    background: $pressedSurface;
    border-color: $accentBorder;
}
QToolButton:checked, QPushButton:checked {
    background: $accentSoft;
    border-color: $accentBorder;
    color: $accent;
}
QToolButton:checked:hover, QPushButton:checked:hover {
    background: $pressedSurface;
    border-color: $accent;
}
QToolButton:focus, QPushButton:focus {
    border-color: $accent;
}
QToolButton:disabled, QPushButton:disabled {
    color: $disabledText;
    background: transparent;
    border-color: transparent;
}
QToolButton[quiet="true"], QPushButton[quiet="true"] {
    background: transparent;
    border-color: transparent;
}
QToolButton[quiet="true"]:hover, QPushButton[quiet="true"]:hover {
    background: $accentSoft;
    border-color: $accentBorder;
}
QToolButton[quiet="true"]:focus, QPushButton[quiet="true"]:focus {
    border-color: $accent;
}
QPushButton#primary, QPushButton#primaryButton, QPushButton[primary="true"],
QToolButton#primaryButton, QToolButton[primary="true"] {
    background: $accent;
    color: white;
    border: 2px solid $accent;
    font-weight: 600;
    padding: 5px 14px;
}
QPushButton#primary:hover, QPushButton#primaryButton:hover, QPushButton[primary="true"]:hover,
QToolButton#primaryButton:hover, QToolButton[primary="true"]:hover {
    background: $accentHover;
    border-color: $accentHover;
}
QPushButton#primary:pressed, QPushButton#primaryButton:pressed, QPushButton[primary="true"]:pressed,
QToolButton#primaryButton:pressed, QToolButton[primary="true"]:pressed {
    background: $accentPressed;
    border-color: $accentPressed;
}
QPushButton#primary:focus, QPushButton#primaryButton:focus, QPushButton[primary="true"]:focus,
QToolButton#primaryButton:focus, QToolButton[primary="true"]:focus {
    border-color: $accentPressed;
}
QPushButton#primary:disabled, QPushButton#primaryButton:disabled, QPushButton[primary="true"]:disabled,
QToolButton#primaryButton:disabled, QToolButton[primary="true"]:disabled {
    color: $textSecondary;
    background: $divider;
    border-color: $divider;
}
QToolButton::menu-button {
    border: 0;
    border-left: 1px solid $divider;
    width: 14px;
}
QToolButton::menu-button:hover {
    background: $accentSoft;
}
QMenuBar {
    background: $titleSurface;
    border: 0;
    padding: 2px 7px;
    spacing: 3px;
}
QMenuBar::item {
    background: transparent;
    border-radius: 4px;
    padding: 6px 12px;
}
QMenuBar::item:selected, QMenuBar::item:pressed {
    background: $accentSoft;
    color: $accent;
}
QMenu {
    background: $panelSurface;
    border: 1px solid $divider;
    border-radius: 6px;
    padding: 5px;
}
QMenu::item {
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 7px 30px 7px 10px;
    margin: 1px 0;
}
QMenu::item:selected {
    background: $accentSoft;
    color: $accent;
    border-color: $accentBorder;
}
QMenu::item:disabled {
    color: $disabledText;
}
QMenu::separator {
    height: 1px;
    background: $divider;
    margin: 5px 8px;
}
QMenu::icon {
    padding-left: 5px;
}
QLineEdit, QComboBox, QAbstractSpinBox {
    background: $panelSurface;
    color: $text;
    border: 1px solid $controlBorder;
    border-radius: 4px;
    min-height: 20px;
    padding: 4px 6px;
    selection-background-color: $accent;
    selection-color: white;
}
QLineEdit:hover, QComboBox:hover, QAbstractSpinBox:hover {
    border-color: $textSecondary;
}
QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus {
    border: 2px solid $accent;
    padding: 3px 5px;
}
QLineEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled {
    background: $appBackground;
    color: $disabledText;
    border-color: $divider;
}
QComboBox::drop-down {
    border: 0;
    width: 22px;
}
QComboBox QAbstractItemView {
    background: $panelSurface;
    color: $text;
    border: 1px solid $controlBorder;
    padding: 4px;
    selection-background-color: $accentSoft;
    selection-color: $accent;
    outline: 0;
}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {
    width: 18px;
    border: 0;
    background: $hoverSurface;
}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {
    background: $accentSoft;
}
QCheckBox, QRadioButton {
    color: $text;
    font-family: "Malgun Gothic", "Segoe UI";
    font-size: ${uiFontSize}pt;
    spacing: 7px;
    padding: 3px 0;
}
QCheckBox:disabled, QRadioButton:disabled {
    color: $disabledText;
}
QCheckBox::indicator, QRadioButton::indicator {
    width: 16px;
    height: 16px;
}
QWidget#pagePanel, QWidget#inspectorPanel, QWidget#inspectorPage, QWidget#sourcePanel,
QWidget#welcomePage, QScrollArea#inspectorScroll, QDockWidget {
    background: $panelSurface;
}
QWidget#pagePanel {
    border-right: 1px solid $divider;
}
QLabel#pagePanelNote {
    color: $textSecondary;
    font-size: ${smallFontSize}pt;
    padding: 8px 4px;
}
QListWidget {
    background: $panelSurface;
    border: 0;
    outline: 0;
}
QListWidget::item {
    padding: 8px;
    margin: 3px 5px;
    border: 2px solid transparent;
    border-radius: 5px;
}
QListWidget::item:hover {
    background: $hoverSurface;
    border-color: $divider;
}
QListWidget::item:selected {
    background: $accentSoft;
    color: $accent;
    border-color: $accent;
}
QListWidget::item:focus {
    border-color: $accent;
}
QDockWidget {
    color: $text;
    border: 0;
    font-weight: 600;
}
QDockWidget::title {
    background: $panelSurface;
    padding: 10px 12px;
    border-bottom: 1px solid $divider;
    text-align: left;
}
QDockWidget::close-button {
    border: 1px solid transparent;
    border-radius: 4px;
    background: transparent;
}
QDockWidget::close-button:hover {
    background: $hoverSurface;
    border-color: $divider;
}
QDockWidget QTextEdit, QDockWidget QPlainTextEdit,
QDialog QTextEdit, QDialog QPlainTextEdit {
    background: $panelSurface;
    color: $text;
    border: 1px solid $controlBorder;
    border-radius: 4px;
    padding: 7px;
    font-family: "Malgun Gothic", "Segoe UI";
    font-size: ${uiFontSize}pt;
    selection-background-color: $accent;
    selection-color: white;
}
QDockWidget QTextEdit:focus, QDockWidget QPlainTextEdit:focus,
QDialog QTextEdit:focus, QDialog QPlainTextEdit:focus {
    border-color: $accent;
}
QTabWidget#inspectorTabs::pane {
    background: $panelSurface;
    border: 0;
    border-top: 1px solid $divider;
}
QTabBar#inspectorTabs::tab, QTabWidget#inspectorTabs QTabBar::tab {
    background: $panelSurface;
    color: $textSecondary;
    border: 0;
    border-bottom: 2px solid transparent;
    padding: 8px 10px;
}
QTabBar#inspectorTabs::tab:selected, QTabWidget#inspectorTabs QTabBar::tab:selected {
    color: $accent;
    border-bottom-color: $accent;
}
QTabBar#inspectorTabs::tab:hover, QTabWidget#inspectorTabs QTabBar::tab:hover {
    background: $accentSoft;
}
QLabel#inspectorSectionTitle {
    color: $text;
    font-weight: 600;
    padding: 7px 0 2px 0;
}
QLabel#inspectorHint {
    color: $textSecondary;
    font-size: ${smallFontSize}pt;
}
QLabel#inspectorNotice {
    color: $accentPressed;
    background: $accentSoft;
    border: 1px solid $accentBorder;
    border-radius: 6px;
    padding: 10px;
}
QLabel#sourceCrop {
    background: $appBackground;
    border: 1px solid $divider;
    border-radius: 4px;
    padding: 6px;
}
QComboBox#inspectorSelector {
    margin: 6px 10px;
}
QGroupBox {
    background: $panelSurface;
    border: 1px solid $divider;
    border-radius: 6px;
    margin-top: 12px;
    padding: 12px 10px 8px 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 9px;
    padding: 0 4px;
    color: $textSecondary;
}
QSplitter::handle {
    background: $divider;
    width: 1px;
    height: 1px;
}
QSplitter::handle:hover {
    background: $accentBorder;
}
QGraphicsView#workspace {
    border: 0;
    background: $workspace;
}
QStatusBar {
    background: $panelSurface;
    border-top: 1px solid $divider;
    min-height: 28px;
    padding: 0 5px;
}
QStatusBar::item {
    border: 0;
}
QStatusBar QLabel {
    color: $textSecondary;
    font-size: ${smallFontSize}pt;
    padding: 3px 6px;
}
QStatusBar QPushButton, QStatusBar QToolButton {
    background: transparent;
    border: 1px solid transparent;
    padding: 2px 7px;
    min-height: 20px;
}
QStatusBar QPushButton:hover, QStatusBar QToolButton:hover {
    background: $accentSoft;
    border-color: $accentBorder;
}
QStatusBar QPushButton:focus, QStatusBar QToolButton:focus {
    border-color: $accent;
}
QScrollBar:vertical {
    background: $appBackground;
    width: 10px;
    margin: 2px;
    border: 0;
}
QScrollBar:horizontal {
    background: $appBackground;
    height: 10px;
    margin: 2px;
    border: 0;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: #B7C2CF;
    border-radius: 3px;
    min-height: 28px;
    min-width: 28px;
}
QScrollBar::handle:hover {
    background: $controlBorder;
}
QScrollBar::add-line, QScrollBar::sub-line {
    height: 0;
    width: 0;
    border: 0;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}
QSlider::groove:horizontal {
    height: 3px;
    background: $divider;
    border-radius: 1px;
}
QSlider::sub-page:horizontal {
    background: $accent;
    border-radius: 1px;
}
QSlider::handle:horizontal {
    background: $panelSurface;
    border: 2px solid $accent;
    width: 10px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover {
    background: $accentSoft;
}
QProgressBar {
    background: $accentSoft;
    color: $text;
    border: 1px solid $divider;
    border-radius: 4px;
    min-height: 8px;
    text-align: center;
}
QProgressBar::chunk {
    background: $accent;
    border-radius: 3px;
}
QToolTip {
    background: $panelSurface;
    color: $text;
    border: 1px solid $controlBorder;
    border-radius: 4px;
    padding: 7px 9px;
    font-family: "Malgun Gothic", "Segoe UI";
    font-size: ${smallFontSize}pt;
}
""")


def stylesheet(base_font_size: float = 10.0) -> str:
    """Return UI styling without changing the document's font or palette."""
    size = max(10.0, float(base_font_size))
    return _STYLESHEET.substitute(
        COLORS,
        uiFontSize=f"{size:g}",
        smallFontSize=f"{max(9.0, size - 1):g}",
        titleFontSize=f"{size + 1:g}",
        dialogTitleFontSize=f"{size + 4:g}",
    )


def apply_theme(editor: QWidget) -> None:
    """Style one editor and its dialogs while honoring a larger UI font."""
    editor.setProperty("blueOffice", True)
    editor.setStyleSheet(stylesheet(editor.font().pointSizeF()))
