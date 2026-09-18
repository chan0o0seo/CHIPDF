"""Verify the frozen app imports and exports internal links without the source PDF."""
from pathlib import Path
import json
import os
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT/'.deps'), str(ROOT)]
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas
from PIL import Image, ImageDraw

from studio.document_io import import_files
from studio.model import Paragraph, Run, Style, TextBox
from studio.recognition import native_background_patch
from studio.storage import save_project


def verify():
    app = QApplication.instance() or QApplication([])
    build = json.loads((ROOT/'latest-build.json').read_text('utf-8'))
    output = ROOT/'qa'/('pdf-links-'+build['id']+'-'+uuid.uuid4().hex[:6])
    output.mkdir(parents=True, exist_ok=True)
    source = output/'source.pdf'
    canvas = Canvas(str(source), pagesize=(300, 400))
    for index in range(3):
        canvas.bookmarkPage(f'p{index}')
        canvas.drawString(20, 370, f'PAGE {index+1}')
        if index == 0:
            canvas.drawString(20, 310, 'GO TO PAGE 3')
            canvas.linkRect('', 'p2', (20, 300, 200, 330), relative=0)
        elif index == 2:
            canvas.drawString(20, 310, 'BACK TO PAGE 1')
            canvas.linkRect('', 'p0', (20, 300, 200, 330), relative=0)
        canvas.showPage()
    canvas.save()
    project, assets, _ = import_files([source])
    page = project.pages[0]
    rect = page.pdf_links[0]['rect']
    box = TextBox(x=rect[0]+60, y=rect[1]+100, width=450, height=90,
                  source_rect=rect, erase_when_empty=True,
                  paragraphs=[Paragraph([Run('3페이지로 이동합니다', Style(size=26, color='#175bb5', underline=True))])])
    selection = Image.new('L', (page.width, page.height))
    x, y, w, h = rect
    ImageDraw.Draw(selection).rectangle((x, y, x+w-1, y+h-1), fill=255)
    box.erase_patch, box.erase_mask, box.erase_rect = native_background_patch(assets[page.asset], assets[page.clean_asset], selection)
    page.objects = [box]
    project_file = output/'translated.twproj'
    save_project(project_file, project, assets)
    env = os.environ.copy()
    # Native Windows rendering uses the installed Korean fonts; Qt's offscreen
    # platform has a separate font backend and can render fallback squares.
    for key in ('PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QT_QPA_PLATFORM'):
        env.pop(key, None)
    env['PATH'] = os.pathsep.join([str(Path(os.environ['SystemRoot'])/'System32'), os.environ['SystemRoot']])

    def run(file, name):
        result_dir = output/(name+'-native')
        if result_dir.exists():
            result_dir = output/(name+'-native-'+uuid.uuid4().hex[:6])
        process = subprocess.run([build['exe'], str(file), '--data-dir', str(output/'data'),
                                  '--smoke-dir', str(result_dir), '--smoke-collection'],
                                 env=env, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
        assert process.returncode == 0, f'Frozen app failed: {process.returncode}, logs: {result_dir}'
        assert (result_dir/'ok.txt').exists()
        reader = PdfReader(result_dir/'output.pdf')
        assert len(reader.pages) == 3
        first = reader.pages[0]['/Annots'][0].get_object()
        assert first['/Dest'][0] == reader.pages[2].indirect_reference
        assert reader.pages[2]['/Annots'][0].get_object()['/Dest'][0] == reader.pages[0].indirect_reference
        assert len(reader.pages[0]['/Annots']) == 1
        return first

    run(source, 'import')
    # Only rename our generated fixture, proving the saved project is self-contained.
    source.rename(output/'source-unavailable.pdf')
    annotation = run(project_file, 'translated')
    assert abs(float(annotation['/Rect'][0])-box.x*300/page.width) < .01
    report = {'version': build['version'], 'packaged_import': True, 'packaged_project_reopen': True,
              'forward_and_backward_links': True, 'moved_korean_box_hotspot': True,
              'source_pdf_unavailable': True, 'directory': str(output)}
    (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__':
    verify()
