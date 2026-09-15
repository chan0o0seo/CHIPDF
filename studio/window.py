from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (QAction, QColor, QFont, QIcon, QImage, QImageReader, QKeySequence,
                          QPainter, QPixmap, QTextBlockFormat, QTextCharFormat, QTextCursor,
                          QUndoCommand, QUndoStack)
from PySide6.QtWidgets import (QApplication, QColorDialog, QComboBox, QDoubleSpinBox,
                              QFileDialog, QFontComboBox, QHBoxLayout, QLabel, QListWidget,
                              QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
                              QSplitter, QStackedWidget, QToolBar, QVBoxLayout, QWidget)

from .canvas import Canvas, CardScene, TextItem
from .model import Page, Project, TextBox, uid
from .richtext import ALIGN
from .storage import atomic_write, load_project, save_project
from .workflow import Workflow
from .editing import Editing
from .object_items import VisualItem, GroupItem, validate_images
from .model import GroupBox
from .layout_tools import LayoutTools, move_in_scene
from .collection import Collection
from .document_io import import_files
from .presets import Presets
from .font_favorites import FontFavorites
from . import APP_NAME, __version__


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise OSError("PNG 이미지 변환에 실패했습니다.")
    return bytes(data)


class Change(QUndoCommand):
    def __init__(self, editor, before, after, label, before_page, after_page):
        super().__init__(label)
        self.editor, self.before, self.after = editor, before, after
        self.first = True
        self.before_page, self.after_page = before_page, after_page

    def undo(self):
        self.editor.apply_snapshot(self.before, self.before_page)

    def redo(self):
        if self.first:
            self.first = False
        else:
            self.editor.apply_snapshot(self.after, self.after_page)


