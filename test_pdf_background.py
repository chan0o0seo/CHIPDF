"""Pixel-level checks of native PDF text removal over real graphic content."""
from contextlib import closing
import ctypes
from io import BytesIO
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / '.deps'), str(ROOT)]

from PIL import Image, ImageDraw
import pypdfium2 as pdfium
import pypdfium2.raw as raw
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen.canvas import Canvas

from studio.pdf_background import render_without_text


def make_pdf(text=True, form_depth=2, render_mode=0):
    output = BytesIO()
    canvas = Canvas(output, pagesize=(360, 240), pageCompression=1)
    tile = Image.new('RGB', (120, 80))
    pixels = tile.load()
    for y in range(tile.height):
        for x in range(tile.width):
            pixels[x, y] = (50 + x, 90 + y, 170 + (x + y) % 70)
    draw = ImageDraw.Draw(tile)
    draw.line((0, 5, 119, 75), fill='#dffd65', width=5)
    canvas.drawImage(ImageReader(tile), 0, 0, 360, 240)
    canvas.setStrokeColorRGB(.25, .65, .95)
    canvas.setLineWidth(1.1)
    for x in range(0, 360, 13):
        canvas.line(x, 0, x, 240)
    canvas.setFillColorRGB(.91, .36, .14)
    canvas.circle(180, 120, 48, stroke=1, fill=1)
    pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))

    def draw_text(x, y):
        if text:
            canvas.saveState()
            canvas.setFillColorRGB(.05, .1, .16)
            obj = canvas.beginText(x, y)
            obj.setFont('HeiseiKakuGo-W5', 22)
            obj.setTextRenderMode(render_mode)
            obj.textLine('日本語の文章')
            canvas.drawText(obj)
            canvas.restoreState()

    draw_text(20, 190)
    if form_depth:
        for depth in range(form_depth):
            canvas.beginForm(f'form{depth}', 0, 0, 360, 240)
            if depth == 0:
                # This graphic shares the text's Form and must survive intact.
                canvas.setFillColorRGB(.3, .9, .4)
                canvas.rect(35, 52, 185, 25, stroke=0, fill=1)
                draw_text(45, 65)
            else:
                canvas.doForm(f'form{depth - 1}')
            canvas.endForm()
        canvas.doForm(f'form{form_depth - 1}')
    canvas.save()
    return output.getvalue()


def pixels(page, scale=1.37):
    with closing(page.render(scale=scale)) as bitmap:
        return bitmap.to_pil().convert('RGBA').tobytes()


