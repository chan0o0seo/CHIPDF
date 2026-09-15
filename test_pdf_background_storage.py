"""PDF background persistence, bounded import, and legacy archive behavior."""
from test_studio import APP, StudioTests
from contextlib import closing
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from PySide6.QtGui import QColor, QImage

from studio.document_io import Cancelled, import_files, png_data, validate_bundle
from studio.model import Page, Project
from studio.storage import load_bundle, load_project, save_project


class SizedBytes(bytes):
    """Exercise pre-write size guards without allocating hundreds of MB."""
    def __new__(cls, size):
        value = super().__new__(cls, b'bounded fixture')
        value.size = size
        return value

    def __len__(self):
        return self.size


class PdfBackgroundStorageTests(unittest.TestCase):
    setUp = StudioTests.setUp
    tearDown = StudioTests.tearDown
    pixels = StudioTests.pixels

    def background_project(self):
        project = deepcopy(self.editor.project)
        page = project.pages[0]
        page.clean_asset = f'assets/{page.id}_background.png'
        image = QImage(page.width, page.height, QImage.Format_ARGB32)
        image.fill(QColor('#badae5'))
        assets = {page.asset: self.editor.original, page.clean_asset: png_data(image)}
        return project, assets

    def archive(self, path, project, assets):
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json', json.dumps(project.to_dict()))
            for key, value in assets.items():
                archive.writestr(key, value)

    def pdf_file(self, name='native.pdf', text=True, raster=False):
        from reportlab.pdfgen.canvas import Canvas
        from reportlab.lib.utils import ImageReader
        path = self.root / name
        canvas = Canvas(str(path), pagesize=(216, 288))
        canvas.setFillColorRGB(.2, .5, .7)
        canvas.rect(0, 0, 216, 288, fill=1, stroke=0)
        canvas.setFillColorRGB(.7, .4, .1)
        canvas.rect(30, 0, 80, 288, fill=1, stroke=0)
        if raster:
            canvas.drawImage(ImageReader(BytesIO(self.source_bytes)), 0, 0, 216, 288)
        if text:
            canvas.setFillColorRGB(0, 0, 0)
            canvas.setFont('Helvetica', 24)
            canvas.drawString(20, 200, 'NATIVE TEXT')
        canvas.showPage()
        canvas.save()
        return path

    def test_single_page_background_roundtrip_keeps_original_and_asset_map(self):
        project, assets = self.background_project()
        path = self.root / 'background.twproj'
        save_project(path, project, assets)
        loaded, restored = load_project(path)
        self.assertEqual(loaded, project)
        self.assertIsInstance(restored, dict)
        self.assertEqual(restored, assets)
        self.assertEqual(loaded.version, 8)
        validate_bundle(loaded, restored)
        self.assertEqual(self.source.read_bytes(), self.source_bytes)
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(set(archive.namelist()), set(assets) | {'manifest.json'})

    def test_legacy_single_asset_contract_and_all_versions_migrate(self):
        for version in range(1, 8):
            data = self.editor.project.to_dict()
            data['version'] = version
            data['pages'][0].pop('clean_asset')
            project = Project.from_dict(data)
            self.assertEqual(project.version, 8)
            self.assertEqual(project.pages[0].clean_asset, '')
            path = self.root / f'legacy-{version}.twproj'
            self.archive(path, project, {project.pages[0].asset: self.editor.original})
            restored, original = load_project(path)
            self.assertEqual(original, self.editor.original)
            self.assertIsInstance(original, bytes)
            self.assertEqual(restored.pages[0].clean_asset, '')

    def test_clean_reference_is_local_and_belongs_to_its_page(self):
        project, _ = self.background_project()
        for reference in ('../background.png', 'assets/original.png',
                          f'assets/{"a" * 32}_background.png',
                          'C:/Users/User/private.png', None, 3):
            invalid = project.to_dict()
            invalid['pages'][0]['clean_asset'] = reference
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                Project.from_dict(invalid)
        duplicate = project.to_dict()
        duplicate['pages'].append(deepcopy(duplicate['pages'][0]))
        with self.assertRaises(ValueError):
            Project.from_dict(duplicate)

    def test_missing_background_rejected_before_save_and_document_swap(self):
        project, assets = self.background_project()
        assets.pop(project.pages[0].clean_asset)
        path = self.root / 'missing.twproj'
        with self.assertRaises(ValueError):
            save_project(path, project, assets)
        self.assertFalse(path.exists())
        self.archive(path, project, assets)
        before = deepcopy(self.editor.project)
        with self.assertRaises(ValueError):
            self.editor.load_path(path)
        self.assertEqual(self.editor.project, before)

    def test_corrupt_or_wrong_size_background_rejected_before_document_swap(self):
        project, assets = self.background_project()
        small = QImage(40, 50, QImage.Format_ARGB32)
        small.fill(QColor('white'))
        before = deepcopy(self.editor.project)
        for invalid in (b'not PNG', png_data(small)):
            assets[project.pages[0].clean_asset] = invalid
            path = self.root / 'corrupt.twproj'
            self.archive(path, project, assets)
            with self.assertRaises(ValueError):
                self.editor.load_path(path)
            self.assertEqual(self.editor.project, before)

    def test_save_budget_counts_each_background_and_combined_assets(self):
        project, assets = self.background_project()
        path = self.root / 'oversize.twproj'
        assets[project.pages[0].clean_asset] = SizedBytes(250_000_001)
        with self.assertRaises(ValueError):
            save_project(path, project, assets)
        self.assertFalse(path.exists())
        second = Page(width=100, height=100)
        second.asset = f'assets/{second.id}.png'
        project.pages.append(second)
        assets = {project.pages[0].asset: SizedBytes(200_000_000),
                  project.pages[0].clean_asset: SizedBytes(200_000_000),
                  second.asset: SizedBytes(200_000_000)}
        with self.assertRaises(ValueError):
            save_project(path, project, assets)
        self.assertFalse(path.exists())

    def test_archive_supports_200_pages_with_backgrounds(self):
        pages, assets = [], {}
        image = QImage(24, 24, QImage.Format_ARGB32)
        image.fill(QColor('white'))
        data = png_data(image)
        for _ in range(200):
            page = Page(width=24, height=24)
            page.asset = f'assets/{page.id}.png'
            page.clean_asset = f'assets/{page.id}_background.png'
            pages.append(page)
            assets.update({page.asset: data, page.clean_asset: data})
        project = Project(pages=pages)
        path = self.root / 'full.twproj'
        save_project(path, project, assets)
        loaded, restored = load_bundle(path)
        self.assertEqual(loaded, project)
        self.assertEqual(len(restored), 400)

    def test_appending_background_assets_survives_undo_redo_and_save(self):
        project, assets = self.background_project()
        page = project.pages[0]
        replacement = Page(width=page.width, height=page.height)
        replacement.asset = f'assets/{replacement.id}.png'
        replacement.clean_asset = f'assets/{replacement.id}_background.png'
        project.pages = [replacement]
        assets = {replacement.asset: assets[page.asset], replacement.clean_asset: assets[page.clean_asset]}
        self.editor.install_collection(project, assets, append=True)
        self.assertEqual(self.editor.current_page.clean_asset, replacement.clean_asset)
        self.editor.undo()
        self.assertEqual(len(self.editor.project.pages), 1)
        self.editor.redo()
        self.assertEqual(self.editor.assets[replacement.clean_asset], assets[replacement.clean_asset])
        path = self.root / 'appended.twproj'
        self.editor.save_to(path)
        _, restored = load_bundle(path)
        self.assertEqual(restored[replacement.clean_asset], assets[replacement.clean_asset])

    def test_append_budget_counts_backgrounds_before_mutation(self):
        page = Page(width=24, height=24)
        page.asset = f'assets/{page.id}.png'
        page.clean_asset = f'assets/{page.id}_background.png'
        more = Project(pages=[page])
        assets = {page.asset: SizedBytes(260_000_000), page.clean_asset: SizedBytes(260_000_000)}
        before = deepcopy(self.editor.project)
        with self.assertRaises(ValueError):
            self.editor.install_collection(more, assets, append=True)
        self.assertEqual(self.editor.project, before)

    def test_native_pdf_import_retains_exact_original_and_real_background(self):
        import pypdfium2 as pdfium
        source = self.pdf_file()
        before = source.read_bytes()
        with pdfium.PdfDocument(source) as document:
            with closing(document[0]) as page, closing(page.render(scale=200/72)) as bitmap:
                stream = BytesIO()
                bitmap.to_pil().save(stream, 'PNG')
                original_pixels = self.pixels(QImage.fromData(stream.getvalue(), 'PNG'))
        project, assets, _ = import_files([source])
        page = project.pages[0]
        self.assertTrue(page.clean_asset)
        self.assertEqual(len(assets), 2)
        self.assertEqual(self.pixels(QImage.fromData(assets[page.asset], 'PNG')), original_pixels)
        expected, expected_assets, _ = import_files([self.pdf_file('text-free.pdf', text=False)])
        expected_background = QImage.fromData(expected_assets[expected.pages[0].asset], 'PNG')
        clean = QImage.fromData(assets[page.clean_asset], 'PNG')
        self.assertEqual(self.pixels(clean), self.pixels(expected_background))
        self.assertEqual(source.read_bytes(), before)

    def test_raster_pdf_has_no_extra_asset(self):
        project, assets, _ = import_files([self.pdf_file(text=False, raster=True)])
        self.assertEqual(project.pages[0].clean_asset, '')
        self.assertEqual(len(assets), 1)

    def test_identical_clean_render_is_not_stored(self):
        path = self.pdf_file(text=False)
        project, assets, _ = import_files([path])
        data = assets[project.pages[0].asset]
        with patch('studio.pdf_background.render_without_text', return_value=(data, 1)):
            project, assets, _ = import_files([path])
        self.assertEqual(project.pages[0].clean_asset, '')
        self.assertEqual(len(assets), 1)

    def test_cancel_during_pdf_background_preparation_preserves_open_work(self):
        path = self.pdf_file()
        original = path.read_bytes()
        before = deepcopy(self.editor.project)
        with patch('studio.pdf_background.render_without_text', side_effect=InterruptedError('cancel')):
            with self.assertRaises(Cancelled):
                self.editor.load_path(path)
        self.assertEqual(self.editor.project, before)
        self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
