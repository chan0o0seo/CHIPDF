"""Recent-work persistence and real UI selection/stepping checks."""
import json
import unittest
from unittest.mock import patch

import test_studio as base
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStyle, QStyleOptionSpinBox

from studio.recent_files import RECENT_LIMIT, read_recent
from studio.window import Editor


class RecentFilesTests(unittest.TestCase):
    setUp = base.StudioTests.setUp
    tearDown = base.StudioTests.tearDown
    insert = base.StudioTests.insert

    def test_recovery_save_as_order_and_restart(self):
        recovery = str(self.editor.recovery_path().resolve())
        self.assertEqual(self.editor.recent_files[0]['path'], recovery)
        self.assertIn('자동 저장', self.editor.recent_list.item(0).text())
        first, second = self.root / '첫 작업.twproj', self.root / '둘째 작업.twproj'
        self.editor.save_to(first)
        self.editor.save_to(second)
        self.editor.load_path(first)
        self.assertEqual([item['path'] for item in self.editor.recent_files], [str(first), str(second)])
        other = Editor(self.editor.data_dir)
        try:
            self.assertEqual(other.recent_files, self.editor.recent_files)
            with patch.object(other, 'open_path') as opened:
                other.recent_list.setCurrentRow(1)
                other.recent_open_button.click()
                opened.assert_called_once_with(str(second))
                opened.reset_mock()
                other.recent_menu.actions()[0].trigger()
                opened.assert_called_once_with(str(first))
        finally:
            other.close()
            other.deleteLater()

    def test_history_failure_does_not_fail_document_save(self):
        self.insert('복구할 편집 내용')
        with patch('studio.recent_files.atomic_write', side_effect=OSError('history unavailable')):
            self.assertTrue(self.editor.autosave())
        project, _ = base.load_project(self.editor.recovery_path())
        self.assertEqual(project.pages[0].objects[0].text, '복구할 편집 내용')
        self.assertFalse(self.editor.dirty)

    def test_missing_file_disabled_and_disappearing_file_guarded(self):
        path = self.root / '삭제될 작업.twproj'
        self.editor.save_to(path)
        path.unlink()
        with patch.object(self.editor, 'open_path') as opened:
            self.editor.open_recent_path(str(path))
            opened.assert_not_called()
        self.assertFalse(self.editor.recent_menu.actions()[0].isEnabled())
        self.assertIn('파일 없음', self.editor.recent_list.item(0).text())

    def test_legacy_malformed_history_and_limit(self):
        path = self.root / 'recent.json'
        path.write_text(json.dumps({'path': str(self.source)}), 'utf-8')
        self.assertEqual(read_recent(path), [{'path': str(self.source), 'name': self.source.name}])
        for invalid in ('null', '42', '"text"', '{broken', '[null, {}, {"path": 1}]'):
            path.write_text(invalid, 'utf-8')
            self.assertEqual(read_recent(path), [])
        for index in range(RECENT_LIMIT + 3):
            self.editor.remember_recent(self.root / f'{index}.twproj')
        self.assertEqual(len(self.editor.recent_files), RECENT_LIMIT)
        self.assertEqual(read_recent(self.editor.data_dir / 'recent.json'), self.editor.recent_files)

    def test_font_arrows_click_and_undo(self):
        item = self.insert('크기 조절')
        self.editor.finish_edit()
        for field in (self.editor.size_box, self.editor.inspector_size):
            base.APP.processEvents()
            option = QStyleOptionSpinBox()
            field.initStyleOption(option)
            before = field.value()
            for subcontrol, expected in ((QStyle.SC_SpinBoxUp, before + field.singleStep()),
                                         (QStyle.SC_SpinBoxDown, before)):
                rect = field.style().subControlRect(QStyle.CC_SpinBox, option, subcontrol, field)
                self.assertFalse(rect.isEmpty())
                QTest.mouseClick(field, Qt.LeftButton, Qt.NoModifier, rect.center())
                self.assertEqual(field.value(), expected)
                self.assertEqual(item.model.paragraphs[0].runs[0].style.size, expected)
        self.editor.undo()
        self.assertEqual(self.editor.inspector_size.value(), before + self.editor.inspector_size.singleStep())


if __name__ == '__main__':
    unittest.main()