class PdfBackgroundTests(unittest.TestCase):
    def test_nested_japanese_text_removed_preserving_image_and_vector_pixels(self):
        with pdfium.PdfDocument(make_pdf()) as source, pdfium.PdfDocument(make_pdf(False)) as expected:
            with closing(source[0]) as page, closing(expected[0]) as background:
                original = pixels(page)
                clean, count = render_without_text(page, 1.37)
                self.assertGreaterEqual(count, 2)
                self.assertEqual(Image.open(BytesIO(clean)).convert('RGBA').tobytes(), pixels(background))
                self.assertNotEqual(original, pixels(background))
                # Hidden flags are temporary; later imports see the original PDF.
                self.assertEqual(pixels(page), original)

    def test_rotation_and_crop_use_exact_original_geometry(self):
        with pdfium.PdfDocument(make_pdf()) as source, pdfium.PdfDocument(make_pdf(False)) as expected:
            with closing(source[0]) as page, closing(expected[0]) as background:
                for item in (page, background):
                    item.set_rotation(90)
                    item.set_cropbox(15, 12, 345, 225)
                clean, _ = render_without_text(page, 2.125)
                image = Image.open(BytesIO(clean)).convert('RGBA')
                with closing(page.render(scale=2.125)) as rendered:
                    self.assertEqual(image.size, rendered.to_pil().size)
                self.assertEqual(image.tobytes(), pixels(background, 2.125))

    def test_stroked_text_is_removed_without_touching_paths(self):
        for mode in (1, 2):
            with self.subTest(mode=mode), pdfium.PdfDocument(make_pdf(render_mode=mode)) as source, pdfium.PdfDocument(make_pdf(False)) as expected:
                with closing(source[0]) as page, closing(expected[0]) as background:
                    clean, _ = render_without_text(page, 1.37)
                    self.assertEqual(Image.open(BytesIO(clean)).convert('RGBA').tobytes(), pixels(background))

    def test_image_only_or_invisible_ocr_has_no_clean_asset(self):
        for data in (make_pdf(False), make_pdf(render_mode=3)):
            with pdfium.PdfDocument(data) as document, closing(document[0]) as page:
                original = pixels(page)
                self.assertIsNone(render_without_text(page, 1.37))
                self.assertEqual(pixels(page), original)

    def test_clipping_text_fails_closed_without_altering_page(self):
        for mode in (4, 5, 6, 7):
            with self.subTest(mode=mode), pdfium.PdfDocument(make_pdf(render_mode=mode)) as document, closing(document[0]) as page:
                original = pixels(page)
                self.assertIsNone(render_without_text(page, 1.37))
                self.assertEqual(pixels(page), original)

    def test_cancel_after_first_hidden_object_restores_page(self):
        with pdfium.PdfDocument(make_pdf()) as document, closing(document[0]) as page:
            original = pixels(page)
            hidden = []
            setter = raw.FPDFPageObj_SetIsActive

            def record(obj, active):
                result = setter(obj, active)
                if not active and result:
                    hidden.append(obj)
                return result

            with patch.object(raw, 'FPDFPageObj_SetIsActive', side_effect=record):
                with self.assertRaises(InterruptedError):
                    render_without_text(page, 1.37, cancelled=lambda: bool(hidden))
            self.assertTrue(hidden)
            self.assertEqual(pixels(page), original)

    def test_setter_failure_restores_any_already_hidden_text(self):
        with pdfium.PdfDocument(make_pdf()) as document, closing(document[0]) as page:
            original = pixels(page)
            setter = raw.FPDFPageObj_SetIsActive
            calls = 0

            def fail_second_hide(obj, active):
                nonlocal calls
                if not active:
                    calls += 1
                    if calls == 2:
                        return False
                return setter(obj, active)

            with patch.object(raw, 'FPDFPageObj_SetIsActive', side_effect=fail_second_hide):
                self.assertIsNone(render_without_text(page, 1.37))
            self.assertEqual(calls, 2)
            self.assertEqual(pixels(page), original)

    def test_render_failure_restores_page(self):
        with pdfium.PdfDocument(make_pdf()) as document, closing(document[0]) as page:
            original = pixels(page)
            with patch.object(page, 'render', side_effect=RuntimeError('failed rendering')):
                with self.assertRaisesRegex(RuntimeError, 'failed rendering'):
                    render_without_text(page, 1.37)
            self.assertEqual(pixels(page), original)

    def test_form_depth_and_object_limits_fail_closed(self):
        with pdfium.PdfDocument(make_pdf()) as document, closing(document[0]) as page:
            original = pixels(page)
            with patch('studio.pdf_background.MAX_FORM_DEPTH', 1):
                self.assertIsNone(render_without_text(page, 1.37))
            with patch('studio.pdf_background.MAX_OBJECTS', 1):
                self.assertIsNone(render_without_text(page, 1.37))
            self.assertEqual(pixels(page), original)

    def test_unknown_text_mode_is_unsupported(self):
        with pdfium.PdfDocument(make_pdf()) as document, closing(document[0]) as page:
            original = pixels(page)
            with patch.object(raw, 'FPDFTextObj_GetTextRenderMode', return_value=-1):
                self.assertIsNone(render_without_text(page, 1.37))
            self.assertEqual(pixels(page), original)

    def test_bitmap_bounds_and_scale_validation(self):
        with pdfium.PdfDocument(make_pdf()) as document, closing(document[0]) as page:
            self.assertIsNone(render_without_text(page, 1000))
            for value in (0, -1, float('nan'), float('inf')):
                with self.assertRaises(ValueError):
                    render_without_text(page, value)


if __name__ == '__main__':
    unittest.main()
