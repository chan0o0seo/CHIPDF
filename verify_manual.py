"""Native Windows QA for manual PDF sentence selection and brush restoration.

Uses generated documents only. OCR and translation run through the real editor
workers and local engines; no engine output is mocked or corrected by the test.
"""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / '.deps'), str(ROOT)]
os.environ['QT_QPA_PLATFORM'] = 'windows'

from copy import deepcopy
import hashlib
from io import BytesIO
import json
import math
import time
import uuid

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas as PdfCanvas
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QFont, QImage, QInputMethodEvent, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from studio.document_io import png_data, render_page
from studio.model import TextBox
from studio.storage import load_bundle
from studio.window import Editor
from studio import __version__


def digest(data):
    return hashlib.sha256(data).hexdigest()


def rgba(image):
    converted = image.convertToFormat(QImage.Format_RGBA8888)
    return bytes(converted.constBits())


def pil(image):
    return Image.open(BytesIO(png_data(image))).convert('RGBA')


def main():
    QApplication.setAttribute(Qt.AA_Use96Dpi)
    app = QApplication([])
    assert app.platformName() == 'windows', 'A native Windows Qt session is required.'
    app.setFont(QFont('맑은 고딕', 10))
    out = ROOT / 'qa' / 'manual-08'
    run = out / ('run-' + uuid.uuid4().hex[:8])
    run.mkdir(parents=True)
    checks, timings = [], {}
    editor = Editor(run / 'data')
    report = {'app_version': __version__, 'platform': app.platformName(),
              'run': str(run.relative_to(ROOT)), 'checks': checks, 'timings': timings}

    def check(condition, label):
        assert condition, label
        checks.append(label)
        print('PASS: ' + label, flush=True)

    def pump(seconds=.12):
        until = time.perf_counter() + seconds
        while time.perf_counter() < until:
            app.processEvents()
            time.sleep(.008)
        app.processEvents()

    def wait_jobs(label, timeout=150):
        start = time.perf_counter()
        pump(.03)
        while editor.job or editor.io_job or editor.pending_ocr or editor.translation_after_ocr:
            app.processEvents()
            time.sleep(.01)  # Release the GIL so the Python worker can run.
            if time.perf_counter() - start > timeout:
                editor.cancel_job()
                raise TimeoutError(label + ': ' + editor.status.text())
        pump(.15)
        timings[label] = round(time.perf_counter()-start, 3)
        check(not editor.last_error, label + ' worker completed without errors')

    def screen_point(x, y):
        return editor.canvas.mapFromScene(QPointF(x, y))

    def drag(points):
        viewport = editor.canvas.viewport()
        positions = [screen_point(x, y) for x, y in points]
        check(all(viewport.rect().contains(p) for p in positions), 'gesture endpoints are visible')
        QTest.mouseMove(viewport, positions[0], 10)
        QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, positions[0], 10)
        for position in positions[1:]:
            QTest.mouseMove(viewport, position, 15)
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, positions[-1], 10)
        app.processEvents()
        return positions

    def action_click(action, toolbar):
        widget = toolbar.widgetForAction(action)
        if widget and widget.isVisible():
            QTest.mouseClick(widget, Qt.LeftButton)
        else:
            # Qt places excess toolbar actions in its overflow menu on small
            # displays; triggering that same action avoids monitor-size coupling.
            action.trigger()
        app.processEvents()

    def capture(name):
        pump()
        check(editor.grab().save(str(run / name)), 'native capture ' + name)

    try:
        background = (243, 235, 215)
        source = Image.new('RGB', (1000, 700), background)
        draw = ImageDraw.Draw(source)
        fonts = Path(os.environ['WINDIR']) / 'Fonts'
        font_path = next(path for name in ('meiryo.ttc', 'YuGothR.ttc', 'msgothic.ttc')
                         if (path := fonts / name).is_file())
        font = ImageFont.truetype(str(font_path), 36)
        japanese = '鍵は机の上にあります。'
        draw.text((80, 90), japanese, fill=(24, 24, 24), font=font, anchor='lt')
        draw.ellipse((639, 379, 661, 401), fill=(25, 25, 25))
        draw.rectangle((850, 520, 900, 560), fill=(33, 105, 135))
        source_png = run / 'source.png'
        source.save(source_png)
        source_pdf = run / 'source.pdf'
        pdf = PdfCanvas(str(source_pdf), pagesize=(360, 252), pageCompression=1)
        pdf.drawImage(ImageReader(source), 0, 0, 360, 252)
        pdf.showPage()
        pdf.save()
        file_hashes = {str(path.relative_to(ROOT)): digest(path.read_bytes()) for path in (source_png, source_pdf)}

        editor.show()
        editor.load_path(source_pdf)
        pump(.5)
        editor.canvas.fit_page()
        pump()
        check(not editor.auto_ocr and not editor.job and not editor.current_page.objects,
              'opening a PDF does not run automatic paragraph OCR')
        check(editor.canvas.tool == 'ocr', 'new PDF opens in manual sentence selection mode')
        check((editor.image.width(), editor.image.height()) == (1000, 700), 'PDF imports at the expected page size')
        original_pixels = rgba(editor.image)
        originals = {name: digest(data) for name, data in editor.assets.items()}
        capture('01-open-pdf.png')

        # Reverse rectangle direction exercises normalization at the current
        # fitted zoom, instead of bypassing the canvas with a backend call.
        upper_left, lower_right = screen_point(60, 70), screen_point(800, 160)
        scene_a = editor.canvas.mapToScene(upper_left)
        scene_b = editor.canvas.mapToScene(lower_right)
        expected = [math.floor(scene_a.x()), math.floor(scene_a.y()),
                    math.ceil(scene_b.x())-math.floor(scene_a.x()),
                    math.ceil(scene_b.y())-math.floor(scene_a.y())]
        drag([(800, 160), (430, 115), (60, 70)])
        wait_jobs('rectangle_ocr')
        check(len(editor.current_page.objects) == 1, 'one rectangle creates one text box')
        obj = editor.current_page.objects[0]
        check(isinstance(obj, TextBox) and obj.source_rect == expected, 'text box uses the dragged bounds at fitted zoom')
        check(obj.source_text.strip() and '机' in obj.source_text and 'あります' in obj.source_text,
              'real Japanese OCR reads the selected sentence')
        check(obj.text == '' and obj.erase_when_empty and bool(obj.erase_patch),
              'OCR creates an empty Korean box with immediate source erasure')
        check(editor.source_text.toPlainText() == obj.source_text, 'recognized Japanese is displayed separately')
        check(editor.editing_item() is not None, 'new text box accepts typing immediately')
        editor.finish_edit()
        editor.refresh_background()
        blank_background = pil(editor.background_image)
        x, y, width, height = obj.source_rect
        crop = blank_background.crop((x+2, y+2, x+width-2, y+height-2))
        check(all(abs(channel-background[i]) <= 2 for pixel in crop.getdata() for i, channel in enumerate(pixel[:3])),
              'selected Japanese is replaced by the surrounding paper color before typing')
        empty_export = render_page(deepcopy(editor.current_page), editor.original)
        check(rgba(empty_export) == rgba(editor.background_image), 'empty-box export includes the visible restoration')
        source_text = obj.source_text
        object_id = obj.id
        capture('02-blank-box.png')

        action_click(editor.translate_action, editor.main_toolbar)
        wait_jobs('local_translation')
        obj = editor.items_by_id[object_id].model
        check(bool(obj.text.strip()) and any('\uac00' <= ch <= '\ud7a3' for ch in obj.text),
              'translation button generates Korean through the actual local engine')
        machine_target = obj.text
        item = editor.items_by_id[object_id]
        item.begin_edit()
        cursor = item.textCursor()
        cursor.select(QTextCursor.Document)
        item.setTextCursor(cursor)
        event = QInputMethodEvent()
        event.setCommitString('열쇠는 책상 위에 있습니다.')
        app.sendEvent(editor.scene, event)
        editor.finish_edit()
        corrected = editor.items_by_id[object_id].model.text
        check(corrected == '열쇠는 책상 위에 있습니다.', 'Korean IME commit edits the rectangle text box')
        action_click(editor.translate_action, editor.main_toolbar)
        wait_jobs('translation_candidate')
        obj = editor.items_by_id[object_id].model
        check(obj.text == corrected and bool(obj.candidate_text), 'translation preserves typed Korean and presents a candidate')
        capture('03-translated.png')

        editor.source_dock.hide()
        editor.set_canvas_tool('brush')
        editor.brush_size_box.setValue(42)
        editor.canvas.fit_page()
        pump()
        # A further zoom change proves brush diameter and stroke locations use
        # page coordinates, rather than screen pixels.
        editor.canvas.zoom(.9)
        pump()
        before_brush = editor.project.to_dict()
        before_pixels = rgba(editor.render_image())
        before_background = rgba(editor.background_image)
        drag([(625, 390), (642, 390), (658, 390), (675, 390)])
        check(not editor.canvas.brush_mask_image().isNull() and editor.apply_erase_action.isEnabled(),
              'brush stroke creates a pending selection and enables Erase')
        check(editor.project.to_dict() == before_brush and rgba(editor.render_image()) == before_pixels,
              'brush selection changes neither the document nor exported pixels before Erase')
        mask = pil(editor.canvas.brush_mask_image()).convert('L')
        check(mask.getpixel((650, 390)) == 255 and mask.getpixel((650, 420)) == 0,
              'brush mask follows page coordinates and diameter after zoom')
        capture('04-brush-pending.png')
        action_click(editor.apply_erase_action, editor.region_bar)
        wait_jobs('brush_erase')
        check(len(editor.current_page.background_patches) == 1 and editor.canvas.brush_mask_image().isNull(),
              'Erase applies one page repair and clears the pending selection')
        repaired_background = pil(editor.background_image)
        check(all(abs(repaired_background.getpixel((650, 390))[i]-background[i]) <= 2 for i in range(3)),
              'brush repair removes the black mark and restores paper immediately')
        before_image = Image.frombytes('RGBA', (1000, 700), before_background)
        check(all(old == new for old, new, selected in zip(before_image.getdata(), repaired_background.getdata(), mask.getdata()) if not selected),
              'brush repair leaves every pixel outside the painted mask unchanged')
        after_brush = editor.project.to_dict()
        after_pixels = rgba(editor.render_image())
        check(after_pixels != before_pixels, 'applied brush repair appears in document rendering')
        editor.undo_stack.undo()
        pump()
        check(editor.project.to_dict() == before_brush and rgba(editor.render_image()) == before_pixels,
              'undo restores the document and pixels before brush erasure')
        editor.undo_stack.redo()
        pump()
        check(editor.project.to_dict() == after_brush and rgba(editor.render_image()) == after_pixels,
              'redo restores the exact applied brush repair')

        editor.compare_action.trigger()
        pump()
        check(editor.comparing and rgba(editor.background_item.pixmap().toImage()) == original_pixels,
              'original comparison displays the untouched imported PDF')
        editor.compare_action.trigger()
        pump()
        check(not editor.comparing and rgba(editor.render_image()) == after_pixels,
              'leaving original comparison restores edited output')
        editor.set_canvas_tool('brush')
        pump()
        pending_snapshot = editor.project.to_dict()
        drag([(865, 535), (880, 545)])
        QTest.keyClick(editor.canvas.viewport(), Qt.Key_Escape)
        pump()
        check(editor.canvas.tool == 'select' and editor.canvas.brush_mask_image().isNull()
              and editor.project.to_dict() == pending_snapshot,
              'Escape discards an unapplied brush selection without document changes')

        project_file = run / 'manual.twproj'
        first_png = run / 'edited.png'
        output_pdf = run / 'edited.pdf'
        editor.save_to(project_file)
        editor.export_to(first_png)
        editor.export_pages(output_pdf, [0], 'pdf')
        first_png_bytes = first_png.read_bytes()
        saved, assets = load_bundle(project_file)
        check(saved.version == 8 and len(saved.pages[0].background_patches) == 1,
              'project schema 8 persists the independent background repair')
        check({name: digest(data) for name, data in assets.items()} == originals,
              'saved project preserves all original page asset bytes')
        pdf_reader = PdfReader(output_pdf)
        pdf_image = pdf_reader.pages[0].images[0].image.convert('RGBA')
        png_image = Image.open(BytesIO(first_png_bytes)).convert('RGBA')
        check(pdf_image.size == png_image.size and pdf_image.tobytes() == png_image.tobytes(),
              'PDF embeds exactly the same page pixels as PNG export')
        check(tuple(float(v) for v in pdf_reader.pages[0].mediabox[2:]) == (360., 252.),
              'PDF output preserves original physical page dimensions')
        editor.load_path(project_file)
        pump()
        second_png = run / 'reopened.png'
        editor.export_to(second_png)
        check(second_png.read_bytes() == first_png_bytes and rgba(editor.render_image()) == after_pixels,
              'save and reopen preserve exact PNG bytes and native page pixels')
        check(all(digest((ROOT / path).read_bytes()) == value for path, value in file_hashes.items()),
              'generated source PNG and PDF remain unchanged')
        editor.source_dock.hide()
        editor.canvas.fit_page()
        capture('05-complete.png')
        report.update({'passed': True, 'project_version': saved.version,
                       'project': str(project_file.relative_to(ROOT)),
                       'png': str(first_png.relative_to(ROOT)), 'pdf': str(output_pdf.relative_to(ROOT)),
                       'png_sha256': digest(first_png_bytes), 'original_files': file_hashes,
                       'original_assets': originals, 'ocr_source': source_text,
                       'expected_source': japanese, 'machine_target': machine_target,
                       'typed_target': corrected, 'rect': expected,
                       'page_size': [1000, 700], 'pdf_size_pt': [360, 252]})
        (run / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
        print(json.dumps({'passed': True, 'checks': len(checks), 'result': str(out / 'result.json'),
                          'timings': timings}, ensure_ascii=True), flush=True)
        return 0
    except Exception as exc:
        report.update({'passed': False, 'error': repr(exc), 'status': editor.status.text()})
        editor.grab().save(str(run / 'failure.png'))
        (run / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
        print(json.dumps(report, ensure_ascii=True, indent=2), flush=True)
        raise
    finally:
        editor.cancel_job()
        editor.pool.waitForDone(10000)
        editor.io_pool.waitForDone(10000)
        editor.dirty = False
        editor.close()
        editor.deleteLater()
        app.clipboard().clear()
        app.processEvents()


if __name__ == '__main__':
    raise SystemExit(main())
