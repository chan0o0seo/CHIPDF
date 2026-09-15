"""Native text-control integration: composition, selection, undo and output."""
from test_studio import APP, StudioTests
from copy import deepcopy
import json
import unittest

from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QInputMethodEvent, QTextCursor, QTextCharFormat
from PySide6.QtTest import QTest

from studio.document_io import render_page
from studio.model import Project
from studio.storage import load_project


class VerticalEditorTests(unittest.TestCase):
    setUp = StudioTests.setUp
    insert = StudioTests.insert
    pixels = StudioTests.pixels

    def tearDown(self):
        if APP.platformName() == 'offscreen':
            APP.clipboard().clear()
        StudioTests.tearDown(self)

    def vertical(self, text='한글 세로쓰기\n둘째 문단', width=200, height=280):
        item = self.insert(text)
        item.finish_edit()
        key = item.model.id
        item.model.width, item.model.height = width, height
        self.editor.rebuild_scene([key])
        self.editor.set_writing_mode('vertical-rl')
        return self.editor.items_by_id[key]

    def test_mode_switch_is_one_undo_and_preserves_source_and_rich_text(self):
        item = self.insert('원문과 독립된 번역')
        cursor = item.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(3, QTextCursor.KeepAnchor)
        item.setTextCursor(cursor)
        self.editor.format_flag('bold', True)
        item.finish_edit()
        item.model.source_text, item.model.source_rect = '原文', [1, 2, 30, 40]
        item.model.reviewed = True
        before = deepcopy(item.model)
        count = self.editor.undo_stack.count()
        self.editor.set_writing_mode('vertical-rl')
        expected = deepcopy(before)
        expected.writing_mode = 'vertical-rl'
        self.assertEqual(self.editor.selected()[0].model, expected)
        self.assertEqual(self.editor.undo_stack.count(), count + 1)
        self.editor.undo()
        self.assertEqual(self.editor.items_by_id[before.id].model, before)
        self.editor.redo()
        self.assertEqual(self.editor.items_by_id[before.id].model, expected)

    def test_ime_preview_is_vertical_transient_and_replacement_commits_once(self):
        item = self.vertical('한국')
        item.begin_edit()
        cursor = item.textCursor()
        cursor.movePosition(QTextCursor.End)
        item.setTextCursor(cursor)
        APP.sendEvent(self.editor.scene, QInputMethodEvent('어', []))
        self.assertEqual(item.model.text, '한국')
        layout = item.vertical_layout()
        self.assertEqual(''.join(g.text for g in layout.glyphs), '한국어')
        self.assertEqual(item.inputMethodQuery(Qt.ImCursorRectangle), layout.caret_rect(3))
        self.editor.autosave()
        saved, _ = load_project(self.editor.recovery_path())
        self.assertEqual(saved.pages[0].objects[0].text, '한국')
        event = QInputMethodEvent()
        event.setCommitString('어')
        APP.sendEvent(self.editor.scene, event)
        self.assertEqual(item.model.text, '한국어')
        replacement = QInputMethodEvent()
        replacement.setCommitString('말', -1, 1)
        APP.sendEvent(self.editor.scene, replacement)
        self.assertEqual(item.model.text, '한국말')
        self.assertFalse(item.preedit)
        item.finish_edit()
        self.editor.undo()
        self.assertEqual(self.editor.items_by_id[item.model.id].model.text, '한국')

    def test_preedit_cancel_and_selection_composition_preserve_char_styles(self):
        item = self.vertical('단서 번역')
        item.begin_edit()
        cursor = item.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(2, QTextCursor.KeepAnchor)
        item.setTextCursor(cursor)
        self.editor.format_flag('bold', True)
        commit = QInputMethodEvent('ㄱ', [])
        commit.setCommitString('힌트')
        APP.sendEvent(self.editor.scene, commit)
        self.assertEqual(item.model.text, '힌트 번역')
        self.assertTrue(item.model.paragraphs[0].runs[0].style.bold)
        APP.sendEvent(self.editor.scene, QInputMethodEvent('', []))
        self.assertEqual(item.model.text, '힌트 번역')
        self.assertFalse(item.preedit)
        self.assertEqual(''.join(g.text for g in item.vertical_layout().glyphs), '힌트 번역')

    def test_arrows_shift_selection_and_grapheme_delete_never_move_box(self):
        item = self.vertical('가👩\u200d🔬나e\u0301다')
        item.begin_edit()
        cursor = item.textCursor()
        cursor.setPosition(1)
        item.setTextCursor(cursor)
        position = QPointF(item.pos())
        QTest.keyClick(self.editor.canvas.viewport(), Qt.Key_Down, Qt.ShiftModifier)
        self.assertEqual(item.textCursor().selectedText(), '👩\u200d🔬')
        QTest.keyClick(self.editor.canvas.viewport(), Qt.Key_Delete)
        self.assertEqual(item.model.text, '가나e\u0301다')
        self.assertEqual(item.pos(), position)
        cursor = item.textCursor()
        cursor.movePosition(QTextCursor.End)
        item.setTextCursor(cursor)
        QTest.keyClick(self.editor.canvas.viewport(), Qt.Key_Up)
        QTest.keyClick(self.editor.canvas.viewport(), Qt.Key_Backspace)
        self.assertEqual(item.model.text, '가나다')
        self.editor.undo()
        self.assertEqual(item.model.text, '가나e\u0301다')

    def test_mouse_hit_selection_partial_format_uses_vertical_positions(self):
        item = self.vertical('하나둘셋넷다섯', height=310)
        item.begin_edit()
        layout = item.vertical_layout()
        a = self.editor.canvas.mapFromScene(item.mapToScene(layout.caret_rect(1).center()))
        b = self.editor.canvas.mapFromScene(item.mapToScene(layout.caret_rect(4).center()))
        QTest.mouseClick(self.editor.canvas.viewport(), Qt.LeftButton, Qt.NoModifier, a)
        self.assertEqual(item.textCursor().position(), 1)
        QTest.mouseClick(self.editor.canvas.viewport(), Qt.LeftButton, Qt.ShiftModifier, b)
        self.assertEqual(item.textCursor().selectedText(), '나둘셋')
        self.editor.format_flag('underline', True)
        self.assertEqual(item.model.paragraphs[0].runs[1].text, '나둘셋')
        self.assertTrue(item.model.paragraphs[0].runs[1].style.underline)
        self.assertFalse(item.model.paragraphs[0].runs[0].style.underline)

    def test_reflow_cache_font_and_frame_changes_and_draft_fit(self):
        item = self.vertical('한글' * 30, width=60, height=120)
        self.assertTrue(item.has_overflow())
        old = item.vertical_layout()
        item.model.width, item.model.height = 500, 600
        self.assertFalse(item.has_overflow())
        self.assertIsNot(old, item.vertical_layout())
        item.model.width, item.model.height = 180, 220
        self.editor.fit_fresh_targets([item.model.id])
        self.assertLess(item.model.paragraphs[0].runs[0].style.size, 20)
        self.assertFalse(item.has_overflow())

    def test_vertical_copy_group_and_save_reopen_share_export_renderer(self):
        item = self.vertical('「증거」\n시각 １２：３０')
        item.model.source_text, item.model.source_rect = '証拠', [60, 60, 100, 60]
        self.editor.copy_objects()
        self.editor.paste_objects()
        pasted = self.editor.selected()[0]
        self.assertEqual(pasted.model.writing_mode, 'vertical-rl')
        self.assertEqual(pasted.model.text, item.model.text)
        ids = [item.model.id, pasted.model.id]
        self.editor.scene.clearSelection()
        for key in ids:
            self.editor.items_by_id[key].setSelected(True)
        self.editor.group_selected()
        group = self.editor.selected()[0]
        group.model.rotation, group.model.scale = 7, .85
        self.editor.rebuild_scene([group.model.id])
        expected = self.pixels(self.editor.render_image())
        self.assertEqual(expected, self.pixels(render_page(self.editor.current_page, self.editor.original)))
        path = self.root / '세로쓰기.twproj'
        self.editor.save_to(path)
        self.editor.load_path(path)
        self.assertEqual(expected, self.pixels(self.editor.render_image()))
        self.assertEqual(self.source.read_bytes(), self.source_bytes)

    def test_legacy_defaults_and_reject_bad_mode_locked_text_unchanged(self):
        item = self.vertical()
        data = self.editor.project.to_dict()
        data['version'] = 5
        data['pages'][0]['objects'][0].pop('writing_mode')
        self.assertEqual(Project.from_dict(data).pages[0].objects[0].writing_mode, 'horizontal')
        data['pages'][0]['objects'][0]['writing_mode'] = 'diagonal'
        with self.assertRaises(ValueError):
            Project.from_dict(data)
        item.model.locked = True
        self.editor.set_writing_mode('horizontal')
        self.assertEqual(item.model.writing_mode, 'vertical-rl')

    def test_previous_clipboard_formats_remain_readable(self):
        item = self.vertical()
        data = self.editor.project.to_dict()['pages'][0]['objects']
        data[0].pop('writing_mode')
        for kind in ('application/x-translation-studio-objects-v3', 'application/x-translation-studio-objects-v4'):
            mime = QMimeData()
            mime.setData(kind, json.dumps({'objects': data}).encode('utf-8'))
            APP.clipboard().setMimeData(mime)
            self.editor.paste_objects()
            pasted = self.editor.selected()[0].model
            self.assertNotEqual(pasted.id, item.model.id)
            self.assertEqual(pasted.writing_mode, 'horizontal')
            self.assertEqual(pasted.text, item.model.text)

    def test_shift_enter_wraps_same_paragraph_and_roundtrips(self):
        item = self.vertical('앞뒤')
        item.begin_edit()
        cursor = item.textCursor()
        cursor.setPosition(1)
        item.setTextCursor(cursor)
        QTest.keyClick(self.editor.canvas.viewport(), Qt.Key_Return, Qt.ShiftModifier)
        self.assertEqual(item.model.text, '앞\u2028뒤')
        self.assertEqual(item.document().blockCount(), 1)
        layout = item.vertical_layout()
        self.assertEqual(len(layout.columns), 2)
        self.assertLess(layout.caret_rect(2).x(), layout.caret_rect(0).x())
        self.editor.undo()
        self.assertEqual(item.model.text, '앞뒤')
        self.editor.redo()
        self.assertEqual(item.model.text, '앞\u2028뒤')
        item.finish_edit()
        path = self.root / '줄바꿈.twproj'
        self.editor.save_to(path)
        expected = self.pixels(self.editor.render_image())
        self.editor.load_path(path)
        self.assertEqual(expected, self.pixels(self.editor.render_image()))


if __name__ == '__main__':
    unittest.main()
