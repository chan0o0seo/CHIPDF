from test_studio import APP, StudioTests
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject
from pypdf.generic import DictionaryObject, ArrayObject
from reportlab.pdfgen.canvas import Canvas
from PySide6.QtCore import QRectF

from studio.document_io import import_files, export_collection, Cancelled
from studio.model import Project, Page, TextBox, GroupBox, Paragraph, Run
from studio.pdf_links import export_links, prepare_link_repair
from studio.storage import save_project, load_bundle


def fixture(path):
    canvas = Canvas(str(path), pagesize=(300, 400))
    for index in range(3):
        canvas.bookmarkPage(f'p{index}')
        canvas.drawString(20, 350, f'PAGE {index+1}')
        if index == 0:
            canvas.linkRect('', 'p2', (20, 340, 110, 365), relative=0)
        if index == 2:
            canvas.linkRect('', 'p0', (20, 340, 110, 365), relative=0)
        canvas.showPage()
    canvas.save()


class PdfLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root/'source.pdf'
        fixture(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def imported(self):
        return import_files([self.source])[:2]

    def test_import_roundtrip_translation_move_and_subset_export(self):
        project, assets = self.imported()
        page, target = project.pages[0], project.pages[2]
        self.assertEqual(page.pdf_links[0]['page_id'], target.id)
        rect = page.pdf_links[0]['rect']
        page.objects.append(TextBox(x=200, y=220, width=310, height=65,
            source_rect=rect, paragraphs=[Paragraph([Run('다음 장으로 이동')])]))
        saved = self.root/'work.twproj'
        save_project(saved, project, assets)
        project, assets = load_bundle(saved)
        self.source.unlink()
        output = self.root/'result.pdf'
        export_collection(project, assets, [0, 2], output, 'pdf')
        reader = PdfReader(output)
        annot = reader.pages[0]['/Annots'][0].get_object()
        self.assertEqual(annot['/Dest'][0], reader.pages[1].indirect_reference)
        self.assertAlmostEqual(float(annot['/Rect'][0]), 200*300/page.width, places=3)
        self.assertEqual(len(reader.pages[0]['/Annots']), 1)
        self.assertEqual(reader.pages[1]['/Annots'][0].get_object()['/Dest'][0], reader.pages[0].indirect_reference)
        export_collection(project, assets, [0], output, 'pdf')
        self.assertFalse(PdfReader(output).pages[0].get('/Annots'))

    def test_rotated_and_cropped_source_rect_matches_pdfium_coordinates(self):
        writer = PdfWriter(self.source)
        writer.pages[0].cropbox.lower_left = (10, 20)
        writer.pages[0].cropbox.upper_right = (280, 390)
        writer.pages[0].rotate(90)
        writer.write(self.root/'rotated.pdf')
        project, _, _ = import_files([self.root/'rotated.pdf'])
        page = project.pages[0]
        x, y, w, h = page.pdf_links[0]['rect']
        # Rotated crop: (PDF y-20, PDF x-10), rendered at 200 dpi.
        self.assertAlmostEqual(x/page.width, 320/370, delta=.002)
        self.assertAlmostEqual(y/page.height, 10/270, delta=.002)
        self.assertAlmostEqual(w/page.width, 25/370, delta=.002)
        self.assertAlmostEqual(h/page.height, 90/270, delta=.002)

    def test_named_destination_is_resolved(self):
        writer = PdfWriter(self.source)
        writer.add_named_destination('chapter', 2)
        writer.pages[0]['/Annots'][0].get_object()[NameObject('/Dest')] = TextStringObject('chapter')
        path = self.root/'named.pdf'
        writer.write(path)
        project, _, _ = import_files([path])
        self.assertEqual(project.pages[0].pdf_links[0]['page_id'], project.pages[2].id)

    def test_goto_action_and_multiple_imports_keep_destinations_separate(self):
        writer = PdfWriter(self.source)
        annot = writer.pages[0]['/Annots'][0].get_object()
        dest = annot.pop('/Dest')
        annot[NameObject('/A')] = DictionaryObject({NameObject('/S'): NameObject('/GoTo'), NameObject('/D'): dest})
        path = self.root/'action.pdf'
        writer.write(path)
        project, _, _ = import_files([self.source, path])
        self.assertEqual(project.pages[0].pdf_links[0]['page_id'], project.pages[2].id)
        self.assertEqual(project.pages[3].pdf_links[0]['page_id'], project.pages[5].id)

    def test_legacy_repair_preserves_edits_and_has_no_source_dependency(self):
        project, assets = self.imported()
        expected = deepcopy(project)
        for page in project.pages:
            page.pdf_links = []
        project.pages[0].objects = [TextBox(paragraphs=[Paragraph([Run('이미 번역한 문장')])])]
        before = deepcopy(project)
        repaired, count = prepare_link_repair(project, assets, [self.source])
        self.assertEqual(count, 2)
        self.assertEqual(project, before)
        self.assertEqual(repaired.pages[0].objects, before.pages[0].objects)
        self.assertEqual(repaired.pages[0].pdf_links, expected.pages[0].pdf_links)
        with self.assertRaises(ValueError):
            prepare_link_repair(repaired, assets, [self.source])
        with self.assertRaises(Cancelled):
            prepare_link_repair(project, assets, [self.source], lambda: True)

    def test_group_transform_and_manual_disable_override(self):
        page, target = Page(), Page()
        group = GroupBox(x=180, y=220, width=300, height=200, rotation=90, scale=1.2)
        box = TextBox(x=10, y=20, width=100, height=40, parent_id=group.id,
                      source_rect=[10, 10, 100, 40])
        page.objects = [group, box]
        page.pdf_links = [{'rect': [10, 10, 100, 40], 'page_id': target.id}]
        links = export_links(page, {page.id, target.id})
        self.assertEqual(len(links), 1)
        self.assertAlmostEqual(links[0][0][2], 48)
        self.assertAlmostEqual(links[0][0][3], 120)
        box.link_mode = 'none'
        self.assertFalse(export_links(page, {page.id, target.id}))
        box.link_mode, box.link_page_id = 'page', page.id
        self.assertEqual(export_links(page, {page.id, target.id})[0][1], page.id)
        group.opacity = 0
        self.assertFalse(export_links(page, {page.id, target.id}))

    def test_blank_erased_box_and_multiple_destinations(self):
        page, second, third = Page(), Page(), Page()
        box = TextBox(x=200, y=200, width=200, height=100, source_rect=[0, 0, 200, 100])
        page.objects = [box]
        page.pdf_links = [{'rect': [10, 10, 80, 20], 'page_id': second.id},
                          {'rect': [10, 50, 80, 20], 'page_id': third.id}]
        ids = {page.id, second.id, third.id}
        links = export_links(page, ids)
        self.assertEqual(len(links), 2)
        self.assertFalse(QRectF(*links[0][0]).intersects(QRectF(*links[1][0])))
        box.paragraphs = [Paragraph([Run('')])]
        self.assertEqual(len(export_links(page, ids)), 2)
        box.erase_when_empty = True
        self.assertFalse(export_links(page, ids))

    def test_validation_and_old_version_migration(self):
        project, _ = self.imported()
        data = project.to_dict()
        data['version'] = 8
        for page in data['pages']:
            page.pop('pdf_links')
        self.assertEqual(Project.from_dict(data).version, 9)
        data = project.to_dict()
        data['pages'][0]['pdf_links'][0]['rect'][0] = float('nan')
        with self.assertRaises(ValueError):
            Project.from_dict(data)
        data = project.to_dict()
        data['pages'][0]['pdf_links'][0]['page_id'] = 'f'*32
        with self.assertRaises(ValueError):
            Project.from_dict(data)


class LinkEditorTests(unittest.TestCase):
    setUp = StudioTests.setUp
    tearDown = StudioTests.tearDown
    insert = StudioTests.insert

    def test_manual_link_undo_copy_and_save(self):
        item = self.insert('다음 페이지')
        item.finish_edit()
        key = item.model.id
        self.editor.set_page_link('page', self.editor.current_page.id)
        self.assertEqual(self.editor.items_by_id[key].model.link_mode, 'page')
        self.editor.undo()
        self.assertEqual(self.editor.items_by_id[key].model.link_mode, 'auto')
        self.editor.redo()
        self.editor.copy_objects()
        self.editor.paste_objects()
        self.assertEqual(len(self.editor.current_page.objects), 2)
        self.assertEqual(self.editor.current_page.objects[-1].link_page_id, self.editor.current_page.id)
        self.editor.save_to(self.root/'links.twproj')
        self.assertEqual(load_bundle(self.root/'links.twproj')[0], self.editor.project)


if __name__ == '__main__':
    unittest.main()