class Editor(QMainWindow, Workflow, Editing, LayoutTools, Collection, Presets, FontFavorites):
    def __init__(self, data_dir: Path, auto_ocr=False):
        super().__init__()
        self.data_dir = Path(data_dir)
        self.project = None
        self.page_index = 0
        self.assets = {}
        self.operation_page_id = None
        self.original = b""
        self.image = QImage()
        self.project_path = None
        self.source_path = None
        self.items_by_id = {}
        self.operation_before = None
        self.loading = False
        self.dirty = False
        self.comparing = False
        self.active_group_id = ""
        self.last_error = None
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(100)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(850)
        self.save_timer.timeout.connect(self.autosave)
        self.setWindowTitle(APP_NAME)
        self.resize(1260, 880)
        self.setMinimumSize(900, 600)
        self.scene = CardScene(self)
        self.canvas = Canvas(self.scene, self)
        self.canvas.file_dropped.connect(self.open_path)
        self.canvas.files_dropped.connect(self.open_sources)
        self.scene.selectionChanged.connect(self.update_tools)
        self.make_ui()
        self.init_workflow(auto_ocr)
        self.init_editing()
        self.init_layout_tools()
        self.init_collection()
        self.init_presets()
        self.init_font_favorites()
        self.undo_stack.indexChanged.connect(self.update_tools)
        self.update_tools()

    def action(self, label, callback, shortcut=None, checkable=False):
        action = QAction(label, self)
        action.setCheckable(checkable)
        action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        self.addAction(action)
        return action

    def make_ui(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #f8f9f7; color: #243c3a; }
            QToolBar { border: 0; border-bottom: 1px solid #dfe5e1; spacing: 7px; padding: 8px 12px; }
            QToolButton, QPushButton { border: 1px solid transparent; padding: 7px 12px; border-radius: 5px; }
            QToolButton:hover, QPushButton:hover { background: #e4eee9; }
            QToolButton:checked { background: #d8e9e2; }
            QToolButton:disabled { color: #a2ada7; }
            QPushButton#primary { background: #2e7068; color: white; padding: 12px 24px; }
            QPushButton#primary:hover { background: #235c55; }
            QComboBox, QDoubleSpinBox { border: 1px solid #d5dfd8; border-radius: 4px; padding: 5px; background: white; }
            QListWidget { border: 0; background: #f5f7f4; outline: 0; }
            QListWidget::item { padding: 12px; border-radius: 6px; }
            QListWidget::item:selected { background: #dfece5; color: #234f48; }
            QStatusBar { background: #f8f9f7; border-top: 1px solid #dfe5e1; }
            QSplitter::handle { background: #dfe5e1; width: 1px; }
        """)
        self.open_action = self.action("열기", self.choose_open, "Ctrl+O")
        self.save_action = self.action("작업 저장", self.save, "Ctrl+S")
        self.save_as_action = self.action("다른 이름으로 저장", lambda: self.save(save_as=True), "Ctrl+Shift+S")
        self.add_action = self.action("＋ 텍스트", self.add_text, "Ctrl+T")
        self.undo_action = self.action("실행 취소", self.undo, "Ctrl+Z")
        self.redo_action = self.action("다시 실행", self.redo, "Ctrl+Y")
        self.action("다시 실행", self.redo, "Ctrl+Shift+Z")
        self.duplicate_action = self.action("복제", self.duplicate, "Ctrl+D")
        self.compare_action = self.action("원본 비교", self.compare, checkable=True)
        self.export_action = self.action("완성본 저장", self.choose_export, "Ctrl+Shift+E")
        self.file_menu = self.menuBar().addMenu("파일")
        self.file_menu.addActions([self.open_action, self.save_action, self.save_as_action, self.export_action])
        edit_menu = self.menuBar().addMenu("편집")
        self.edit_menu = edit_menu
        edit_menu.addActions([self.undo_action, self.redo_action, self.add_action, self.duplicate_action])
        self.delete_action = self.action("삭제", self.delete_selected)
        edit_menu.addAction(self.delete_action)
        help_menu = self.menuBar().addMenu("도움말")
        help_menu.addAction(self.action("이 시제품에서 할 수 있는 일", self.show_about))
        main = QToolBar("기본 도구")
        self.main_toolbar = main
        main.setMovable(False)
        self.addToolBar(main)
        main.addAction(self.open_action)
        main.addSeparator()
        main.addAction(self.add_action)
        main.addAction(self.undo_action)
        main.addAction(self.redo_action)
        stretch = QWidget()
        stretch.setSizePolicy(stretch.sizePolicy().Policy.Expanding, stretch.sizePolicy().Policy.Preferred)
        main.addWidget(stretch)
        main.addAction(self.compare_action)
        main.addAction(self.save_action)
        main.addAction(self.export_action)
        self.addToolBarBreak()
        self.format_bar = QToolBar("글자 서식")
        self.format_bar.setMovable(False)
        self.addToolBar(self.format_bar)
        self.font_box = QFontComboBox()
        self.font_box.setFixedWidth(178)
        self.font_box.activated.connect(lambda: self.format_font())
        self.format_bar.addWidget(self.font_box)
        self.size_box = QDoubleSpinBox()
        self.size_box.setRange(1, 400)
        self.size_box.setDecimals(1)
        self.size_box.setSuffix(" pt")
        self.size_box.setFixedWidth(94)
        self.size_box.valueChanged.connect(self.format_size)
        self.format_bar.addWidget(self.size_box)
        self.bold_action = self.action("굵게", lambda checked: self.format_flag("bold", checked), checkable=True)
        self.italic_action = self.action("기울임", lambda checked: self.format_flag("italic", checked), checkable=True)
        self.underline_action = self.action("밑줄", lambda checked: self.format_flag("underline", checked), checkable=True)
        self.format_bar.addActions([self.bold_action, self.italic_action, self.underline_action])
        self.format_bar.addAction(self.action("글자색", self.choose_color))
        self.align_box = QComboBox()
        self.align_box.addItems(["왼쪽 정렬", "가운데 정렬", "오른쪽 정렬"])
        self.align_box.activated.connect(self.format_alignment)
        self.format_bar.addWidget(self.align_box)
        self.fill_action = self.action("흰 배경", self.toggle_fill, checkable=True)
        self.fill_action.setToolTip("선택한 상자에 흰 배경을 넣습니다. 원본은 보존됩니다.")
        self.format_bar.addAction(self.fill_action)
        self.format_bar.addAction(self.duplicate_action)
        self.format_bar.addAction(self.delete_action)

        splitter = QSplitter()
        sidebar = QWidget()
        sidebar.setMinimumWidth(180)
        sidebar.setMaximumWidth(260)
        side = QVBoxLayout(sidebar)
        label = QLabel("작업 자료")
        label.setStyleSheet("font-weight: 600; padding: 12px 6px;")
        side.addWidget(label)
        self.card_list = QListWidget()
        self.card_list.setIconSize(QSize(140, 150))
        self.card_list.setViewMode(QListWidget.IconMode)
        self.card_list.setResizeMode(QListWidget.Adjust)
        self.card_list.setMovement(QListWidget.Static)
        side.addWidget(self.card_list)
        sidebar_note = QLabel("카드 클릭으로 전환 · Ctrl/Shift로 여러 장 선택")
        sidebar_note.setWordWrap(True)
        sidebar_note.setStyleSheet("color: #72817b; padding: 8px; font-size: 11px;")
        side.addWidget(sidebar_note)
        splitter.addWidget(sidebar)
        self.center = QStackedWidget()
        welcome = QWidget()
        layout = QVBoxLayout(welcome)
        layout.addStretch()
        eyebrow = QLabel("TRANSLATION STUDIO")
        eyebrow.setAlignment(Qt.AlignCenter)
        eyebrow.setStyleSheet("color: #578177; font-size: 12px; letter-spacing: 3px;")
        title = QLabel("자료 위에서, 바로 편집")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 32px; font-weight: 600; padding: 12px;")
        desc = QLabel("일본어 문장을 사각형으로 선택하세요.\n원문을 확인하고, 한국어를 입력하거나 번역을 누르세요.")
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet("color: #75827b; font-size: 14px; line-height: 1.6;")
        button_row = QHBoxLayout()
        button_row.addStretch()
        open_button = QPushButton("PDF·이미지·작업 열기")
        open_button.setObjectName("primary")
        open_button.clicked.connect(self.choose_open)
        button_row.addWidget(open_button)
        button_row.addStretch()
        layout.addWidget(eyebrow)
        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addSpacing(24)
        layout.addLayout(button_row)
        try:
            recent = json.loads((self.data_dir / "recent.json").read_text("utf-8"))
            recent_path = Path(recent["path"])
            if recent_path.exists():
                resume = QPushButton("마지막 작업 이어서 열기")
                resume.clicked.connect(lambda: self.open_path(str(recent_path)))
                layout.addWidget(resume, alignment=Qt.AlignCenter)
        except (OSError, ValueError, KeyError):
            pass
        layout.addStretch()
        self.center.addWidget(welcome)
        self.center.addWidget(self.canvas)
        splitter.addWidget(self.center)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([206, 1054])
        self.setCentralWidget(splitter)
        self.status = QLabel("PDF · 이미지 · 작업 파일을 열 수 있습니다")
        self.status.setStyleSheet("padding: 5px 12px; color: #61736a;")
        self.statusBar().addWidget(self.status, 1)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(48)
        for label, callback in [("−", lambda: self.canvas.zoom(1 / 1.15)), ("＋", lambda: self.canvas.zoom(1.15)), ("화면에 맞춤", self.canvas.fit_page)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            self.statusBar().addPermanentWidget(button)
        self.statusBar().addPermanentWidget(self.zoom_label)
        self.canvas.zoom_changed.connect(lambda value: self.zoom_label.setText(f"{value}%"))

    def selected(self):
        return [item for item in self.scene.selectedItems() if isinstance(item, (TextItem, VisualItem, GroupItem)) and item.model.parent_id == self.active_group_id]

    def editing_item(self):
        return next((item for item in self.items_by_id.values() if item.editing), None)

    def finish_edit(self):
        item = self.editing_item()
        if item:
            item.finish_edit()

    def begin_operation(self):
        if self.project and self.operation_before is None:
            self.operation_before = deepcopy(self.project)
            self.operation_page_id = self.current_page.id

    def sync_positions(self):
        for item in self.items_by_id.values():
            item.model.x, item.model.y = item.pos().x(), item.pos().y()
            item.model.rotation = item.rotation()
            item.model.scale = item.scale()

    def finish_operation(self, label):
        self.sync_positions()
        self.reframe_groups()
        self.sync_positions()
        before, self.operation_before = self.operation_before, None
        if before and before != self.project:
            self.undo_stack.push(Change(self, before, deepcopy(self.project), label, self.operation_page_id, self.current_page.id))
            self.changed()
        self.update_tools()

    def apply_snapshot(self, project, page_id=None):
        view = self.capture_canvas_view()
        self.invalidate_jobs()
        selection = [i.model.id for i in self.selected()]
        page_id = page_id or self.current_page.id
        self.project = deepcopy(project)
        index = next((i for i, p in enumerate(self.project.pages) if p.id == page_id), 0)
        same_page = view is not None and view[:2] == (self.project.id, self.project.pages[index].id)
        self.activate_page(index, selection, keep_scope=True, fit_view=not same_page)
        self.refresh_card_list()
        self.changed()
        self.restore_canvas_view(view)

    def capture_canvas_view(self):
        if not self.project:
            return None
        canvas = self.canvas
        viewport_size = canvas.viewport().size()
        inverse, invertible = canvas.viewportTransform().inverted()
        if not invertible:
            return None
        center = inverse.map(QPointF(viewport_size.width() / 2, viewport_size.height() / 2))
        return (self.project.id, self.current_page.id, canvas.transform(), center,
                viewport_size, canvas.horizontalScrollBar().value(), canvas.verticalScrollBar().value())

    def restore_canvas_view(self, view):
        if view is None or not self.project or view[:2] != (self.project.id, self.current_page.id):
            return
        _, _, transform, center, viewport_size, horizontal, vertical = view
        canvas = self.canvas
        if canvas.transform() != transform:
            canvas.setTransform(transform)
            canvas.zoom_changed.emit(round(transform.m11() * 100))
        if canvas.viewport().size() == viewport_size:
            # Reuse the exact scroll offsets to avoid rounding drift after repeated edits.
            canvas.horizontalScrollBar().setValue(horizontal)
            canvas.verticalScrollBar().setValue(vertical)
        else:
            canvas.centerOn(center)

    def changed(self):
        if self.loading or not self.project:
            return
        self.dirty = True
        self.status.setText("변경 사항 저장 중…")
        self.save_timer.start()
        if hasattr(self, "background_timer"):
            self.background_timer.start()
        self.update_undo()

    def rebuild_scene(self, selection=()):
        view = self.capture_canvas_view()
        self.canvas.cancel_stamp_stroke()
        self.loading = True
        self.items_by_id = {}
        self.scene.clear()
        self.scene.snap_guides = []
        background = self.scene.addPixmap(QPixmap.fromImage(self.image))
        self.background_item = background
        background.setZValue(-1)
        page = self.current_page
        self.scene.setSceneRect(-60, -60, page.width + 120, page.height + 120)
        for obj in page.objects:
            item = TextItem(obj, self) if isinstance(obj, TextBox) else GroupItem(obj, self) if isinstance(obj, GroupBox) else VisualItem(obj, self)
            self.scene.addItem(item)
            self.items_by_id[obj.id] = item
            item.setVisible(not self.comparing)
        for obj in page.objects:
            if obj.parent_id:
                self.items_by_id[obj.id].setParentItem(self.items_by_id[obj.parent_id])
        self.configure_scope()
        for obj in page.objects:
            self.items_by_id[obj.id].setSelected(obj.id in selection and obj.parent_id == self.active_group_id)
        self.loading = False
        self.refresh_background()
        self.update_tools()
        self.restore_canvas_view(view)

    def update_undo(self):
        if not hasattr(self, "undo_action"):
            return
        item = self.editing_item()
        self.undo_action.setEnabled(item.document().isUndoAvailable() if item else self.undo_stack.canUndo())
        self.redo_action.setEnabled(item.document().isRedoAvailable() if item else self.undo_stack.canRedo())

    def update_tools(self):
        if self.loading or not hasattr(self, "format_bar"):
            return
        selected = self.selected()
        editable = bool(self.project) and not self.comparing
        for action in (self.save_action, self.save_as_action, self.export_action, self.compare_action):
            action.setEnabled(bool(self.project))
        self.add_action.setEnabled(editable)
        mutable = bool(self.mutable_selection())
        self.duplicate_action.setEnabled(editable and mutable)
        self.delete_action.setEnabled(editable and mutable)
        all_text = bool(selected) and all(isinstance(i.model, TextBox) for i in selected)
        self.format_bar.setVisible(editable and mutable and all_text)
        if all_text:
            item = selected[0]
            style = item.model.paragraphs[0].runs[0].style
            for widget in (self.font_box, self.size_box, self.align_box):
                widget.blockSignals(True)
            self.font_box.setCurrentFont(QFont(style.family))
            self.size_box.setValue(style.size)
            self.align_box.setCurrentIndex(["left", "center", "right"].index(item.model.paragraphs[0].align))
            vertical = item.model.writing_mode == 'vertical-rl'
            for i, label in enumerate(['위쪽 정렬', '가운데 정렬', '아래쪽 정렬'] if vertical else ['왼쪽 정렬', '가운데 정렬', '오른쪽 정렬']):
                self.align_box.setItemText(i, label)
            if hasattr(self, 'vertical_action'):
                self.vertical_action.setChecked(all(i.model.writing_mode == 'vertical-rl' for i in selected))
            for widget in (self.font_box, self.size_box, self.align_box):
                widget.blockSignals(False)
            self.bold_action.setChecked(style.bold)
            self.italic_action.setChecked(style.italic)
            self.underline_action.setChecked(style.underline)
            self.fill_action.setChecked(item.model.fill == "#ffffff")
            self.update_font_favorite()
        self.update_undo()
        self.update_workflow_tools()
        self.update_editing_tools()
        self.update_layout_tools()
        self.update_presets_tools()

    def set_writing_mode(self, mode):
        if mode not in ('horizontal', 'vertical-rl'):
            raise ValueError('글쓰기 방향이 올바르지 않습니다.')
        self.finish_edit()
        selected = self.mutable_selection()
        if not selected or not all(isinstance(i.model, TextBox) for i in selected):
            return
        ids = [i.model.id for i in selected]
        self.begin_operation()
        for item in selected:
            item.model.writing_mode = mode
        self.rebuild_scene(ids)
        self.finish_operation('세로쓰기' if mode == 'vertical-rl' else '가로쓰기')
        self.status.setText('세로쓰기 · 위에서 아래로 입력, 다음 열은 왼쪽 · 상자 크기는 손잡이로 조절' if mode == 'vertical-rl' else '가로쓰기로 변경됨')

    def add_text(self):
        if not self.project or self.comparing:
            return
        self.finish_edit()
        self.begin_operation()
        page = self.items_by_id[self.active_group_id].model if self.active_group_id else self.current_page
        width = min(420, page.width * 0.65)
        height = min(130, max(50, page.height * 0.15))
        obj = TextBox(x=(page.width - width) / 2, y=(page.height - height) / 2,
                      width=max(24, width), height=height,
                      parent_id=self.active_group_id, z=max((o.z for o in self.scope_objects()), default=-1) + 1)
        self.current_page.objects.append(obj)
        self.rebuild_scene([obj.id])
        self.finish_operation("텍스트 추가")
        item = self.items_by_id[obj.id]
        item.begin_edit()
        cursor = item.textCursor()
        cursor.select(QTextCursor.Document)
        item.setTextCursor(cursor)
        self.canvas.setFocus()

    def delete_selected(self):
        if self.comparing:
            return
        self.finish_edit()
        ids = self.descendants(i.model.id for i in self.mutable_selection())
        if not ids:
            return
        self.begin_operation()
        self.current_page.objects = [o for o in self.current_page.objects if o.id not in ids]
        self.rebuild_scene()
        self.finish_operation("상자 삭제")

    def duplicate(self):
        self.clone_selection()

    def nudge(self, dx, dy):
        if not self.mutable_selection():
            return
        self.begin_operation()
        for item in self.selected():
            move_in_scene(item, QPointF(dx, dy))
        self.finish_operation("이동")

    def undo(self):
        self.canvas.cancel_stamp_stroke()
        item = self.editing_item()
        if item:
            item.document().undo()
        else:
            self.undo_stack.undo()
        self.update_undo()

    def redo(self):
        self.canvas.cancel_stamp_stroke()
        item = self.editing_item()
        if item:
            item.document().redo()
        else:
            self.undo_stack.redo()
        self.update_undo()

    def apply_format(self, fmt=None, align=None):
        selected = self.mutable_selection()
        if not selected or not all(isinstance(i.model, TextBox) for i in selected):
            return
        self.begin_operation()
        editing = self.editing_item()
        for item in selected:
            cursor = item.textCursor() if item.editing else QTextCursor(item.document())
            if not item.editing:
                cursor.select(QTextCursor.Document)
            if fmt:
                cursor.mergeCharFormat(fmt)
                if item.editing:
                    item.setTextCursor(cursor)
            if align:
                block = QTextBlockFormat()
                block.setAlignment(ALIGN[align])
                cursor.mergeBlockFormat(block)
        if not editing:
            self.finish_operation("글자 서식")
        if editing:
            self.canvas.setFocus()

    def format_font(self):
        fmt = QTextCharFormat()
        fmt.setFontFamilies([self.font_box.currentFont().family()])
        self.apply_format(fmt)

    def format_size(self, value):
        fmt = QTextCharFormat()
        fmt.setFontPointSize(value)
        self.apply_format(fmt)

    def format_flag(self, kind, enabled):
        fmt = QTextCharFormat()
        if kind == "bold":
            fmt.setFontWeight(QFont.Bold if enabled else QFont.Normal)
        elif kind == "italic":
            fmt.setFontItalic(enabled)
        elif kind == "strike":
            fmt.setFontStrikeOut(enabled)
        else:
            fmt.setFontUnderline(enabled)
        self.apply_format(fmt)

    def choose_color(self):
        color = QColorDialog.getColor(parent=self, title="글자색")
        if color.isValid():
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            self.apply_format(fmt)

    def format_alignment(self, index):
        self.apply_format(align=["left", "center", "right"][index])

    def toggle_fill(self, checked):
        self.finish_edit()
        if not self.mutable_selection():
            return
        self.begin_operation()
        for item in self.selected():
            item.model.fill = "#ffffff" if checked else "transparent"
            item.update()
        self.finish_operation("상자 배경")

    def compare(self, checked):
        view = self.capture_canvas_view()
        self.finish_edit()
        self.canvas.cancel_tool()
        self.comparing = checked
        self.scene.snap_guides = []
        for item in self.items_by_id.values():
            item.setVisible(not checked)
        self.refresh_background()
        self.update_tools()

        self.restore_canvas_view(view)

    def choose_open(self):
        self.choose_sources()

    def open_path(self, path):
        self.open_sources([path])

    def load_path(self, path: Path):
        # Synchronous entry for tests and CLI verification; normal UI imports use a worker.
        self.install_collection(*import_files([path]))

    def recovery_path(self):
        return self.data_dir / "recovery" / f"{self.project.id}.twproj"

    def autosave(self):
        if not self.project or not self.dirty:
            return True
        self.sync_positions()
        path = self.project_path or self.recovery_path()
        try:
            save_project(path, self.project, self.assets)
            atomic_write(self.data_dir / "recent.json", json.dumps({"path": str(path)}, ensure_ascii=False).encode("utf-8"))
        except (OSError, ValueError) as exc:
            self.last_error = str(exc)
            self.status.setText("저장 실패 · 작업 저장에서 다른 위치를 선택해 주세요")
            return False
        self.dirty = False
        self.status.setText("자동 저장됨" + (" · 작업 저장으로 보관 위치 선택" if not self.project_path else ""))
        return True

    def save(self, checked=False, save_as=False):
        if not self.project:
            return
        self.finish_edit()
        path = self.project_path
        if not path or save_as:
            value, _ = QFileDialog.getSaveFileName(self, "작업 저장", self.project.name + ".twproj", f"{APP_NAME} (*.twproj)")
            if not value:
                return
            path = Path(value)
            if path.suffix.lower() != ".twproj":
                path = Path(str(path) + ".twproj")
        try:
            self.save_to(path)
        except (OSError, ValueError) as exc:
            self.report_error("작업을 저장하지 못했습니다", exc)

    def save_to(self, path):
        self.finish_edit()
        self.sync_positions()
        path = Path(path).resolve()
        if path in {Path(p.source_file).resolve() for p in self.project.pages if p.source_file}:
            raise ValueError("원본 자료에 작업 파일을 덮어쓸 수 없습니다.")
        save_project(path, self.project, self.assets)
        self.project_path = path
        atomic_write(self.data_dir / "recent.json", json.dumps({"path": str(path)}, ensure_ascii=False).encode("utf-8"))
        self.dirty = False
        self.save_timer.stop()
        self.status.setText("저장됨 · " + path.name)

    def render_image(self):
        if not self.project:
            raise ValueError("먼저 이미지를 열어 주세요.")
        self.finish_edit()
        page = self.current_page
        result = QImage(page.width, page.height, QImage.Format_ARGB32_Premultiplied)
        result.fill(Qt.transparent)
        self.scene.show_controls = False
        was_comparing = self.comparing
        self.comparing = False
        self.refresh_background()
        for item in self.items_by_id.values():
            item.setVisible(True)
        painter = QPainter(result)
        painter.setRenderHints(self.canvas.renderHints())
        try:
            self.scene.render(painter, QRectF(0, 0, page.width, page.height), QRectF(0, 0, page.width, page.height))
        finally:
            painter.end()
            self.scene.show_controls = True
            self.comparing = was_comparing
            self.refresh_background()
            for item in self.items_by_id.values():
                item.setVisible(not self.comparing)
            self.scene.update()
        return result

    def export_to(self, path):
        path = Path(path).resolve()
        self.check_output_path(path)
        atomic_write(path, png_bytes(self.render_image()))
        self.status.setText("완성본 저장됨 · " + path.name)

    def choose_export(self):
        self.choose_collection_export()

    def report_error(self, title, error):
        self.last_error = str(error)
        QMessageBox.warning(self, title, str(error))

    def show_about(self):
        QMessageBox.information(self, f"{APP_NAME} {__version__}",
            "문장을 사각형으로 선택해 읽고, 한국어를 입력하거나 번역합니다.\n"
            "브러시로 칠한 뒤 지우기를 누르면 해당 부분의 배경을 복원합니다.\n\n"
            "원문 확인 · 원문 수정 · 새 번역 후보 비교 · 글자 획 가리기\n"
            "한글 편집 · 부분 서식 · 이동/크기/회전 · 자동 저장 · PNG 출력\n\n"
            "로컬 번역은 오역이 있는 시험용 초안입니다. 원문과 대조해 주세요.\n"
            "도형·이미지 삽입 · 자르기·뒤집기 · 정렬·간격 · 앞뒤 순서·잠금\n"
            "그룹·안쪽 편집 · 맞춤 안내선 · 문단 간격·여백\nPDF·여러 카드 가져오기 · 작품 저장 · PNG/PDF 묶음 출력\n"
            "세로쓰기 · 이름으로 서식 저장 · 다른 카드에 글자 배치 적용\n"
            "개인 계정 설치 · 업데이트·제거 후에도 작업과 개인 서식 보존")

    def closeEvent(self, event):
        if self.io_job:
            self.io_job.cancelled.set()
        self.invalidate_jobs()
        self.finish_edit()
        self.save_timer.stop()
        if self.autosave():
            self.loading = True
            event.accept()
        else:
            answer = QMessageBox.question(self, "작업 저장 실패", "저장하지 못한 변경이 있습니다. 그래도 종료할까요?",
                                          QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel)
            event.accept() if answer == QMessageBox.Discard else event.ignore()
            if event.isAccepted():
                self.loading = True
