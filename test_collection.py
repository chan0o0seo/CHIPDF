"""Whole-work persistence, page-local editing/jobs, PDF and atomic batch output."""
from test_studio import APP, ROOT, StudioTests
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from studio.document_io import Cancelled, export_collection, folder_images, import_files, render_page, png_data
from studio.model import Project
from studio.recognition import Region
from studio.storage import load_bundle, save_project


class CollectionTests(unittest.TestCase):
    setUp = StudioTests.setUp
    tearDown = StudioTests.tearDown
    insert = StudioTests.insert
    pixels = StudioTests.pixels

    def image_file(self, name, width=520, height=710, color='#bddcce'):
        image = QImage(width, height, QImage.Format_ARGB32)
        image.fill(QColor(color))
        path = self.root / name
        image.save(str(path))
        return path

    def collection(self):
        self.editor.install_collection(*import_files([self.source, self.image_file('카드2.png'), self.image_file('카드3.png', 850, 450, '#e7d6aa')]))

    def pdf_file(self):
        from reportlab.pdfgen.canvas import Canvas
        path = self.root / '두페이지.pdf'
        canvas = Canvas(str(path), pagesize=(216, 288))
        canvas.setFillColorRGB(.1, .5, .3)
        canvas.rect(0, 0, 216, 288, fill=1, stroke=0)
        canvas.setFillColorRGB(1, 1, 1)
        canvas.drawString(15, 240, 'FIRST PAGE')
        canvas.showPage()
        canvas.setPageSize((360, 180))
        canvas.setFillColorRGB(.7, .3, .1)
        canvas.rect(0, 0, 360, 180, fill=1, stroke=0)
        canvas.drawString(15, 130, 'SECOND PAGE')
        canvas.showPage()
        canvas.save()
        return path

    def pump(self, condition, timeout=10):
        deadline = time.monotonic()+timeout
        while not condition():
            APP.processEvents()
            time.sleep(.01)
            self.assertLess(time.monotonic(), deadline)
        APP.processEvents()

    def test_page_click_commits_ime_and_keeps_separate_edits(self):
        self.collection()
        first = self.insert('첫 카드 한글')
        key = first.model.id
        view = self.editor.card_list
        target = view.visualItemRect(view.item(1)).center()
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, target)
        self.assertEqual(self.editor.page_index, 1)
        self.assertIsNone(self.editor.editing_item())
        self.assertEqual(self.editor.project.pages[0].objects[0].text, '첫 카드 한글')
        self.insert('두 번째 카드').finish_edit()
        self.editor.switch_page(0)
        self.assertEqual(self.editor.items_by_id[key].model.text, '첫 카드 한글')
        self.assertEqual(len(self.editor.current_page.objects), 1)

    def test_undo_from_other_page_returns_to_edited_card(self):
        self.collection()
        self.insert('A').finish_edit()
        self.editor.switch_page(1)
        second = self.insert('B')
        key = second.model.id
        second.finish_edit()
        self.editor.switch_page(2)
        self.editor.undo()
        self.assertEqual(self.editor.page_index, 1)
        self.assertNotEqual(self.editor.items_by_id[key].model.text, 'B')
        self.assertEqual(self.editor.project.pages[0].objects[0].text, 'A')
        self.editor.redo()
        self.assertEqual(self.editor.items_by_id[key].model.text, 'B')

    def test_multipage_autosave_reopen_and_originals_embedded(self):
        self.collection()
        for index in range(3):
            self.editor.switch_page(index)
            self.insert(f'카드 {index+1}').finish_edit()
        path = self.root / '작품.twproj'
        self.editor.save_to(path)
        expected = [self.pixels(render_page(deepcopy(p), self.editor.assets[p.asset])) for p in self.editor.project.pages]
        self.editor.switch_page(0)
        self.editor.add_shape('ellipse')
        self.editor.autosave()
        saved, assets = load_bundle(path)
        self.assertEqual(len(saved.pages), 3)
        self.assertEqual(len(assets), 3)
        self.assertEqual(len(saved.pages[0].objects), 2)
        self.image_file('카드2.png').unlink()
        before = path.read_bytes()
        self.editor.load_path(path)
        self.assertEqual(path.read_bytes(), before)
        for index in (1, 2):
            self.editor.switch_page(index)
            self.assertEqual(self.pixels(self.editor.render_image()), expected[index])
        self.assertEqual(self.source.read_bytes(), self.source_bytes)

    def test_group_and_clipboard_on_later_page_do_not_change_first(self):
        self.collection()
        self.insert('첫 장 고정').finish_edit()
        before = deepcopy(self.editor.current_page)
        self.editor.switch_page(1)
        text = self.insert('두 번째 그룹')
        key = text.model.id
        text.finish_edit()
        shape = self.editor.add_shape('rect')
        self.editor.items_by_id[key].setSelected(True)
        self.editor.group_selected()
        self.editor.copy_objects()
        self.editor.switch_page(2)
        self.editor.paste_objects()
        self.assertEqual(len(self.editor.current_page.objects), 3)
        self.assertEqual(self.editor.project.pages[0], before)
        self.editor.enter_group(self.editor.selected()[0].model.id)
        child = next(o for o in self.editor.current_page.objects if o.kind == 'text')
        self.editor.items_by_id[child.id].setSelected(True)
        self.editor.apply_paragraph_settings({'margin': 3, 'line_spacing': 1.2})
        self.assertEqual(self.editor.project.pages[0], before)
        Project.from_dict(self.editor.project.to_dict())
        APP.clipboard().clear()

    def test_delayed_ocr_cannot_write_to_another_page(self):
        self.collection()
        release = threading.Event()
        self.editor.launch_job(lambda cancel, progress: (release.wait(2), [Region('古いページ', [15, 15, 90, 25], 90, 20)])[1], self.editor.accept_regions)
        self.editor.switch_page(1)
        release.set()
        self.pump(lambda: self.editor.job is None)
        self.assertTrue(all(not p.objects for p in self.editor.project.pages))
        self.editor.accept_regions([Region('現在のページ', [15, 15, 90, 25], 90, 20)])
        self.assertFalse(self.editor.project.pages[0].objects)
        self.assertEqual(self.editor.current_page.objects[0].source_text, '現在のページ')

    def test_delayed_translation_does_not_follow_page_switch(self):
        self.collection()
        self.editor.accept_regions([Region('証拠', [20, 20, 100, 30], 90, 20)])
        obj = self.editor.current_page.objects[0]
        snapshot = {obj.id: (obj.source_text, obj.text, deepcopy(obj.paragraphs))}
        release = threading.Event()
        self.editor.launch_job(lambda cancel, progress: (release.wait(2), [(obj.id, '증거', None)])[1], lambda rows: self.editor.accept_translations(rows, snapshot, False))
        self.editor.switch_page(1)
        self.insert('현재 수정').finish_edit()
        release.set()
        self.pump(lambda: self.editor.job is None)
        self.assertEqual(self.editor.current_page.objects[0].text, '현재 수정')
        self.assertEqual(self.editor.project.pages[0].objects[0].text, '')

    def test_append_is_one_undo_and_assets_survive_redo(self):
        self.insert('기존 편집').finish_edit()
        previous = deepcopy(self.editor.project)
        more = self.image_file('추가.png')
        self.editor.install_collection(*import_files([more]), append=True)
        self.assertEqual(self.editor.page_index, 1)
        self.editor.undo()
        self.assertEqual(self.editor.project, previous)
        self.editor.redo()
        self.assertEqual(len(self.editor.project.pages), 2)
        self.assertFalse(self.editor.image.isNull())
        self.editor.save_to(self.root / '추가작품.twproj')

    def test_folder_uses_natural_order_and_import_is_atomic(self):
        directory = self.root / '묶음'
        directory.mkdir()
        for name in ('10.png', '2.png', '1.png'):
            source = self.image_file(name)
            source.rename(directory/name)
        self.assertEqual([p.name for p in folder_images(directory)], ['1.png', '2.png', '10.png'])
        self.editor.load_path(directory)
        self.assertEqual([p.name for p in self.editor.project.pages], ['1.png', '2.png', '10.png'])
        before = deepcopy(self.editor.project)
        (directory/'4.png').write_bytes(b'broken')
        with self.assertRaises(ValueError):
            self.editor.load_path(directory)
        self.assertEqual(self.editor.project, before)

    def test_cancel_import_does_not_replace_current_document(self):
        before = deepcopy(self.editor.project)
        cancel = threading.Event()
        with self.assertRaises(Cancelled):
            result = import_files([self.source, self.image_file('중단.png')], cancel.is_set, lambda message: cancel.set())
            self.editor.install_collection(*result)
        self.assertEqual(self.editor.project, before)

    def test_native_async_import_finishes_and_cancel_preserves_work(self):
        self.editor.open_sources([self.source, self.image_file('비동기.png')])
        self.pump(lambda: self.editor.io_job is None)
        self.assertEqual(len(self.editor.project.pages), 2)
        before = deepcopy(self.editor.project)
        release = threading.Event()
        def slow(paths, cancelled, progress):
            release.wait(2)
            return import_files(paths, cancelled, progress)
        with patch('studio.collection.import_files', slow):
            self.editor.open_sources([self.source])
            self.editor.io_job.cancelled.set()
            release.set()
            self.pump(lambda: self.editor.io_job is None)
        self.assertEqual(self.editor.project, before)

    def test_pdf_import_preserves_pages_orientation_and_physical_sizes(self):
        path = self.pdf_file()
        original = path.read_bytes()
        self.editor.load_path(path)
        pages = self.editor.project.pages
        self.assertEqual(len(pages), 2)
        self.assertEqual((pages[0].width_pt, pages[0].height_pt), (216, 288))
        self.assertEqual((pages[1].width_pt, pages[1].height_pt), (360, 180))
        self.assertEqual((pages[0].width, pages[0].height), (600, 800))
        self.assertGreater(pages[1].width, pages[1].height)
        self.assertEqual(path.read_bytes(), original)
        with self.assertRaises(ValueError):
            self.editor.export_pages(path, [0, 1], 'pdf')

    def test_png_subset_export_is_identical_and_keeps_active_editor(self):
        self.collection()
        self.insert('첫 페이지').finish_edit()
        self.editor.add_shape('roundrect')
        self.editor.switch_page(1)
        self.insert('가운데').finish_edit()
        before = deepcopy(self.editor.project)
        selected = [i.model.id for i in self.editor.selected()]
        destination = self.root / '묶음출력'
        self.editor.export_pages(destination, [2, 0], 'png')
        paths = sorted(destination.glob('*.png'))
        self.assertEqual(len(paths), 2)
        self.assertTrue(paths[0].name.startswith('001_'))
        self.assertTrue(paths[1].name.startswith('003_'))
        self.assertEqual(self.editor.project, before)
        self.assertEqual(self.editor.page_index, 1)
        self.assertEqual([i.model.id for i in self.editor.selected()], selected)
        for path, index in zip(paths, (0, 2)):
            self.editor.switch_page(index)
            self.assertEqual(path.read_bytes(), png_data(self.editor.render_image()))

    def test_pdf_export_renders_every_page_with_correct_size(self):
        import pypdfium2 as pdfium
        self.editor.load_path(self.pdf_file())
        self.insert('한국어 PDF 편집').finish_edit()
        output = self.root / '완성.pdf'
        self.editor.export_pages(output, [0, 1], 'pdf')
        with pdfium.PdfDocument(output) as document:
            self.assertEqual(len(document), 2)
            for index, page in enumerate(self.editor.project.pages):
                with closing(document[index]) as pdf_page:
                    self.assertEqual(pdf_page.get_size(), (page.width_pt, page.height_pt))
                    with closing(pdf_page.render(scale=200/72)) as bitmap:
                        self.assertEqual((bitmap.width, bitmap.height), (page.width, page.height))

    def test_cancelled_batch_keeps_existing_pdf_and_no_png_directory(self):
        self.collection()
        for kind in ('png', 'pdf'):
            target = self.root / ('중단.pdf' if kind == 'pdf' else '중단폴더')
            if kind == 'pdf':
                target.write_bytes(b'previous output')
            stopped = [False]
            def progress(value):
                if value == 1:
                    stopped[0] = True
            with self.assertRaises(Cancelled):
                self.editor.export_pages(target, [0, 1, 2], kind, lambda: stopped[0], progress)
            self.assertEqual(target.read_bytes(), b'previous output') if kind == 'pdf' else self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob('.studio-export-*')))

    def test_missing_asset_and_cross_page_parent_are_rejected_before_swap(self):
        self.collection()
        path = self.root / '손상.twproj'
        self.editor.save_to(path)
        before = deepcopy(self.editor.project)
        with zipfile.ZipFile(path) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        entries.pop(self.editor.project.pages[1].asset)
        with zipfile.ZipFile(path, 'w') as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        with self.assertRaises(ValueError):
            self.editor.load_path(path)
        self.assertEqual(self.editor.project, before)
        bad = deepcopy(before)
        bad.pages[1].asset = bad.pages[0].asset
        with self.assertRaises(ValueError):
            Project.from_dict(bad.to_dict())


if __name__ == '__main__':
    unittest.main()
