"""Actual 2 PDFs + 10 card images: native UI, independent page export and roundtrip."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / '.deps'), str(ROOT)]
from copy import deepcopy
import hashlib
import json
import shutil
import time
import uuid
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QDialog
from studio.window import Editor
from studio.model import TextBox, Paragraph, Run, Style
from studio.document_io import folder_images, png_data, render_page

QApplication.setAttribute(Qt.AA_Use96Dpi)
app = QApplication([])
app.setFont(QFont('맑은 고딕', 10))
out = ROOT / 'qa' / 'collection-05'
out.mkdir(parents=True, exist_ok=True)
run = out / ('run-'+uuid.uuid4().hex[:8])
run.mkdir()
workspace = ROOT.parent.parent
pdfs = [workspace/'0.ST資料'/'1.ST_事前準備.pdf', workspace/'1.HO'/'PC1.シュウ'/'シュウ.pdf']
cards = folder_images(Path('C:/Users/User/Downloads/フラジャイル_ウェイト_20260822更新/20260802_フラジャイル・ウェイト/04_配布画像_png'))[:10]
sources = pdfs+cards
digests = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
editor = Editor(out/'data', auto_ocr=False)
editor.show()
editor.open_sources(sources)
deadline = time.monotonic()+120
while editor.io_job:
    app.processEvents()
    time.sleep(.01)
    assert time.monotonic() < deadline, 'Import timeout'
assert editor.project and len(editor.project.pages) == 27
print('Imported 27 pages from 2 PDFs and 10 cards', flush=True)
# Add a small explicit QA label to each PDF's first page and the first card.
for index in (0, 11, 17):
    editor.switch_page(index)
    page = editor.current_page
    label = editor.add_object(TextBox(width=min(600, page.width-40), height=48,
        fill='#ffffff', margin=6, paragraphs=[Paragraph([Run(f'편집 검증 · 카드 {index+1:02d}', Style(size=16, color='#286a60', bold=True))])]), '한글 검증')
    label.x, label.y = 20, page.height-68
    editor.rebuild_scene([label.id])
    editor.begin_operation()
    editor.finish_operation('검증 배치')
editor.save_to(out/'작품.twproj')
expected = [hashlib.sha256(png_data(render_page(deepcopy(p), editor.assets[p.asset]))).hexdigest() for p in editor.project.pages]
editor.export_pages(run/'pages', range(27), 'png', progress=lambda n: print(f'PNG {n}/27', flush=True) if n%5 == 0 else None)
editor.export_pages(run/'작품.pdf', range(27), 'pdf', progress=lambda n: print(f'PDF {n}/27', flush=True) if n%5 == 0 else None)
editor.load_path(out/'작품.twproj')
for index, page in enumerate(editor.project.pages):
    editor.switch_page(index)
    assert hashlib.sha256(png_data(editor.render_image())).hexdigest() == expected[index]
for path, digest in zip(sorted((run/'pages').glob('*.png')), expected):
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in digests.items())
editor.switch_page(0)
app.processEvents()
editor.canvas.fit_page()
editor.grab().save(str(out/'pdf-window.png'))
editor.switch_page(17)
editor.card_list.scrollToItem(editor.card_list.item(17))
app.processEvents()
editor.canvas.fit_page()
editor.grab().save(str(out/'cards-window.png'))
def capture_dialog():
    dialog = app.activeModalWidget()
    assert isinstance(dialog, QDialog)
    dialog.grab().save(str(out/'export-dialog.png'))
    dialog.reject()
QTimer.singleShot(150, capture_dialog)
editor.choose_collection_export()
shutil.copy2(pdfs[1], out/'native-input.pdf')
report = {'pages': 27, 'pdf_inputs': 2, 'pdf_pages': 17, 'image_inputs': 10,
          'roundtrip_all_png_identical': True, 'batch_png_identical': True, 'all_sources_unchanged': True,
          'pdf': str(run/'작품.pdf'), 'png_folder': str(run/'pages'), 'project': str(out/'작품.twproj'),
          'page_png_sha256': expected, 'physical_sizes': [[p.width_pt,p.height_pt] for p in editor.project.pages],
          'source_sha256': digests}
(out/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in ('page_png_sha256','physical_sizes','source_sha256')}, ensure_ascii=True), flush=True)
editor.close()
