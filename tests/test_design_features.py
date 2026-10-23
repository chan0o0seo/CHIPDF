"""Text effects, separate opacity and image adjustments: model, rendering and PDF output."""
import base64
from copy import deepcopy
from io import BytesIO
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / '.deps'), str(ROOT)]
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas

from studio.document_io import export_collection, import_files, png_data, render_page
from studio.model import ImageBox, Paragraph, Project, Run, Style, TextBox


def pixels(page, assets):
    return np.asarray(Image.open(BytesIO(png_data(render_page(page, assets[page.asset])))).convert('RGB'), np.int16)


class DesignFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from studio.agent_cli import load_fonts
        load_fonts([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'qa', prefix='design-')
        self.work = Path(self.temp.name)
        source = self.work / 'blank.pdf'
        canvas = Canvas(str(source), pagesize=(360, 288))
        canvas.setFillColorRGB(1, 1, 1)
        canvas.rect(0, 0, 360, 288, fill=1, stroke=0)
        canvas.showPage()
        canvas.save()
        self.project, self.assets, _ = import_files([source])
        self.page = self.project.pages[0]

    def tearDown(self):
        self.temp.cleanup()

    def text(self, **effects):
        box = TextBox(x=100, y=200, width=700, height=200, fill='transparent',
                      paragraphs=[Paragraph([Run('한글 효과 시험', Style(size=40, color='#ffffff'))])])
        for key, value in effects.items():
            setattr(box, key, value)
        self.page.objects = [box]
        return box

    def test_new_fields_round_trip_and_are_validated(self):
        box = self.text(outline_width=4, outline_color='#112233', shadow_enabled=True, shadow_blur=6,
                        highlight='#ffee00', text_opacity=.7, fill_opacity=.3)
        box.paragraphs[0].runs[0].style.letter_spacing = 150
        image = ImageBox(x=10, y=10, width=100, height=100, image_data=self.png('#808080'),
                         brightness=20, contrast=-10, saturation=30, corner_radius=12,
                         border_color='#ff0000', border_width=3)
        self.page.objects.append(image)
        data = self.project.to_dict()
        self.assertEqual(data['version'], 13)
        loaded = Project.from_dict(data)
        self.assertEqual(loaded.to_dict(), data)
        for path, value in ((('objects', 0, 'outline_width'), 99), (('objects', 0, 'text_opacity'), 2),
                            (('objects', 0, 'highlight'), 'red'), (('objects', 1, 'brightness'), 300),
                            (('objects', 1, 'border_color'), 'blue'),
                            (('objects', 0, 'paragraphs', 0, 'runs', 0, 'style', 'letter_spacing'), 5000)):
            bad = deepcopy(data)
            target = bad['pages'][0]
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(ValueError):
                Project.from_dict(bad)
        # Projects saved before these fields existed still open.
        old = deepcopy(data)
        old['version'] = 12
        for obj in old['pages'][0]['objects']:
            for key in ('text_opacity', 'fill_opacity', 'highlight', 'outline_color', 'outline_width', 'shadow_enabled',
                        'shadow_color', 'shadow_opacity', 'shadow_dx', 'shadow_dy', 'shadow_blur', 'brightness',
                        'contrast', 'saturation', 'corner_radius', 'border_color', 'border_width'):
                obj.pop(key, None)
        old['pages'][0]['objects'][0]['paragraphs'][0]['runs'][0]['style'].pop('letter_spacing')
        self.assertEqual(Project.from_dict(old).pages[0].objects[0].outline_width, 0)

    def png(self, color, size=(80, 60)):
        encoded = BytesIO()
        Image.new('RGB', size, color).save(encoded, 'PNG')
        return base64.b64encode(encoded.getvalue()).decode()

    def test_outline_shadow_and_highlight_render_under_the_text(self):
        self.text()
        plain = pixels(self.page, self.assets)
        self.text(outline_width=4, outline_color='#ff0000')
        outlined = pixels(self.page, self.assets)
        red = (outlined[..., 0] > 200) & (outlined[..., 1] < 80) & (outlined[..., 2] < 80)
        self.assertGreater(red.sum(), 500)
        # White letters stay on top of their outline: glyph interiors remain white.
        from PIL import ImageFilter
        white = Image.fromarray(((plain.min(axis=2) > 250)*255).astype(np.uint8)).filter(ImageFilter.MinFilter(5))
        interior = np.asarray(white) > 0
        self.assertGreater(interior.sum(), 200)
        self.assertGreater((outlined[interior].min(axis=1) > 240).mean(), .98)
        self.text(shadow_enabled=True, shadow_color='#0000ff', shadow_opacity=1, shadow_dx=12, shadow_dy=12)
        shadow = pixels(self.page, self.assets)
        blue = (shadow[..., 2] > 200) & (shadow[..., 0] < 80)
        self.assertGreater(blue.sum(), 500)
        self.text(shadow_enabled=True, shadow_color='#0000ff', shadow_opacity=1, shadow_blur=8)
        soft = pixels(self.page, self.assets)
        self.assertGreater(((soft[..., 2] > 60) & (soft[..., 0] < 200)).sum(), blue.sum())
        self.text(highlight='#00ff00')
        marked = pixels(self.page, self.assets)
        self.assertGreater(((marked[..., 1] > 200) & (marked[..., 0] < 80)).sum(), 5000)

    def test_text_and_background_opacity_are_separate(self):
        self.text(fill='#000000', fill_opacity=.5)
        half = pixels(self.page, self.assets)
        self.assertTrue(110 < half[300, 140, 0] < 145, half[300, 140])
        text = half[200:400, 100:800]
        self.assertGreater((text.min(axis=2) > 250).sum(), 200)
        self.text(fill='#000000', text_opacity=0)
        hidden = pixels(self.page, self.assets)[200:400, 100:800]
        self.assertEqual(int((hidden.min(axis=2) > 250).sum()), 0)

    def test_letter_spacing_widens_horizontal_and_vertical_text(self):
        def ink(box):
            image = pixels(self.page, self.assets)
            ys, xs = np.nonzero(image.max(axis=2) < 200)
            return xs.max()-xs.min(), ys.max()-ys.min()
        for vertical in (False, True):
            with self.subTest(vertical=vertical):
                widths = []
                for spacing in (0, 300):
                    box = self.text()
                    box.writing_mode = 'vertical-rl' if vertical else 'horizontal'
                    box.width, box.height = (200, 700) if vertical else (700, 200)
                    run = box.paragraphs[0].runs[0]
                    run.style.color, run.style.letter_spacing = '#000000', spacing
                    widths.append(ink(box)[1 if vertical else 0])
                self.assertGreater(widths[1], widths[0]*1.15)

    def test_image_adjustments_corners_and_border(self):
        image = ImageBox(x=200, y=200, width=400, height=300, image_data=self.png('#808080'), aspect_locked=False)
        self.page.objects = [image]
        base = pixels(self.page, self.assets)[350, 400]
        image.brightness = 50
        self.assertGreater(pixels(self.page, self.assets)[350, 400, 0], base[0]+30)
        image.brightness, image.corner_radius = 0, 80
        corner = pixels(self.page, self.assets)
        self.assertEqual(tuple(corner[203, 203]), (255, 255, 255))
        self.assertEqual(tuple(corner[350, 400]), tuple(base))
        image.corner_radius, image.border_width, image.border_color = 0, 10, '#ff0000'
        framed = pixels(self.page, self.assets)
        self.assertGreater(framed[203, 400, 0], 200)
        self.assertLess(framed[203, 400, 1], 60)

    def test_effects_stay_real_text_in_pdf_text_mode(self):
        for vertical in (False, True):
            for blur in (0, 6):
                with self.subTest(vertical=vertical, blur=blur):
                    box = self.text(outline_width=3, outline_color='#202020', shadow_enabled=True,
                                    shadow_blur=blur, highlight='#ffe08a', fill='#335577', fill_opacity=.6)
                    box.paragraphs[0].runs[0].style.letter_spacing = 120
                    if vertical:
                        box.writing_mode, box.width, box.height = 'vertical-rl', 200, 700
                    output = self.work / f'effects-{vertical}-{blur}.pdf'
                    report = {}
                    export_collection(self.project, self.assets, [0], output, 'pdf', report=report)
                    self.assertEqual(report['image_text_pages'], [])
                    text = ''.join(PdfReader(output).pages[0].extract_text().split())
                    self.assertIn('효과', text)


if __name__ == '__main__':
    unittest.main()
