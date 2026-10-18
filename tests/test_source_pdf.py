"""Native PDF retention, compact edit layers and legacy output compatibility."""
from copy import deepcopy
from io import BytesIO
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / '.deps'), str(ROOT)]
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image, ImageChops, ImageDraw, ImageStat
from PySide6.QtWidgets import QApplication
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject
import pypdfium2
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader

from studio.document_io import Cancelled, export_collection, import_files, validate_bundle
from studio.model import BackgroundPatch, GroupBox, Page, Paragraph, Project, Run, ShapeBox, Style, TextBox
from studio.recognition import encode_png
from studio.storage import load_bundle, required_assets, save_project


def pdf_image(path, index=0, scale=200/72):
    with pypdfium2.PdfDocument(str(path)) as document:
        page = document[index]
        try:
            bitmap = page.render(scale=scale)
            try:
                return bitmap.to_pil().convert('RGB')
            finally:
                bitmap.close()
        finally:
            page.close()


class SourcePdfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'qa', prefix='source-pdf-')
        self.work = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, count=2, rotation=0, crop=False, photo=False):
        source = self.work / 'original.pdf'
        canvas = Canvas(str(source), pagesize=(360, 288), pageCompression=1)
        if photo:
            randomizer = random.Random(109)
            image = Image.frombytes('RGB', (700, 560), randomizer.randbytes(700*560*3))
            encoded = BytesIO()
            image.save(encoded, 'JPEG', quality=70)
        for index in range(count):
            if photo:
                canvas.drawImage(ImageReader(BytesIO(encoded.getvalue())), 0, 0, 360, 288)
            canvas.setFillColorRGB(.1, .5, .8)
            canvas.rect(35, 30, 150, 140, fill=1, stroke=0)
            canvas.setFillColorRGB(0, 0, 0)
            canvas.setFont('Helvetica', 14)
            canvas.drawString(45, 215, f'Source text {index+1}')
            canvas.bookmarkPage(str(index))
            if count > 1:
                canvas.linkRect('', str((index+1) % count), (45, 210, 145, 230), thickness=0)
            canvas.showPage()
        canvas.save()
        if rotation or crop:
            writer = PdfWriter()
            reader = PdfReader(source)
            for page in reader.pages:
                result = writer.add_page(page, excluded_keys=('/Annots',))
                if crop:
                    result.cropbox = RectangleObject((20, 15, 330, 270))
                if rotation:
                    result.rotate(rotation)
            writer.write(source)
        return source

    def test_archive_embeds_source_once_and_does_not_need_external_file(self):
        source = self.fixture()
        original = source.read_bytes()
        project, assets, _ = import_files([source])
        self.assertEqual(project.version, 12)
        self.assertEqual(project.pages[0].pdf_asset, project.pages[1].pdf_asset)
        saved = self.work / 'edited.twproj'
        save_project(saved, project, assets)
        with zipfile.ZipFile(saved) as archive:
            self.assertEqual(sum(name.endswith('.pdf') for name in archive.namelist()), 1)
        loaded, stored = load_bundle(saved)
        validate_bundle(loaded, stored)
        source.unlink()
        output = self.work / 'output.pdf'
        export_collection(loaded, stored, [0, 1], output, 'pdf')
        reader = PdfReader(output)
        self.assertIn('Source text 1', reader.pages[0].extract_text())
        self.assertIn('Source text 2', reader.pages[1].extract_text())
        self.assertEqual(stored[project.pages[0].pdf_asset], original)
        self.assertFalse(reader.pages[0].get('/Resources', {}).get('/XObject'))

    def test_small_edit_keeps_jpeg_and_is_much_smaller_than_raster_export(self):
        source = self.fixture(count=1, photo=True)
        original = source.read_bytes()
        project, assets, _ = import_files([source])
        page = project.pages[0]
        page.objects.append(TextBox(x=100, y=80, width=250, height=80,
                                   paragraphs=[Paragraph([Run('Edited', Style(size=24))])]))
        output, raster = self.work / 'native.pdf', self.work / 'raster.pdf'
        export_collection(project, assets, [0], output, 'pdf')
        legacy = deepcopy(project)
        legacy.pages[0].pdf_asset, legacy.pages[0].pdf_page = '', -1
        export_collection(legacy, assets, [0], raster, 'pdf')
        self.assertLess(output.stat().st_size, raster.stat().st_size/3)
        print(f'PDF size comparison: original={len(original)}, native={output.stat().st_size}, raster={raster.stat().st_size}')
        self.assertIn('Source text 1', PdfReader(output).pages[0].extract_text())
        self.assertEqual(source.read_bytes(), original)
        expected, actual = pdf_image(raster), pdf_image(output)
        self.assertLess(sum(ImageStat.Stat(ImageChops.difference(expected, actual)).mean)/3, 4)
        # Pixels well away from the edit retain the native PDF's rendering.
        original_image = pdf_image(source)
        self.assertIsNone(ImageChops.difference(original_image.crop((600, 400, 900, 700)),
                                              actual.crop((600, 400, 900, 700))).getbbox())

    def test_rotated_crop_and_grouped_edits_match_legacy_rendering(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                source = self.fixture(count=1, rotation=rotation, crop=True)
                project, assets, _ = import_files([source])
                page = project.pages[0]
                group = GroupBox(x=90, y=120, width=240, height=150, rotation=13, scale=.8)
                shape = ShapeBox(x=5, y=10, width=100, height=70, fill='#ff3300',
                                 opacity=.4, parent_id=group.id)
                text = TextBox(x=20, y=25, width=230, height=95, parent_id=group.id,
                               paragraphs=[Paragraph([Run('Changed', Style(size=25, bold=True))])])
                page.objects = [group, shape, text]
                native, raster = self.work / f'native-{rotation}.pdf', self.work / f'raster-{rotation}.pdf'
                export_collection(project, assets, [0], native, 'pdf')
                legacy = deepcopy(project)
                legacy.pages[0].pdf_asset, legacy.pages[0].pdf_page = '', -1
                export_collection(legacy, assets, [0], raster, 'pdf')
                expected, actual = pdf_image(raster), pdf_image(native)
                self.assertEqual(actual.size, expected.size)
                self.assertLess(sum(ImageStat.Stat(ImageChops.difference(expected, actual)).mean)/3, 1.5)
                self.assertIn('Source text 1', PdfReader(native).pages[0].extract_text())

    def test_repair_masks_feathering_and_empty_erase_match_preview(self):
        source = self.fixture(count=1)
        project, assets, _ = import_files([source])
        page = project.pages[0]
        patch = Image.new('RGBA', (180, 90), '#ffffff')
        mask = Image.new('L', patch.size)
        ImageDraw.Draw(mask).rectangle((10, 10, 169, 79), fill=255)
        ImageDraw.Draw(mask).line((5, 5, 175, 5), fill=90, width=2)
        box = TextBox(x=500, y=250, width=180, height=90, erase_rect=[100, 150, 180, 90],
                      erase_patch=encode_png(patch), erase_mask=encode_png(mask), erase_when_empty=True,
                      paragraphs=[Paragraph([Run('')])])
        page.objects = [box]
        repair = Image.new('RGBA', (40, 30), '#ffcc88')
        page.background_patches = [BackgroundPatch(rect=[110, 160, 40, 30],
            patch=encode_png(repair), mask=encode_png(Image.new('L', (40, 30), 255)))]
        native, raster = self.work / 'native.pdf', self.work / 'raster.pdf'
        export_collection(project, assets, [0], native, 'pdf')
        legacy = deepcopy(project)
        legacy.pages[0].pdf_asset, legacy.pages[0].pdf_page = '', -1
        export_collection(legacy, assets, [0], raster, 'pdf')
        expected, actual = pdf_image(raster), pdf_image(native)
        region = (100, 150, 280, 240)
        self.assertLess(sum(ImageStat.Stat(ImageChops.difference(expected.crop(region), actual.crop(region))).mean)/3, 1)

    def test_reorder_partial_mixed_pages_and_cancelled_export(self):
        project, assets, _ = import_files([self.fixture()])
        first, last = project.pages
        image = Image.new('RGB', (200, 150), '#ff0000')
        data = BytesIO()
        image.save(data, 'PNG')
        blank = Page(width=200, height=150)
        blank.asset = f'assets/{blank.id}.png'
        assets[blank.asset] = data.getvalue()
        project.pages = [last, blank, first]
        output = self.work / 'mixed.pdf'
        export_collection(project, assets, [0, 1, 2], output, 'pdf')
        reader = PdfReader(output)
        self.assertIn('Source text 2', reader.pages[0].extract_text())
        self.assertEqual(reader.pages[2]['/Annots'][0].get_object()['/Dest'][0], reader.pages[0].indirect_reference)
        self.assertEqual(pdf_image(output, 1).getpixel((80, 80)), (255, 0, 0))
        export_collection(project, assets, [2], self.work / 'partial.pdf', 'pdf')
        self.assertFalse(PdfReader(self.work / 'partial.pdf').pages[0].get('/Annots'))
        prior = output.read_bytes()
        with self.assertRaises(Cancelled):
            export_collection(project, assets, [0, 1, 2], output, 'pdf', cancel=lambda: True)
        self.assertEqual(output.read_bytes(), prior)
        self.assertFalse(list(self.work.glob('.studio-export-*')))

    def test_legacy_schema_and_invalid_embedded_sources(self):
        project, assets, _ = import_files([self.fixture(count=1)])
        broken = dict(assets)
        broken[project.pages[0].pdf_asset] = b'broken'
        with self.assertRaisesRegex(ValueError, '원본 PDF'):
            validate_bundle(project, broken)
        invalid = deepcopy(project)
        invalid.pages[0].pdf_page = 199
        with self.assertRaisesRegex(ValueError, '해당 페이지'):
            validate_bundle(invalid, assets)
        old = project.to_dict()
        old['version'] = 11
        del old['pages'][0]['pdf_asset']
        del old['pages'][0]['pdf_page']
        legacy = Project.from_dict(old)
        self.assertFalse(legacy.pages[0].pdf_asset)
        self.assertNotIn(project.pages[0].pdf_asset, required_assets(legacy))
        for asset, index in (('../source.pdf', 0), ('', 0), (project.pages[0].pdf_asset, True)):
            bad = project.to_dict()
            bad['pages'][0].update(pdf_asset=asset, pdf_page=index)
            with self.assertRaises(ValueError):
                Project.from_dict(bad)

    def test_existing_background_repair_upgrades_old_project(self):
        from studio.pdf_repair import prepare_pdf_repair
        source = self.fixture(count=1)
        project, assets, _ = import_files([source])
        key = project.pages[0].pdf_asset
        project.pages[0].pdf_asset, project.pages[0].pdf_page = '', -1
        del assets[key]
        repaired, merged, matched, _ = prepare_pdf_repair(project, assets, [source])
        self.assertEqual(matched, 1)
        self.assertEqual(repaired.pages[0].pdf_asset, key)
        self.assertIn(key, merged)
        self.assertFalse(project.pages[0].pdf_asset)


if __name__ == '__main__':
    unittest.main()
