"""Native v0.6 QA: vertical IME editing, reusable styles/layouts and 3-card output."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / '.deps'), str(ROOT)]

from copy import deepcopy
import hashlib
import json
import uuid

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QInputMethodEvent, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QApplication, QDialog
from pypdf import PdfReader

from studio.document_io import png_data, render_page
from studio.model import GroupBox, Paragraph, Run, ShapeBox, Style, TextBox, uid
from studio.window import Editor

QApplication.setAttribute(Qt.AA_Use96Dpi)
app = QApplication([])
assert app.platformName() != 'offscreen', 'This check requires the native Windows platform.'
app.setFont(QFont('맑은 고딕', 10))
out = ROOT / 'qa' / 'vertical-06'
out.mkdir(parents=True, exist_ok=True)
run = out / ('run-' + uuid.uuid4().hex[:8])
run.mkdir()
source = ROOT / 'qa' / 'collection-05' / '작품.twproj'
source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
editor = Editor(out / 'data', auto_ocr=False)
editor.show()
editor.load_path(source)
# Save a separate copy before any fixture changes, leaving every earlier release intact.
editor.save_to(run / 'source-copy.twproj')
project = deepcopy(editor.project)
project.id, project.name = uid(), '세로쓰기와 서식 재사용 · 편집 검증'
project.pages = project.pages[17:20]
for index, page in enumerate(project.pages):
    page.name = f'세로 편집 예시 {index+1:02d}'
    page.objects = []
    page.ocr_done = True
assets = {page.asset: editor.assets[page.asset] for page in project.pages}
original_assets = {name: hashlib.sha256(data).hexdigest() for name, data in assets.items()}
editor.install_collection(project, assets)
editor.save_to(out / '작업.twproj')


def select(*ids):
    editor.scene.clearSelection()
    for key in ids:
        editor.items_by_id[key].setSelected(True)
    app.processEvents()


def capture(name):
    editor.source_dock.hide()
    editor.canvas.fit_page()
    app.processEvents()
    assert editor.grab().save(str(out / name))


def provenance(page):
    return {obj.id: deepcopy((obj.text, obj.source_text, obj.source_rect, obj.erase_rect,
                             obj.target_origin, obj.reviewed, obj.candidate_text,
                             obj.candidate_source, obj.erase_enabled))
            for obj in page.objects if isinstance(obj, TextBox)}


def add_at(obj, label):
    # The insert command places new objects in the card's center. Position them
    # through their graphics items, just as a subsequent canvas move would.
    x, y = obj.x, obj.y
    result = editor.add_object(obj, label)
    editor.begin_operation()
    editor.items_by_id[result.id].setPos(x, y)
    editor.finish_operation('검증 예시 배치')
    return result


body_ids, title_ids = [], []
sentences = [
    '닫힌 방에 「작은 열쇠」가 남았다。\n시계는 １２시를 가리킨다。\n그날의 기억을 차분히 확인해 보자。',
    '서랍 속에 「파란 편지」가 있었다。\n메모에는 ０３이라는 숫자가 적혀 있다。\n당신이 아는 사실을 함께 확인하자。',
    '정원에서 「붉은 리본」을 발견했다。\n발자국은 ２층 계단으로 이어졌다。\n기억과 증거를 나란히 놓고 살펴보자。',
]
for index, text in enumerate(sentences):
    editor.switch_page(index)
    page = editor.current_page
    add_at(ShapeBox(x=86, y=54, width=548, height=432,
                              fill='#fffdf7', stroke='#d9d1ba', stroke_width=1), '검증용 바탕')
    title = add_at(TextBox(x=118, y=72+index*3, width=478, height=48,
        margin=4, paragraphs=[Paragraph([Run(f'편집 예시 · 증거 카드 {index+1:02d}',
                Style(size=18, bold=True, color='#285c50'))])]), '제목')
    body = add_at(TextBox(x=155+index*18, y=136+index*12,
        width=436-index*20, height=318-index*12, margin=8,
        paragraphs=[Paragraph([Run(line, Style(size=18, color='#293d39'))],
                              line_spacing=1.2, space_after=5)
                    for line in text.split('\n')],
        source_text=f'検証用の原文 {index+1}', source_rect=[110, 140, 430, 310],
        erase_rect=[108, 138, 434, 314], target_origin='manual', reviewed=True,
        erase_enabled=False), '검증용 번역문')
    body_ids.append(body.id)
    title_ids.append(title.id)

# Direction is a single normal undo command and survives undo/redo.
editor.switch_page(0)
select(body_ids[0])
count = editor.undo_stack.count()
editor.set_writing_mode('vertical-rl')
assert editor.items_by_id[body_ids[0]].model.writing_mode == 'vertical-rl'
assert editor.undo_stack.count() == count+1
editor.undo()
assert editor.items_by_id[body_ids[0]].model.writing_mode == 'horizontal'
editor.redo()
item = editor.items_by_id[body_ids[0]]
assert item.model.writing_mode == 'vertical-rl'

# IME uses the actual graphics-scene input route; preedit must not enter the saved text.
item.begin_edit()
cursor = item.textCursor()
cursor.movePosition(QTextCursor.End)
item.setTextCursor(cursor)
before_preedit = item.model.text
preedit = QInputMethodEvent('한', [QInputMethodEvent.Attribute(QInputMethodEvent.Cursor, 1, 1, None)])
app.sendEvent(editor.scene, preedit)
app.processEvents()
assert item.model.text == before_preedit
capture('ime-preedit-window.png')
commit = QInputMethodEvent()
commit.setCommitString('한글')
app.sendEvent(editor.scene, commit)
app.processEvents()
assert item.model.text == before_preedit+'한글'
# A selection in the vertical canvas shares ordinary rich-text formatting.
cursor = item.textCursor()
cursor.setPosition(6)
cursor.setPosition(12, QTextCursor.KeepAnchor)
item.setTextCursor(cursor)
fmt = QTextCharFormat()
fmt.setFontWeight(QFont.Bold)
fmt.setFontPointSize(22)
editor.apply_format(fmt)
assert any(run.style.bold and run.style.size == 22 for p in item.model.paragraphs for run in p.runs)
item.finish_edit()
assert not item.vertical_layout().overflow
select(body_ids[0])
capture('vertical-selected-window.png')

# Named presets survive a real Editor restart and never save a card's wording.
style_name, layout_name = '증거 본문 · 세로', '증거 카드 · 기본 배치'
editor.save_text_preset(style_name)
editor.save_layout_preset(layout_name)
preset_file = out / 'data' / 'presets.json'
assert preset_file.exists()
preset_text = preset_file.read_text('utf-8')
assert '닫힌 방에' not in preset_text and '検証用の原文' not in preset_text
editor.save_to(out / '작업.twproj')
editor.close()
editor.deleteLater()
app.processEvents()
editor = Editor(out / 'data', auto_ocr=False)
editor.show()
editor.load_path(out / '작업.twproj')
for index in (1, 2):
    editor.switch_page(index)
    select(body_ids[index])
    before = provenance(editor.current_page)
    assert editor.apply_text_preset(style_name) == 1
    assert provenance(editor.current_page) == before
    body = editor.items_by_id[body_ids[index]].model
    assert body.writing_mode == 'vertical-rl'
    assert body.paragraphs[0].line_spacing == 1.2 and body.margin == 8

# Geometry is reused across explicitly selected cards, preserving each card's text and OCR links.
editor.switch_page(0)
candidates = editor.layout_candidates(layout_name)
target_ids = [page.id for page in editor.project.pages[1:]]
assert all(next(c for c in candidates if c['page_id'] == key)['eligible'] for key in target_ids)
before_contents = [provenance(page) for page in editor.project.pages]
before_layout = deepcopy(editor.project)
count = editor.undo_stack.count()
assert editor.apply_layout_preset(layout_name, target_ids, include_style=False) == 2
assert editor.undo_stack.count() == count+1
assert [provenance(page) for page in editor.project.pages] == before_contents
for page, key in zip(editor.project.pages[1:], body_ids[1:]):
    body = next(obj for obj in page.objects if obj.id == key)
    assert (body.x, body.y, body.width, body.height) == (155, 136, 436, 318)
editor.undo()
assert editor.project == before_layout
editor.redo()
assert [provenance(page) for page in editor.project.pages] == before_contents


def capture_layout_dialog():
    dialog = app.activeModalWidget()
    assert isinstance(dialog, QDialog)
    dialog.grab().save(str(out / 'layout-preset-dialog.png'))
    dialog.reject()


QTimer.singleShot(180, capture_layout_dialog)
editor.apply_layout_preset_dialog(name=layout_name)

# The third card exercises vertical text inside a rotated, scaled group.
editor.switch_page(2)
select(*(obj.id for obj in editor.current_page.objects))
editor.group_selected()
group = editor.selected()[0]
assert isinstance(group.model, GroupBox)
editor.begin_operation()
group.setRotation(-2)
group.setScale(.97)
editor.finish_operation('세로 카드 그룹 변환')
capture('group-window.png')
editor.enter_group(group.model.id)
select(body_ids[2])
assert not editor.items_by_id[body_ids[2]].vertical_layout().overflow
capture('inside-group-window.png')
editor.leave_group()
editor.switch_page(0)
editor.save_to(out / '작업.twproj')
expected = [hashlib.sha256(png_data(render_page(deepcopy(page), editor.assets[page.asset]))).hexdigest()
            for page in editor.project.pages]
editor.export_pages(run / 'pages', range(3), 'png')
editor.export_pages(run / '작업.pdf', range(3), 'pdf')
assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted((run / 'pages').glob('*.png'))] == expected
editor.load_path(out / '작업.twproj')
for index, digest in enumerate(expected):
    editor.switch_page(index)
    assert hashlib.sha256(png_data(editor.render_image())).hexdigest() == digest
physical_sizes = [[page.width_pt, page.height_pt] for page in editor.project.pages]
pdf = PdfReader(run / '작업.pdf')
assert len(pdf.pages) == 3
for page, (width, height) in zip(pdf.pages, physical_sizes):
    assert abs(float(page.mediabox.width)-width) < .01
    assert abs(float(page.mediabox.height)-height) < .01
assert hashlib.sha256(source.read_bytes()).hexdigest() == source_digest
assert {name: hashlib.sha256(data).hexdigest() for name, data in editor.assets.items()} == original_assets
editor.switch_page(0)
select(body_ids[0])
capture('window.png')
report = {
    'version': editor.project.version, 'pages': 3, 'native_platform': app.platformName(),
    'ime_preedit_not_saved': True, 'ime_korean_commit': True, 'vertical_partial_format': True,
    'writing_direction_single_undo': True, 'saved_style_survives_restart': True,
    'layout_reused_pages': 2, 'layout_single_undo': True, 'wording_and_source_links_preserved': True,
    'vertical_rotated_group': True, 'all_sources_unchanged': True,
    'roundtrip_all_png_identical': True, 'batch_png_identical': True,
    'pdf_physical_sizes_preserved': True,
    'pdf': str(run / '작업.pdf'), 'png_folder': str(run / 'pages'), 'project': str(out / '작업.twproj'),
    'page_png_sha256': expected, 'physical_sizes': physical_sizes,
    'source_project_sha256': source_digest, 'asset_sha256': original_assets,
}
(out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
print(json.dumps(report, ensure_ascii=True), flush=True)
editor.close()
