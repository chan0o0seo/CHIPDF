from test_studio import APP, StudioTests
from test_workflow import WorkflowTests
from test_pdf_text_stream import clipped_pdf
from copy import deepcopy
from io import BytesIO
import threading
import unittest
from unittest.mock import patch

from PIL import Image
from studio.document_io import import_files
from studio.model import TextBox, Paragraph, Run
from studio.pdf_repair import prepare_pdf_repair
from studio.recognition import encode_png, restored_background
from studio.storage import load_bundle


class PdfRepairTests(unittest.TestCase):
    setUp = StudioTests.setUp
    tearDown = StudioTests.tearDown
    pump = WorkflowTests.pump

    def legacy(self):
        pdf = self.root / 'original.pdf'
        pdf.write_bytes(clipped_pdf())
        project, assets, _ = import_files([pdf])
        page = project.pages[0]
        clean = assets.pop(page.clean_asset)
        page.clean_asset = ''
        rect = [10, 10, page.width-20, page.height-20]
        page.objects = [TextBox(x=70, y=110, rotation=15, width=320, height=100,
                        source_text='日本語', source_rect=rect,
                        paragraphs=[Paragraph([Run('직접 고친 번역')])],
                        erase_rect=rect, erase_mask=encode_png(Image.new('L', tuple(rect[2:]), 255)),
                        erase_patch=encode_png(Image.new('RGBA', tuple(rect[2:]), '#bbbbbb')))]
        return pdf, project, assets, clean

    def test_repair_preserves_translation_layout_and_original_pixels(self):
        path, project, assets, clean = self.legacy()
        before = deepcopy(project)
        repaired, merged, pages, boxes = prepare_pdf_repair(project, assets, [path])
        self.assertEqual((pages, boxes), (1, 1))
        self.assertEqual(project, before)
        self.assertEqual(merged[project.pages[0].asset], assets[project.pages[0].asset])
        old, new = project.pages[0].objects[0], repaired.pages[0].objects[0]
        self.assertEqual((old.text, old.x, old.y, old.width, old.height, old.rotation),
                         (new.text, new.x, new.y, new.width, new.height, new.rotation))
        actual = Image.open(BytesIO(restored_background(merged[project.pages[0].asset], [new]))).convert('RGBA')
        self.assertEqual(actual.tobytes(), Image.open(BytesIO(clean)).convert('RGBA').tobytes())

    def test_wrong_pdf_rejected_before_work_changes(self):
        path, project, assets, _ = self.legacy()
        wrong = self.root / 'wrong.pdf'
        wrong.write_bytes(clipped_pdf(False))
        before = deepcopy(project)
        with self.assertRaises(ValueError):
            prepare_pdf_repair(project, assets, [wrong])
        self.assertEqual(project, before)

    def test_editor_repair_undo_redo_and_self_contained_reopen(self):
        path, project, assets, _ = self.legacy()
        self.editor.install_collection(project, assets)
        before = deepcopy(self.editor.project)
        self.editor.start_pdf_background_repair([path])
        self.pump(lambda: self.editor.job is None)
        self.assertIsNone(self.editor.last_error)
        self.assertTrue(self.editor.current_page.clean_asset)
        after = deepcopy(self.editor.project)
        self.editor.undo()
        self.assertEqual(self.editor.project, before)
        self.editor.redo()
        self.assertEqual(self.editor.project, after)
        saved = self.root / 'repaired.twproj'
        self.editor.save_to(saved)
        path.unlink()  # Only the generated fixture is deleted.
        self.editor.load_path(saved)
        self.assertEqual(self.editor.project, after)
        self.assertEqual(len(load_bundle(saved)[1]), 2)

    def test_edit_while_repairing_discards_snapshot_instead_of_losing_typing(self):
        path, project, assets, _ = self.legacy()
        self.editor.install_collection(project, assets)
        entered, release = threading.Event(), threading.Event()
        result = prepare_pdf_repair(project, assets, [path])
        def delayed(*args):
            entered.set()
            release.wait(5)
            return result
        with patch('studio.pdf_repair.prepare_pdf_repair', side_effect=delayed):
            self.editor.start_pdf_background_repair([path])
            self.pump(entered.is_set)
            self.editor.begin_operation()
            self.editor.current_page.objects[0].paragraphs[0].runs[0].text = '계속 입력한 글'
            self.editor.finish_operation('글 수정')
            release.set()
            self.pump(lambda: self.editor.job is None)
        self.assertEqual(self.editor.current_page.objects[0].text, '계속 입력한 글')
        self.assertFalse(self.editor.current_page.clean_asset)


if __name__ == '__main__':
    unittest.main()
