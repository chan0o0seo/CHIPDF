"""Native Qt QA of original PDF backgrounds on retained real-material samples."""
from pathlib import Path
import os, sys
ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT/'.deps'), str(ROOT)]
os.environ['QT_QPA_PLATFORM'] = 'windows'
from contextlib import closing
from copy import deepcopy
from io import BytesIO
import hashlib, json, time, uuid
from unittest.mock import patch
from PIL import Image, ImageChops
import pypdfium2 as pdfium
import pypdfium2.raw as raw
from pypdf import PdfReader
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QFont, QImage, QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from studio.window import Editor
from studio.document_io import png_data
from studio.storage import load_bundle
from studio import __version__


def main():
    base = ROOT/'qa/pdf-background-081'
    comparison = json.loads((base/'real-result.json').read_text('utf-8'))
    assert all(page['legacy_identical'] for page in comparison['pages'])
    sample = ROOT/comparison['input']
    before = sample.read_bytes()
    out = base/('native-'+uuid.uuid4().hex[:8]); out.mkdir()
    QApplication.setAttribute(Qt.AA_Use96Dpi)
    app = QApplication([]); app.setFont(QFont('맑은 고딕', 10))
    editor = Editor(out/'data'); editor.show()
    checks=[]; ocr_sources=[]
    def check(value, description):
        assert value, description
        checks.append(description)
        print('PASS '+description, flush=True)
    def pump(duration=.12):
        end=time.monotonic()+duration
        while time.monotonic()<end:
            app.processEvents(); time.sleep(.005)
    def wait():
        end=time.monotonic()+90
        while editor.job:
            pump(.02)
            assert time.monotonic()<end, 'worker timeout'
        pump()
        check(not editor.last_error, 'native background worker completed')
    def pil(image):
        return Image.open(BytesIO(png_data(image))).convert('RGBA')
    def drag(a,b):
        view=editor.canvas
        p,q=[view.mapFromScene(QPointF(*point)) for point in (a,b)]
        check(view.viewport().rect().contains(p) and view.viewport().rect().contains(q),'drag endpoints visible')
        QTest.mousePress(view.viewport(),Qt.LeftButton,Qt.NoModifier,p)
        QTest.mouseMove(view.viewport(),q,20)
        QTest.mouseRelease(view.viewport(),Qt.LeftButton,Qt.NoModifier,q)
        pump(.02)
    try:
        editor.load_path(sample); pump(.5)
        check(len(editor.project.pages)==4 and all(p.clean_asset for p in editor.project.pages),'all four real PDF pages retain native backgrounds')
        with pdfium.PdfDocument(sample) as doc:
            for index in range(4):
                editor.switch_page(index); pump()
                editor.set_canvas_tool('ocr'); pump()
                with closing(doc[index]) as page:
                    candidates=[o.get_bounds() for o in page.get_objects(filter=[raw.FPDF_PAGEOBJ_TEXT])]
                    left,bottom,right,top=next(b for b in candidates if b[2]-b[0]>45 and b[3]-b[1]>6)
                    w,h=page.get_size(); scale=200/72
                    x0,y0=max(0,left*scale-6),max(0,(h-top)*scale-6)
                    x1,y1=min(editor.image.width(),right*scale+6),min(editor.image.height(),(h-bottom)*scale+6)
                original=pil(editor.image)
                clean=Image.open(BytesIO(editor.assets[editor.current_page.clean_asset])).convert('RGBA')
                with patch('studio.recognition.restore_mask',side_effect=AssertionError('native text must not inpaint')):
                    drag((x1,y1),(x0,y0)); wait()
                obj=editor.current_page.objects[0]
                ocr_sources.append(obj.source_text)
                check(not obj.text and obj.erase_when_empty,'OCR creates an empty Korean editing box')
                editor.finish_edit(); editor.refresh_background()
                x,y,bw,bh=map(int,obj.source_rect)
                expected=original.copy(); expected.paste(clean.crop((x,y,x+bw,y+bh)),(x,y))
                check(pil(editor.background_image).tobytes()==expected.tobytes(),'rectangle output equals the true PDF background exactly')
                check(ImageChops.difference(original,expected).convert('RGB').getbbox() is not None,'Japanese text actually disappeared')
                item=editor.items_by_id[obj.id]; item.begin_edit()
                event=QInputMethodEvent(); event.setCommitString('한국어 번역문')
                app.sendEvent(editor.scene,event); editor.finish_edit()
                check(obj.text=='한국어 번역문','Korean text remains editable over original background')
        # Pick an untouched native glyph pixel on the last page for brush QA.
        original=pil(editor.image); clean=Image.open(BytesIO(editor.assets[editor.current_page.clean_asset])).convert('RGBA')
        diff=ImageChops.difference(pil(editor.background_image),clean).convert('RGB')
        bx0,by0,bx1,by1=diff.getbbox()
        point=next((x,y) for y in range(by0,by1) for x in range(bx0,bx1) if diff.getpixel((x,y))!=(0,0,0))
        editor.set_canvas_tool('brush'); editor.canvas.set_brush_size(48); pump()
        before_brush=pil(editor.background_image)
        drag(point,point)
        mask=pil(editor.canvas.brush_mask_image()).convert('L')
        with patch('studio.recognition.restore_mask',side_effect=AssertionError('native brush must not inpaint')):
            editor.apply_brush_erase(); wait()
        expected=before_brush.copy(); expected.paste(clean,(0,0),mask)
        check(pil(editor.background_image).tobytes()==expected.tobytes(),'brush retains exact background pixels and untouched surroundings')
        editor.undo(); check(pil(editor.background_image).tobytes()==before_brush.tobytes(),'brush undo restores previous pixels')
        editor.redo(); check(pil(editor.background_image).tobytes()==expected.tobytes(),'brush redo restores exact background')
        editor.save_to(out/'native.twproj')
        editor.export_pages(out/'pages',range(4),'png')
        editor.export_pages(out/'native.pdf',range(4),'pdf')
        hashes=[hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((out/'pages').glob('*.png'))]
        pdf=PdfReader(out/'native.pdf')
        for i,path in enumerate(sorted((out/'pages').glob('*.png'))):
            check(pdf.pages[i].images[0].image.convert('RGB').tobytes()==Image.open(path).convert('RGB').tobytes(),'PDF and PNG pixels match')
        editor.load_path(out/'native.twproj'); pump()
        editor.export_pages(out/'reopened',range(4),'png')
        check(hashes==[hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((out/'reopened').glob('*.png'))],'save and reopen preserve all page pixels')
        saved,assets=load_bundle(out/'native.twproj')
        check(saved.version==8 and len(assets)==8,'all original and native background assets saved in schema 8')
        check(sample.read_bytes()==before,'source PDF remains unchanged')
        editor.grab().save(str(out/'window.png'))
        report={'version':__version__,'passed':True,'checks':checks,'ocr_sources':ocr_sources,'project':str((out/'native.twproj').relative_to(ROOT)),
                'png_hashes':hashes,'original_assets':{key:hashlib.sha256(data).hexdigest() for key,data in assets.items()},
                'native_comparison':comparison,'window':str((out/'window.png').relative_to(ROOT))}
        (base/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps({'passed':True,'checks':len(checks),'run':str(out)},ensure_ascii=True))
    finally:
        editor.dirty=False; editor.close(); app.processEvents()


if __name__=='__main__':
    main()
