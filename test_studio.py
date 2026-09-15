"""Behavioral Qt tests for the prototype's data-loss and text/layout risks."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / ".deps"), str(ROOT)]

from copy import deepcopy
import json
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QInputMethodEvent, QTextCharFormat, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from studio.model import Project
from studio.storage import load_project, save_project
from studio.window import Editor, png_bytes

QApplication.setAttribute(Qt.AA_Use96Dpi)
APP = QApplication.instance() or QApplication([])


class StudioTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "qa").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "qa")
        self.root = Path(self.temp.name)
        image = QImage(720, 960, QImage.Format_ARGB32)
        image.fill(QColor("#f3e6d0"))
        image.setPixelColor(0, 0, QColor(0, 0, 0, 0))
        self.source = self.root / "원본.png"
        self.source.write_bytes(png_bytes(image))
        self.source_bytes = self.source.read_bytes()
        self.editor = Editor(self.root / "data", auto_ocr=False)
        self.editor.show()
        self.editor.load_path(self.source)
        APP.processEvents()

    def tearDown(self):
        self.editor.dirty = False
        self.editor.close()
        self.editor.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def insert(self, text="한글 번역문\n두 번째 줄"):
        self.editor.add_text()
        item = self.editor.editing_item()
        event = QInputMethodEvent()
        event.setCommitString(text)
        APP.sendEvent(self.editor.scene, event)
        APP.processEvents()
        self.assertEqual(item.toPlainText(), text)
        return item

    def pixels(self, image):
        converted = image.convertToFormat(QImage.Format_RGBA8888)
        return bytes(converted.constBits())

    def test_ime_preedit_commit_and_arrow_keys(self):
        item = self.insert("한국어")
        cursor = item.textCursor()
        cursor.movePosition(QTextCursor.End)
        item.setTextCursor(cursor)
        APP.sendEvent(self.editor.scene, QInputMethodEvent("ㄱ", []))
        self.assertEqual(item.model.text, "한국어")
        self.editor.autosave()
        saved, _ = load_project(self.editor.recovery_path())
        self.assertEqual(saved.pages[0].objects[0].text, "한국어")
        event = QInputMethodEvent()
        event.setCommitString("가")
        APP.sendEvent(self.editor.scene, event)
        self.assertEqual(item.model.text, "한국어가")
        x = item.pos().x()
        old_cursor = item.textCursor().position()
        QTest.keyClick(self.editor.canvas.viewport(), Qt.Key_Left)
        self.assertEqual(item.pos().x(), x)
        self.assertEqual(item.textCursor().position(), old_cursor - 1)
        item.finish_edit()
        QTest.keyClick(self.editor.canvas.viewport(), Qt.Key_Right)
        self.assertEqual(item.model.x, x + 1)

    def test_partial_format_roundtrip_and_exact_export(self):
        item = self.insert()
        cursor = item.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(2, QTextCursor.KeepAnchor)
        item.setTextCursor(cursor)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#b02c41"))
        fmt.setFontPointSize(32)
        self.editor.apply_format(fmt)
        item.finish_edit()
        obj = self.editor.project.pages[0].objects[0]
        self.assertEqual(obj.paragraphs[0].runs[0].style.color, "#b02c41")
        self.assertEqual(obj.paragraphs[0].runs[0].text, "한글")
        self.assertNotEqual(obj.paragraphs[0].runs[-1].style.color, "#b02c41")
        self.editor.begin_operation()
        item.setRotation(12)
        self.editor.finish_operation("회전")
        before = self.editor.render_image()
        path = self.root / "저장.twproj"
        self.editor.save_to(path)
        expected = deepcopy(self.editor.project)
        self.editor.load_path(path)
        self.assertEqual(self.editor.project, expected)
        self.assertEqual(self.pixels(before), self.pixels(self.editor.render_image()))
        self.assertEqual(self.source.read_bytes(), self.source_bytes)
        self.assertEqual(before.pixelColor(0, 0).alpha(), 0)

    def test_text_and_object_undo_redo(self):
        item = self.insert("첫 문장")
        item.finish_edit()
        self.editor.undo()
        self.assertEqual(self.editor.project.pages[0].objects[0].text, "번역문을 입력하세요")
        self.editor.redo()
        self.assertEqual(self.editor.project.pages[0].objects[0].text, "첫 문장")
        self.editor.nudge(17, 12)
        moved = deepcopy(self.editor.project)
        self.editor.undo()
        self.assertNotEqual(self.editor.project, moved)
        self.editor.redo()
        self.assertEqual(self.editor.project, moved)

    def test_mouse_drag_resize_and_rotation(self):
        item = self.insert("상자 조작")
        item.finish_edit()
        APP.processEvents()
        view = self.editor.canvas
        def drag(local_from, local_to):
            start = view.mapFromScene(item.mapToScene(local_from))
            end = view.mapFromScene(item.mapToScene(local_to))
            QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, start)
            QTest.mouseMove(view.viewport(), end, 30)
            QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, end)
            APP.processEvents()
        before = deepcopy(item.model)
        count = self.editor.undo_stack.count()
        drag(QPointF(30, 30), QPointF(65, 50))
        self.assertGreater(item.model.x, before.x + 20)
        self.assertEqual(self.editor.undo_stack.count(), count + 1)
        old_width = item.model.width
        drag(QPointF(item.model.width, item.model.height), QPointF(item.model.width + 60, item.model.height + 30))
        self.assertGreater(item.model.width, old_width + 40)
        drag(QPointF(item.model.width / 2, -23), QPointF(item.model.width + 40, item.model.height / 2))
        self.assertGreater(abs(item.model.rotation), 40)

    def test_source_geometry_does_not_follow_output_box(self):
        item = self.insert()
        item.finish_edit()
        item.model.source_rect = [10, 20, 100, 50]
        item.model.erase_rect = [8, 18, 104, 54]
        item.model.source_text = "原文"
        self.editor.nudge(100, 200)
        self.assertEqual(item.model.source_rect, [10, 20, 100, 50])
        self.assertEqual(item.model.erase_rect, [8, 18, 104, 54])
        self.assertEqual(item.model.source_text, "原文")

    def test_duplicate_delete_and_restore(self):
        self.insert().finish_edit()
        self.editor.duplicate()
        objects = self.editor.project.pages[0].objects
        self.assertEqual(len(objects), 2)
        self.assertNotEqual(objects[0].id, objects[1].id)
        self.editor.delete_selected()
        self.assertEqual(len(self.editor.project.pages[0].objects), 1)
        self.editor.undo()
        self.assertEqual(len(self.editor.project.pages[0].objects), 2)

    def test_failed_atomic_save_preserves_previous_file(self):
        self.insert().finish_edit()
        path = self.root / "작업.twproj"
        self.editor.save_to(path)
        previous = path.read_bytes()
        with patch("studio.storage.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                save_project(path, self.editor.project, self.editor.original)
        self.assertEqual(path.read_bytes(), previous)
        self.assertFalse(list(self.root.glob(".studio-*.tmp")))

    def test_bad_project_does_not_replace_open_document(self):
        self.insert().finish_edit()
        before = deepcopy(self.editor.project)
        malformed = self.root / "손상.twproj"
        malformed.write_bytes(b"not a zip")
        with self.assertRaises(ValueError):
            self.editor.load_path(malformed)
        self.assertEqual(self.editor.project, before)
        data = before.to_dict()
        data["pages"][0]["asset"] = "../private.png"
        with self.assertRaises(ValueError):
            Project.from_dict(data)

    def test_autosave_backup_and_recovery(self):
        self.insert("복구할 번역").finish_edit()
        self.assertTrue(self.editor.autosave())
        path = self.editor.recovery_path()
        expected = deepcopy(self.editor.project)
        self.editor.load_path(path)
        self.assertEqual(self.editor.project, expected)
        self.editor.save_to(self.root / "보관.twproj")
        self.editor.begin_operation()
        self.editor.project.name = "수정된 이름"
        self.editor.finish_operation("이름")
        self.assertTrue(self.editor.autosave())
        backup, _ = load_project(self.root / "보관.twproj.bak")
        self.assertEqual(backup.name, expected.name)

    def test_compare_and_selection_do_not_leak_into_export(self):
        self.insert("편집 결과").finish_edit()
        normal = self.pixels(self.editor.render_image())
        self.editor.compare(True)
        self.assertEqual(self.pixels(self.editor.render_image()), normal)
        self.editor.compare(False)
        self.editor.scene.clearSelection()
        self.assertEqual(self.pixels(self.editor.render_image()), normal)
        with self.assertRaises(ValueError):
            self.editor.export_to(self.source)
        self.assertEqual(self.source.read_bytes(), self.source_bytes)

    def test_ime_whole_text_replacement_keeps_visible_default_style(self):
        item = self.insert("전체 교체 후에도 색 유지")
        item.finish_edit()
        self.assertEqual(item.model.paragraphs[0].runs[0].style.color, item.defaultTextColor().name())
        before = self.pixels(self.editor.render_image())
        path = self.root / "색상.twproj"
        self.editor.save_to(path)
        self.editor.load_path(path)
        self.assertEqual(before, self.pixels(self.editor.render_image()))

    def test_double_click_edit_and_shift_multi_select(self):
        first = self.insert("첫 상자")
        first.finish_edit()
        first_id = first.model.id
        self.editor.add_text()
        first = self.editor.items_by_id[first_id]
        second = self.editor.editing_item()
        second.finish_edit()
        second.setPos(40, 40)
        self.editor.sync_positions()
        view = self.editor.canvas
        self.editor.scene.clearSelection()
        APP.processEvents()
        p1 = view.mapFromScene(first.mapToScene(QPointF(20, 20)))
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, p1)
        APP.processEvents()
        p2 = view.mapFromScene(second.mapToScene(QPointF(20, 20)))
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.ShiftModifier, p2)
        self.assertEqual(len(self.editor.selected()), 2)
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, p2)
        QTest.mouseDClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, p2)
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, p2)
        self.assertTrue(second.editing)


if __name__ == "__main__":
    unittest.main(verbosity=2)
