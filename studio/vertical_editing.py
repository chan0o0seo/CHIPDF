"""Vertical hit testing and caret display over Qt's existing rich-text editor.

Qt still owns text input, IME replacement, clipboard, and document undo. Only
visual navigation/selection and the preedit preview use the vertical layout.
Composition is rendered from a clone and never serialized as committed text.
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QInputMethodEvent, QTextCursor, QTextCharFormat

from .vertical_text import VerticalLayout


class VerticalEditing:
    def init_vertical(self):
        self._vertical_cache_key = None
        self._vertical_cache = None
        self._vertical_document = None
        self._composition_revision = 0
        self._composition_attributes = []
        self._vertical_drag = False
        self._display_caret = 0

    @property
    def is_vertical(self):
        return self.model.writing_mode == 'vertical-rl'

    def vertical_layout(self, include_preedit=True):
        document = self.document()
        composing = bool(include_preedit and self.editing and self.preedit)
        key = (document.revision(), self.model.width, self.model.height, self.model.margin,
               composing, self._composition_revision, self.textCursor().position() if composing else None)
        if key == self._vertical_cache_key:
            return self._vertical_cache
        self._vertical_document = None
        if composing:
            block = document.begin()
            while block.isValid():
                layout = block.layout()
                if layout.preeditAreaText():
                    position = block.position() + layout.preeditAreaPosition()
                    text = layout.preeditAreaText()
                    document = document.clone()
                    document.setUndoRedoEnabled(False)
                    cursor = QTextCursor(document)
                    cursor.setPosition(position)
                    fmt = self.textCursor().charFormat()
                    fmt.setFontUnderline(True)
                    cursor.insertText(text, fmt)
                    length = len(text.encode('utf-16-le')) // 2
                    self._display_caret = position + length
                    for attribute in self._composition_attributes:
                        if attribute.type == QInputMethodEvent.Cursor:
                            self._display_caret = position + max(0, min(length, attribute.start))
                        elif attribute.type == QInputMethodEvent.TextFormat:
                            start = max(0, min(length, attribute.start))
                            end = max(start, min(length, attribute.start + attribute.length))
                            value = attribute.value
                            if hasattr(value, 'toCharFormat'):
                                value = value.toCharFormat()
                            if isinstance(value, QTextCharFormat):
                                cursor.setPosition(position + start)
                                cursor.setPosition(position + end, QTextCursor.KeepAnchor)
                                cursor.mergeCharFormat(value)
                    self._vertical_document = document
                    break
                block = block.next()
        self._vertical_cache = VerticalLayout(document, self.model.width, self.model.height, self.model.margin)
        self._vertical_cache_key = key
        return self._vertical_cache

    def has_overflow(self):
        if self.is_vertical:
            return self.vertical_layout().overflow
        return self.document().size().height() > self.model.height + 1

    def paint_vertical(self, painter):
        layout = self.vertical_layout()
        cursor = self.textCursor()
        controls = self.editing and self.scene() and self.scene().show_controls
        start = cursor.selectionStart() if controls and not self.preedit else None
        end = cursor.selectionEnd() if controls and not self.preedit else None
        layout.paint(painter, start, end)
        if controls and self.hasFocus():
            position = self._display_caret if self.preedit else cursor.position()
            # A horizontal insertion bar follows the top-to-bottom writing axis.
            painter.fillRect(layout.caret_rect(position), QColor('#236a64'))

    def _vertical_cursor_changed(self):
        if not getattr(self, 'editing', False) or not self.is_vertical:
            return
        self.update()
        QGuiApplication.inputMethod().update(Qt.ImQueryInput)

    def setTextCursor(self, cursor):
        super().setTextCursor(cursor)
        self._vertical_cursor_changed()

    def inputMethodQuery(self, query):
        if getattr(self, 'model', None) and self.is_vertical and self.editing:
            if query in (Qt.ImCursorRectangle, Qt.ImAnchorRectangle):
                cursor = self.textCursor()
                layout = self.vertical_layout()
                position = cursor.anchor() if query == Qt.ImAnchorRectangle else self._display_caret if self.preedit else cursor.position()
                return layout.caret_rect(position)
            if query == Qt.ImInputItemClipRectangle:
                return QRectF(0, 0, self.model.width, self.model.height)
        return super().inputMethodQuery(query)

    def inputMethodEvent(self, event):
        self.preedit = bool(event.preeditString())
        self._composition_revision += 1
        self._composition_attributes = list(event.attributes())
        # The native Qt text control implements replacementStart/Length and
        # selection attributes, including Korean reconversion, in UTF-16 units.
        cursor = self.textCursor()
        replace_selection = self.is_vertical and cursor.hasSelection() and bool(event.commitString() or event.preeditString() or event.replacementLength())
        if replace_selection:
            # Qt removes the selection before IME insertion. Keep its typing
            # format when the entire formatted run is being replaced.
            fmt = cursor.charFormat()
            cursor.beginEditBlock()
            cursor.removeSelectedText()
            cursor.setCharFormat(fmt)
            self.setTextCursor(cursor)
        try:
            super().inputMethodEvent(event)
        finally:
            if replace_selection:
                cursor.endEditBlock()
        self._vertical_cursor_changed()

    def clear_vertical_composition(self):
        if self.is_vertical:
            super().inputMethodEvent(QInputMethodEvent('', []))
            self._composition_revision += 1
            self._composition_attributes = []

    def _vertical_point_cursor(self, point, extend=False):
        QGuiApplication.inputMethod().commit()
        cursor = self.textCursor()
        cursor.setPosition(self.vertical_layout(False).hit_test(point),
                           QTextCursor.KeepAnchor if extend else QTextCursor.MoveAnchor)
        self.setTextCursor(cursor)

    def mousePressEvent(self, event):
        if self.is_vertical and self.editing and event.button() == Qt.LeftButton:
            self._vertical_point_cursor(event.pos(), bool(event.modifiers() & Qt.ShiftModifier))
            self._vertical_drag = True
            self.setFocus(Qt.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_vertical and self.editing:
            if self._vertical_drag and event.buttons() & Qt.LeftButton:
                self._vertical_point_cursor(event.pos(), True)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.is_vertical and self.editing:
            self._vertical_drag = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if not self.editor.can_interact(self.model):
            event.accept()
            return
        self.begin_edit()
        if self.is_vertical:
            self._vertical_point_cursor(event.pos())
            cursor = self.textCursor()
            cursor.select(QTextCursor.WordUnderCursor)
            self.setTextCursor(cursor)
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if not self.editing:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.begin_edit()
                event.accept()
            else:
                event.ignore()
            return
        if event.key() == Qt.Key_Escape and not self.preedit:
            self.finish_edit()
            event.accept()
            return
        directions = {Qt.Key_Left: 'left', Qt.Key_Right: 'right', Qt.Key_Up: 'up',
                      Qt.Key_Down: 'down', Qt.Key_Home: 'home', Qt.Key_End: 'end'}
        if self.is_vertical and not self.preedit and event.key() in directions and not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            cursor = self.textCursor()
            direction = directions[event.key()]
            extend = bool(event.modifiers() & Qt.ShiftModifier)
            if cursor.hasSelection() and not extend and direction in ('up', 'down'):
                position = cursor.selectionStart() if direction == 'up' else cursor.selectionEnd()
            else:
                position = self.vertical_layout(False).move_cursor(cursor.position(), direction)
            cursor.setPosition(position, QTextCursor.KeepAnchor if extend else QTextCursor.MoveAnchor)
            self.setTextCursor(cursor)
            event.accept()
            return
        if self.is_vertical and not self.preedit and event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            cursor = self.textCursor()
            if not cursor.hasSelection():
                layout = self.vertical_layout(False)
                position = cursor.position()
                boundaries = layout.boundaries
                if event.key() == Qt.Key_Backspace:
                    target = max((p for p in boundaries if p < position), default=position)
                else:
                    target = min((p for p in boundaries if p > position), default=position)
                cursor.setPosition(target, QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
            self.setTextCursor(cursor)
            event.accept()
            return
        super().keyPressEvent(event)
        self._vertical_cursor_changed()
