"""Behavioral tests for native object editing and compatibility with translation."""
from test_studio import APP, ROOT, StudioTests
from copy import deepcopy
import json
import zipfile

from PySide6.QtCore import QPointF, QRectF, Qt, QMimeData
from PySide6.QtGui import QColor, QImage, QInputMethodEvent, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import unittest

from studio.crop_dialog import CropDialog
from studio.editing import MIME
from studio.model import ImageBox, TextBox
from studio.recognition import Region


class EditingTests(unittest.TestCase):
    setUp = StudioTests.setUp
    tearDown = StudioTests.tearDown
    insert = StudioTests.insert
    pixels = StudioTests.pixels

    def select(self, *ids):
        self.editor.scene.clearSelection()
        for key in ids:
            self.editor.items_by_id[key].setSelected(True)
        APP.processEvents()

    def graphic(self):
        image = QImage(100, 60, QImage.Format_ARGB32)
        image.fill(QColor("#e63c48"))
        for y in range(60):
            for x in range(50, 100):
                image.setPixelColor(x, y, QColor("#326ed0"))
        image.setPixelColor(0, 0, QColor(0, 0, 0, 0))
        return self.editor.insert_qimage(image)

    def test_all_shapes_and_image_save_reopen_export_identically(self):
        for kind in ("rect", "roundrect", "ellipse", "line", "arrow"):
            obj = self.editor.add_shape(kind)
            self.editor.set_property("opacity", .65, "반투명")
            self.editor.nudge((obj.z-2)*60, obj.z*35-100)
        image = self.graphic()
        self.editor.flip_image("flip_h")
        self.editor.apply_crop(image.id, [.15, .1, .7, .8])
        self.editor.items_by_id[image.id].setRotation(27)
        self.editor.sync_positions()
        self.insert("한국어 + 도형 + 투명 이미지").finish_edit()
        expected = self.pixels(self.editor.render_image())
        path = self.root / "혼합.twproj"
        self.editor.save_to(path)
        before = deepcopy(self.editor.project)
        self.editor.load_path(path)
        self.assertEqual(self.editor.project, before)
        self.assertEqual(self.pixels(self.editor.render_image()), expected)
        self.assertEqual(self.source.read_bytes(), self.source_bytes)

    def test_visual_mouse_resize_rotate_move_and_undo(self):
        obj = self.editor.add_shape("ellipse")
        item = self.editor.items_by_id[obj.id]
        view = self.editor.canvas
        def drag(start, finish):
            a, b = view.mapFromScene(item.mapToScene(start)), view.mapFromScene(item.mapToScene(finish))
            QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, a)
            QTest.mouseMove(view.viewport(), b, 30)
            QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, b)
            APP.processEvents()
        original = deepcopy(obj)
        drag(QPointF(30, 30), QPointF(75, 65))
        self.assertGreater(obj.x, original.x+30)
        old = obj.width
        drag(QPointF(obj.width, obj.height), QPointF(obj.width+70, obj.height+40))
        self.assertGreater(obj.width, old+40)
        drag(QPointF(obj.width/2, -23), QPointF(obj.width+40, obj.height/2))
        self.assertGreater(abs(obj.rotation), 45)
        self.editor.undo()
        self.assertAlmostEqual(self.editor.items_by_id[obj.id].model.rotation, 0)

    def test_image_resize_locks_aspect(self):
        obj = self.graphic()
        item = self.editor.items_by_id[obj.id]
        view = self.editor.canvas
        original_ratio = obj.width/obj.height
        a = view.mapFromScene(item.mapToScene(QPointF(obj.width, obj.height)))
        b = view.mapFromScene(item.mapToScene(QPointF(obj.width+100, obj.height+10)))
        QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, a)
        QTest.mouseMove(view.viewport(), b, 30)
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, b)
        self.assertGreater(obj.width, 170)
        self.assertAlmostEqual(obj.width/obj.height, original_ratio, places=4)

    def test_crop_flip_and_reset_preserve_source_pixels(self):
        obj = self.graphic()
        encoded = obj.image_data
        original = self.pixels(self.editor.render_image())
        self.editor.apply_crop(obj.id, [.5, 0, .5, 1])
        rendered = self.editor.render_image()
        self.assertEqual(rendered.pixelColor(round(obj.x+obj.width/2), round(obj.y+obj.height/2)).name(), "#326ed0")
        self.assertEqual(obj.image_data, encoded)
        self.editor.undo()
        self.assertEqual(self.pixels(self.editor.render_image()), original)
        self.select(obj.id)
        self.editor.flip_image("flip_h")
        obj = self.editor.items_by_id[obj.id].model
        self.assertEqual(self.editor.render_image().pixelColor(round(obj.x+10), round(obj.y+30)).name(), "#326ed0")
        self.assertEqual(obj.image_data, encoded)

    def test_crop_dialog_drag_and_cancel_do_not_mutate_document(self):
        obj = self.graphic()
        item = self.editor.items_by_id[obj.id]
        before = deepcopy(self.editor.project)
        dialog = CropDialog(item.image, None, self.editor)
        dialog.show()
        APP.processEvents()
        area = dialog.canvas.image_rect()
        start = QPointF(area.left()+area.width()*.2, area.top()+area.height()*.1).toPoint()
        end = QPointF(area.left()+area.width()*.8, area.top()+area.height()*.9).toPoint()
        QTest.mousePress(dialog.canvas, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(dialog.canvas, end, 20)
        QTest.mouseRelease(dialog.canvas, Qt.LeftButton, Qt.NoModifier, end)
        self.assertAlmostEqual(dialog.canvas.crop[0], .2, delta=.01)
        self.assertAlmostEqual(dialog.canvas.crop[2], .6, delta=.01)
        dialog.reject()
        self.assertEqual(before, self.editor.project)

    def test_alignment_uses_rotated_content_bounds_and_single_object_page(self):
        a = self.editor.add_shape("rect")
        b = self.editor.add_shape("ellipse")
        self.editor.items_by_id[a.id].setPos(20, 70)
        self.editor.items_by_id[a.id].setRotation(32)
        self.editor.items_by_id[b.id].setPos(330, 230)
        self.editor.sync_positions()
        before = deepcopy(self.editor.project)
        self.select(a.id, b.id)
        self.editor.arrange("left")
        def bounds(key):
            item = self.editor.items_by_id[key]
            return item.mapRectToScene(QRectF(0, 0, item.model.width, item.model.height))
        self.assertAlmostEqual(bounds(a.id).left(), bounds(b.id).left())
        self.editor.undo()
        self.assertEqual(self.editor.project, before)
        self.select(a.id)
        self.editor.arrange("hcenter")
        self.assertAlmostEqual(bounds(a.id).center().x(), self.editor.project.pages[0].width/2)

    def test_equal_gaps_keep_endpoints(self):
        ids = []
        for x, w in [(10, 50), (110, 140), (500, 80)]:
            obj = self.editor.add_shape("rect")
            obj.x, obj.width = x, w
            ids.append(obj.id)
        self.editor.rebuild_scene(ids)
        self.editor.arrange("horizontal")
        values = sorted((i.model for i in self.editor.selected()), key=lambda o: o.x)
        self.assertEqual(values[0].x, 10)
        self.assertEqual(values[-1].x, 500)
        self.assertAlmostEqual(values[1].x-values[0].x-values[0].width, values[2].x-values[1].x-values[1].width)

    def test_layer_order_changes_render_and_undo_restores(self):
        a = self.editor.add_shape("rect")
        self.editor.set_property("fill", "#ee3344", "색")
        b = self.editor.add_shape("rect")
        self.editor.set_property("fill", "#2255dd", "색")
        pixel = lambda: self.editor.render_image().pixelColor(round(a.x+40), round(a.y+40)).name()
        self.assertEqual(pixel(), "#2255dd")
        self.select(a.id)
        self.editor.reorder("front")
        self.assertEqual(pixel(), "#ee3344")
        self.editor.undo()
        self.assertEqual(pixel(), "#2255dd")
        self.select(a.id)
        self.editor.reorder("raise")
        self.assertEqual(pixel(), "#ee3344")

    def test_locked_text_blocks_typing_delete_move_and_format(self):
        item = self.insert("고정된 번역")
        item.finish_edit()
        key = item.model.id
        self.editor.toggle_lock()
        before = deepcopy(self.editor.project)
        item = self.editor.items_by_id[key]
        item.begin_edit()
        self.assertFalse(item.editing)
        self.editor.nudge(30, 30)
        self.editor.delete_selected()
        self.editor.format_flag("bold", True)
        self.editor.duplicate()
        self.assertEqual(self.editor.project, before)
        self.assertFalse(self.editor.delete_action.isEnabled())
        self.editor.toggle_lock()
        self.editor.nudge(30, 30)
        self.assertNotEqual(self.editor.project.pages[0].objects[0].x, before.pages[0].objects[0].x)

    def test_structured_clipboard_preserves_mixed_styles_and_assets(self):
        text = self.insert("옮겨 쓸 텍스트")
        text.finish_edit()
        text_id = text.model.id
        self.editor.format_flag("strike", True)
        image = self.graphic()
        self.select(text_id, image.id)
        self.editor.copy_objects()
        originals = [deepcopy(i.model) for i in sorted(self.editor.selected(), key=lambda i: i.model.z)]
        self.editor.paste_objects()
        copies = sorted(self.editor.selected(), key=lambda i: i.model.z)
        self.assertEqual(len(copies), 2)
        for before, after in zip(originals, copies):
            self.assertNotEqual(before.id, after.model.id)
            self.assertEqual(after.model.x, before.x+20)
        self.assertEqual(copies[0].model.paragraphs, originals[0].paragraphs)
        self.assertEqual(copies[1].model.image_data, originals[1].image_data)
        self.editor.undo()
        self.assertEqual(len(self.editor.project.pages[0].objects), 2)

    def test_paste_on_another_card_does_not_copy_source_erasure(self):
        self.editor.accept_regions([Region("元の原文", [10, 10, 100, 35], 80, 20)])
        obj = self.editor.project.pages[0].objects[0]
        self.editor.set_target(obj, "보존할 번역")
        self.editor.rebuild_scene([obj.id])
        self.editor.copy_objects()
        image = QImage(400, 400, QImage.Format_ARGB32)
        image.fill(QColor("white"))
        path = self.root / "다른카드.png"
        image.save(str(path))
        self.editor.load_path(path)
        self.editor.paste_objects()
        pasted = self.editor.project.pages[0].objects[0]
        self.assertEqual(pasted.text, "보존할 번역")
        self.assertEqual(pasted.source_text, "")
        self.assertIsNone(pasted.source_rect)

    def test_text_clipboard_shortcuts_keep_editing_and_undo(self):
        item = self.insert("복사할 문장")
        self.editor.select_all()
        self.editor.copy_objects(cut=True)
        self.assertEqual(item.toPlainText(), "")
        self.editor.paste_objects()
        self.assertEqual(item.toPlainText(), "복사할 문장")
        self.assertTrue(item.editing)
        self.editor.undo()
        self.assertEqual(item.toPlainText(), "")

    def test_style_copy_preserves_target_text_and_source(self):
        first = self.insert("제목 서식")
        first.finish_edit()
        self.editor.format_flag("strike", True)
        self.editor.format_flag("bold", True)
        self.editor.copy_style()
        second = self.insert("다른 문장")
        second.finish_edit()
        second.model.source_text = "原文"
        self.editor.paste_style()
        self.assertEqual(second.model.text, "다른 문장")
        self.assertEqual(second.model.source_text, "原文")
        self.assertTrue(second.model.paragraphs[0].runs[0].style.strike)
        self.assertTrue(second.model.paragraphs[0].runs[0].style.bold)

    def test_corrupt_image_project_and_clipboard_preserve_current_edits(self):
        obj = self.graphic()
        before = deepcopy(self.editor.project)
        data = before.to_dict()
        data["pages"][0]["objects"][0]["image_data"] = "aW52YWxpZA=="
        path = self.root / "불량이미지.twproj"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("manifest.json", json.dumps(data))
            archive.writestr("assets/original.png", self.source_bytes)
        with self.assertRaises(ValueError):
            self.editor.load_path(path)
        self.assertEqual(self.editor.project, before)
        mime = QMimeData()
        mime.setData(MIME, json.dumps({"objects": data["pages"][0]["objects"]}).encode())
        QApplication.clipboard().setMimeData(mime)
        self.editor.paste_objects()
        self.assertEqual(self.editor.project, before)

        # A malformed new text flag must also fail before replacing current work.
        from dataclasses import asdict
        malformed = asdict(TextBox())
        malformed["paragraphs"][0]["runs"][0]["style"]["strike"] = "invalid"
        data["pages"][0]["objects"] = [malformed]
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("manifest.json", json.dumps(data))
            archive.writestr("assets/original.png", self.source_bytes)
        with self.assertRaises(ValueError):
            self.editor.load_path(path)
        self.assertEqual(self.editor.project, before)

    def test_visual_objects_do_not_block_ocr_and_locked_text_skips_translation(self):
        self.editor.add_shape("rect")
        self.editor.accept_regions([Region("翻訳原文", [100, 200, 260, 50], 90, 25)])
        objects = self.editor.project.pages[0].objects
        self.assertEqual(len(objects), 2)
        obj = objects[1]
        self.select(obj.id)
        self.editor.toggle_lock()
        self.editor.translate_missing()
        self.assertIsNone(self.editor.job)
        self.assertFalse(obj.text)

    def test_opening_previous_project_does_not_rewrite_it(self):
        self.insert("이전 작업").finish_edit()
        self.editor.autosave()
        data = self.editor.project.to_dict()
        data["version"] = 2
        data["pages"][0]["asset"] = "assets/original.png"
        path = self.root / "이전버전.twproj"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("manifest.json", json.dumps(data))
            archive.writestr("assets/original.png", self.source_bytes)
        before = path.read_bytes()
        self.editor.auto_ocr = True
        self.editor.load_path(path)
        APP.processEvents()
        self.assertIsNone(self.editor.job)
        self.assertFalse(self.editor.pending_ocr)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.editor.dirty)

    def test_real_copy_paste_shortcuts_duplicate_objects(self):
        self.editor.add_shape("rect")
        self.editor.canvas.setFocus()
        QTest.keyClick(self.editor.canvas.viewport(), Qt.Key_C, Qt.ControlModifier)
        QTest.keyClick(self.editor.canvas.viewport(), Qt.Key_V, Qt.ControlModifier)
        APP.processEvents()
        self.assertEqual(len(self.editor.project.pages[0].objects), 2)
        QTest.keyClick(self.editor.canvas.viewport(), Qt.Key_X, Qt.ControlModifier)
        self.assertEqual(len(self.editor.project.pages[0].objects), 1)
        self.editor.undo()
        self.assertEqual(len(self.editor.project.pages[0].objects), 2)

    def test_replaced_image_is_embedded_and_survives_file_removal(self):
        original = self.graphic()
        old_data = original.image_data
        image = QImage(40, 80, QImage.Format_ARGB32)
        image.fill(QColor("#eeaa33"))
        path = self.root / "삽입할이미지.png"
        image.save(str(path))
        self.editor.insert_image(path, replace=True)
        self.assertEqual(len(self.editor.project.pages[0].objects), 1)
        self.assertNotEqual(original.image_data, old_data)
        self.assertAlmostEqual(original.width/original.height, .5)
        saved = self.root / "독립작업.twproj"
        self.editor.save_to(saved)
        expected = self.pixels(self.editor.render_image())
        path.unlink()
        self.editor.load_path(saved)
        self.assertEqual(self.pixels(self.editor.render_image()), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
