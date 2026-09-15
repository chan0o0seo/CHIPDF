"""Behavioral coverage of manual rectangle OCR and explicit brush repairs."""
from test_studio import APP, StudioTests
from test_workflow import WorkflowTests
from copy import deepcopy
import threading
import unittest
from unittest.mock import patch

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QInputMethodEvent, QPainter
from PySide6.QtTest import QTest

from studio.document_io import import_files, render_page
from studio.recognition import Region, encode_png
from studio.storage import load_bundle
from studio.window import Editor, png_bytes


class ManualEditorTests(unittest.TestCase):
    setUp = StudioTests.setUp
    tearDown = StudioTests.tearDown
    pixels = StudioTests.pixels
    pump = WorkflowTests.pump

    def draw(self, start, end=None):
        view = self.editor.canvas
        end = end or start
        a = view.mapFromScene(QPointF(*start))
        b = view.mapFromScene(QPointF(*end))
        self.assertTrue(view.viewport().rect().contains(a))
        self.assertTrue(view.viewport().rect().contains(b))
        QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, a)
        QTest.mouseMove(view.viewport(), b, 20)
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, b)
        APP.processEvents()

    def region(self, text='日本語の文章', rect=(100, 100, 160, 48)):
        x, y, width, height = rect
        return Region(text, list(rect), 91, 24,
                      patch=encode_png(Image.new('RGBA', (width, height), '#f3e6d0')),
                      mask=encode_png(Image.new('L', (width, height), 255)),
                      erase_rect=list(rect))

    def ink_source(self):
        image = QImage.fromData(self.source_bytes)
        painter = QPainter(image)
        painter.fillRect(110, 112, 22, 20, QColor('black'))
        painter.fillRect(400, 300, 12, 12, QColor('black'))
        painter.end()
        self.source_bytes = png_bytes(image)
        self.source.write_bytes(self.source_bytes)
        self.editor.load_path(self.source)
        APP.processEvents()

    def test_default_import_waits_for_rectangle_and_keeps_auto_ocr_in_menu(self):
        default_editor = Editor(self.root / 'default-data')
        try:
            with patch('studio.workflow.recognize') as auto, patch('studio.region_tools.recognize_region') as region:
                default_editor.load_path(self.source)
                APP.processEvents()
                self.assertFalse(default_editor.auto_ocr)
                self.assertEqual(default_editor.canvas.tool, 'ocr')
                self.assertEqual(default_editor.current_page.objects, [])
                self.assertFalse(default_editor.current_page.ocr_done)
                self.assertIsNone(default_editor.job)
                self.assertFalse(default_editor.pending_ocr)
                auto.assert_not_called()
                region.assert_not_called()
            self.assertIn(default_editor.reread_action, default_editor.file_menu.actions())
            self.assertIn(default_editor.vertical_ocr_action, default_editor.file_menu.actions())
        finally:
            default_editor.dirty = False
            default_editor.close()
            default_editor.deleteLater()
            APP.processEvents()

    def test_rectangle_drag_is_normalized_zoom_correct_and_clipped_to_page(self):
        view = self.editor.canvas
        view.region_selected.disconnect(self.editor.start_region_ocr)
        selected = []
        view.region_selected.connect(selected.append)
        for zoom in (.35, .55):
            self.editor.set_canvas_tool('ocr')
            APP.processEvents()
            view.resetTransform()
            view.scale(zoom, zoom)
            view.centerOn(360, 480)
            self.draw((250, 240), (60, 80))
            self.assertEqual(view.tool, 'select')
            actual = selected[-1]
            for received, expected in zip((actual.x(), actual.y(), actual.width(), actual.height()), (60, 80, 190, 160)):
                self.assertAlmostEqual(received, expected, delta=2 / zoom)
        self.editor.set_canvas_tool('ocr')
        APP.processEvents()
        view.resetTransform()
        view.scale(.35, .35)
        view.centerOn(360, 480)
        self.draw((750, 1000), (-30, 880))
        actual = selected[-1]
        self.assertEqual(actual.x(), 0)
        self.assertEqual(actual.width(), 720)
        self.assertEqual(actual.bottom(), 960)
        self.assertAlmostEqual(actual.top(), 880, delta=3)
        count = len(selected)
        self.editor.set_canvas_tool('ocr')
        APP.processEvents()
        self.draw((100, 100), (110, 110))
        self.assertEqual(len(selected), count)
        self.assertEqual(self.editor.current_page.objects, [])

    def test_rectangle_creates_blank_editable_target_and_immediately_erases_original(self):
        self.ink_source()
        original = self.editor.original
        self.editor.accept_manual_region(self.region())
        obj = self.editor.current_page.objects[0]
        self.assertEqual((obj.x, obj.y, obj.width, obj.height), (100, 100, 160, 48))
        self.assertEqual(obj.text, '')
        self.assertTrue(obj.erase_when_empty)
        self.assertEqual(self.editor.source_text.toPlainText(), obj.source_text)
        self.assertTrue(self.editor.source_dock.isVisible())
        self.assertTrue(self.editor.editing_item().editing)
        self.assertEqual(self.editor.canvas.tool, 'select')
        self.assertEqual(self.editor.background_item.pixmap().toImage().pixelColor(115, 115), QColor('#f3e6d0'))
        self.assertEqual(self.editor.image.pixelColor(115, 115), QColor('black'))
        event = QInputMethodEvent()
        event.setCommitString('직접 입력한 한국어')
        APP.sendEvent(self.editor.scene, event)
        self.editor.finish_edit()
        self.assertEqual(obj.text, '직접 입력한 한국어')
        self.editor.compare(True)
        self.assertEqual(self.editor.background_item.pixmap().toImage().pixelColor(115, 115), QColor('black'))
        self.editor.compare(False)
        self.assertEqual(self.editor.original, original)
        self.assertEqual(self.source.read_bytes(), self.source_bytes)

    def test_empty_ocr_source_can_be_corrected_without_losing_blank_target(self):
        self.editor.accept_manual_region(self.region(''))
        obj = self.editor.current_page.objects[0]
        self.assertIs(self.editor.current_source(), obj)
        self.assertTrue(self.editor.edit_source_button.isEnabled())
        with patch('studio.workflow.QInputDialog.getMultiLineText', return_value=('修正した原文', True)):
            self.editor.edit_source()
        self.assertEqual(obj.source_text, '修正した原文')
        self.assertTrue(obj.source_confirmed)
        self.assertEqual(obj.text, '')
        self.assertEqual(self.editor.source_text.toPlainText(), '修正した原文')

    def test_translate_button_only_translates_selection_and_preserves_existing_target(self):
        self.editor.accept_manual_region(self.region('第一文'))
        self.editor.finish_edit()
        self.editor.accept_manual_region(self.region('第二文', (100, 200, 160, 48)))
        first, second = self.editor.current_page.objects

        class Translator:
            calls = []

            def translate(self, source, cancelled):
                self.calls.append(source)
                return '번역 ' + str(len(self.calls))

        translator = Translator()
        self.editor.translator = translator
        self.editor.translate_action.trigger()
        self.pump(lambda: self.editor.job is None)
        self.assertEqual(translator.calls, ['第二文'])
        self.assertEqual(first.text, '')
        self.assertEqual(second.text, '번역 1')
        self.editor.translate_action.trigger()
        self.pump(lambda: self.editor.job is None)
        self.assertEqual(translator.calls, ['第二文', '第二文'])
        self.assertEqual(second.text, '번역 1')
        self.assertEqual(second.candidate_text, '번역 2')
        self.assertTrue(self.editor.apply_candidate_button.isVisible())
        self.editor.apply_candidate_button.click()
        self.assertEqual(second.text, '번역 2')
        self.editor.undo()
        self.assertEqual(self.editor.items_by_id[second.id].model.text, '번역 1')

    def test_brush_selection_uses_page_pixels_and_never_changes_export_before_apply(self):
        self.ink_source()
        before = deepcopy(self.editor.project)
        output = self.pixels(self.editor.render_image())
        self.editor.set_canvas_tool('brush')
        self.editor.brush_size_box.setValue(40)
        APP.processEvents()
        view = self.editor.canvas
        view.resetTransform()
        view.scale(.5, .5)
        view.centerOn(360, 480)
        self.draw((406, 306))
        mask = view.brush_mask_image()
        self.assertEqual((mask.width(), mask.height()), (720, 960))
        self.assertEqual(mask.pixelColor(406, 306).red(), 255)
        self.assertEqual(mask.pixelColor(435, 306).red(), 0)
        self.assertEqual(self.editor.project, before)
        self.assertEqual(self.pixels(self.editor.render_image()), output)
        self.assertEqual(self.pixels(render_page(self.editor.current_page, self.editor.original)), output)
        self.assertTrue(self.editor.apply_erase_action.isEnabled())
        count = self.editor.undo_stack.count()
        QTest.keyClick(view.viewport(), Qt.Key_Escape)
        APP.processEvents()
        self.assertTrue(view.brush_mask_image().isNull())
        self.assertEqual(view.tool, 'select')
        self.assertEqual(self.editor.project, before)
        self.assertEqual(self.editor.undo_stack.count(), count)

    def test_applied_brush_is_immediate_undoable_and_persists_with_untouched_original(self):
        self.ink_source()
        original = self.editor.original
        self.editor.set_canvas_tool('brush')
        self.editor.brush_size_box.setValue(44)
        APP.processEvents()
        self.draw((406, 306))
        self.editor.apply_erase_action.trigger()
        self.pump(lambda: self.editor.job is None)
        self.assertIsNone(self.editor.last_error)
        self.assertEqual(len(self.editor.current_page.background_patches), 1)
        self.assertTrue(self.editor.canvas.brush_mask_image().isNull())
        self.assertEqual(self.editor.background_item.pixmap().toImage().pixelColor(406, 306), QColor('#f3e6d0'))
        repaired = self.pixels(self.editor.render_image())
        self.assertEqual(self.pixels(render_page(self.editor.current_page, original)), repaired)
        self.editor.undo()
        self.assertEqual(self.editor.current_page.background_patches, [])
        self.assertEqual(self.editor.render_image().pixelColor(406, 306), QColor('black'))
        self.editor.redo()
        self.assertEqual(self.pixels(self.editor.render_image()), repaired)
        destination = self.root / '수동 지우기.twproj'
        self.editor.save_to(destination)
        saved, assets = load_bundle(destination)
        self.assertEqual(len(saved.pages[0].background_patches), 1)
        self.assertEqual(assets[saved.pages[0].asset], original)
        self.editor.load_path(destination)
        self.assertEqual(self.pixels(self.editor.render_image()), repaired)
        self.assertEqual(self.source.read_bytes(), self.source_bytes)

    def test_page_switch_discards_late_region_result(self):
        self.editor.install_collection(*import_files([self.source, self.source]))
        entered, release = threading.Event(), threading.Event()

        def recognize(original, bounds, cancelled, progress, vertical):
            entered.set()
            release.wait(5)
            return self.region()

        with patch('studio.region_tools.recognize_region', side_effect=recognize):
            self.editor.start_region_ocr(QRectF(100, 100, 160, 48))
            try:
                self.pump(entered.is_set)
                self.editor.switch_page(1)
            finally:
                release.set()
                self.pump(lambda: self.editor.job is None)
        self.assertEqual(self.editor.page_index, 1)
        self.assertTrue(all(not page.objects for page in self.editor.project.pages))
        self.assertIsNone(self.editor.manual_task)

    def test_cancel_region_job_discards_late_result_and_preserves_document(self):
        entered, release = threading.Event(), threading.Event()
        before = deepcopy(self.editor.project)

        def recognize(original, bounds, cancelled, progress, vertical):
            entered.set()
            release.wait(5)
            return self.region()

        with patch('studio.region_tools.recognize_region', side_effect=recognize):
            self.editor.start_region_ocr(QRectF(100, 100, 160, 48))
            try:
                self.pump(entered.is_set)
                self.editor.cancel_region_selection()
            finally:
                release.set()
                self.pump(lambda: self.editor.job is None)
        self.assertEqual(self.editor.project, before)
        self.assertEqual(self.editor.canvas.tool, 'select')
        self.assertIsNone(self.editor.manual_task)

    def test_mouse_move_during_brush_job_keeps_operation_running_until_explicit_cancel(self):
        self.editor.set_canvas_tool('brush')
        APP.processEvents()
        self.draw((406, 306))
        before = deepcopy(self.editor.project)
        entered, release = threading.Event(), threading.Event()

        def erase(original, mask, cancelled, progress):
            entered.set()
            release.wait(5)
            return None

        with patch('studio.region_tools.make_erase_patch', side_effect=erase):
            self.editor.apply_brush_erase()
            try:
                self.pump(entered.is_set)
                self.assertFalse(self.editor.apply_erase_action.isEnabled())
                self.assertFalse(self.editor.region_action.isEnabled())
                view = self.editor.canvas
                QTest.mouseMove(view.viewport(), view.mapFromScene(QPointF(430, 320)), 20)
                APP.processEvents()
                self.assertFalse(self.editor.job.cancelled.is_set())
                self.assertFalse(view.brush_mask_image().isNull())
                QTest.keyClick(view.viewport(), Qt.Key_Escape)
                self.assertTrue(self.editor.job.cancelled.is_set())
            finally:
                release.set()
                self.pump(lambda: self.editor.job is None)
        self.assertEqual(self.editor.project, before)
        self.assertTrue(self.editor.canvas.brush_mask_image().isNull())
        self.assertTrue(self.editor.region_action.isEnabled())


if __name__ == '__main__':
    unittest.main(verbosity=2)
