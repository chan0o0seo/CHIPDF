"""Focused checks for middle-button navigation and personal font shortcuts."""
import json
import unittest
from unittest.mock import patch

import test_studio as base
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontDatabase, QTextCursor
from PySide6.QtTest import QTest
from studio.window import Editor


class NavigationFontTests(unittest.TestCase):
    setUp = base.StudioTests.setUp
    tearDown = base.StudioTests.tearDown
    insert = base.StudioTests.insert

    def test_middle_drag_moves_both_axes_without_editing_in_each_tool(self):
        item = self.insert('화면 이동')
        self.editor.finish_edit()
        view = self.editor.canvas
        view.resetTransform()
        view.scale(3, 3)
        for tool in ('select', 'ocr', 'brush'):
            view.set_tool(tool)
            view.centerOn(360, 480)
            base.APP.processEvents()
            before = self.editor.project.to_dict()
            selection = [i.model.id for i in self.editor.selected()]
            undo_count = self.editor.undo_stack.count()
            bars = view.horizontalScrollBar(), view.verticalScrollBar()
            values = [bar.value() for bar in bars]
            cursor = view.viewport().cursor().shape()
            start = view.viewport().rect().center()
            end = start + QPoint(45, 35)
            QTest.mousePress(view.viewport(), Qt.MiddleButton, Qt.NoModifier, start)
            self.assertEqual(view.viewport().cursor().shape(), Qt.ClosedHandCursor)
            QTest.mouseMove(view.viewport(), end)
            QTest.mouseRelease(view.viewport(), Qt.MiddleButton, Qt.NoModifier, end)
            self.assertEqual([bar.value() for bar in bars], [values[0] - 45, values[1] - 35])
            self.assertEqual(view.viewport().cursor().shape(), cursor)
            self.assertIsNone(view._pan_position)
            self.assertEqual(view.tool, tool)
            self.assertEqual(self.editor.project.to_dict(), before)
            self.assertEqual([i.model.id for i in self.editor.selected()], selection)
            self.assertEqual(self.editor.undo_stack.count(), undo_count)
            self.assertTrue(view.brush_mask_image().isNull())
            self.assertIsNone(view._region_start)

    def test_favorite_partial_text_application_persistence_and_removal(self):
        # The offscreen Qt backend does not enumerate Windows system fonts.
        font_id = QFontDatabase.addApplicationFont(str(base.ROOT / '.deps/reportlab/fonts/Vera.ttf'))
        self.assertGreaterEqual(font_id, 0)
        self.addCleanup(QFontDatabase.removeApplicationFont, font_id)
        item = self.insert('ABC')
        original = item.model.paragraphs[0].runs[0].style.family
        family = next(name for name in QFontDatabase.families() if name != original)
        before = self.editor.project.to_dict()
        self.editor.set_font_favorite(family, True)
        self.assertEqual(self.editor.project.to_dict(), before)
        cursor = item.textCursor()
        cursor.setPosition(1)
        cursor.setPosition(2, QTextCursor.KeepAnchor)
        item.setTextCursor(cursor)
        self.editor.populate_font_favorites_menu()
        self.editor.font_favorites_menu.actions()[0].trigger()
        runs = item.model.paragraphs[0].runs
        self.assertEqual([(r.text, r.style.family) for r in runs],
                         [('A', original), ('B', family), ('C', original)])
        self.assertTrue(self.editor.font_favorite_action.isChecked())
        other = Editor(self.editor.data_dir)
        try:
            self.assertEqual(other.font_favorites, [family])
            other.set_font_favorite(family, False)
            self.assertEqual(json.loads(other.font_favorites_path.read_text('utf-8')), [])
        finally:
            other.close()
            other.deleteLater()

    def test_failed_favorite_save_keeps_previous_state(self):
        family = self.editor.font_box.currentFont().family()
        with patch('studio.font_favorites.atomic_write', side_effect=OSError('disk unavailable')):
            self.editor.font_favorite_action.trigger()
        self.assertEqual(self.editor.font_favorites, [])
        self.assertFalse(self.editor.font_favorite_action.isChecked())
        self.assertIn('저장하지 못했습니다', self.editor.status.text())


if __name__ == '__main__':
    unittest.main()
