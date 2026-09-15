"""Native v0.4 QA on a retained v0.3 card copy, including nested groups."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / '.deps'), str(ROOT)]
import hashlib
import json
from PySide6.QtCore import QPointF, QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QDialog, QDoubleSpinBox
from studio.window import Editor
from studio.model import GroupBox, ImageBox, ShapeBox, TextBox

QApplication.setAttribute(Qt.AA_Use96Dpi)
app = QApplication([])
app.setFont(QFont('맑은 고딕', 10))
out = ROOT / 'qa' / 'layout-04'
out.mkdir(parents=True, exist_ok=True)
editor = Editor(out / 'data', auto_ocr=False)
editor.show()
source = ROOT / 'qa' / 'editing-03' / '편집예시.twproj'
digest = hashlib.sha256(source.read_bytes()).hexdigest()
editor.load_path(source)
editor.save_to(out / '그룹편집.twproj')

def select(*ids):
    editor.scene.clearSelection()
    for key in ids:
        editor.items_by_id[key].setSelected(True)
    app.processEvents()

def group(*ids):
    select(*ids)
    editor.group_selected()
    return editor.selected()[0].model.id

objects = editor.project.pages[0].objects
banner = next(o for o in objects if isinstance(o, ShapeBox) and o.shape == 'roundrect')
title = next(o for o in objects if isinstance(o, TextBox) and not o.source_text)
select(banner.id)
editor.toggle_lock()
title = editor.items_by_id[title.id].model
title.paragraphs[0].runs[0].text = '번역 카드 · 그룹 편집'
title.margin, title.height, title.y = 4, 56, 74
editor.rebuild_scene()
header = group(banner.id, title.id)
swatches = [o.id for o in editor.project.pages[0].objects if isinstance(o, ShapeBox) and o.shape == 'ellipse']
palette = group(*swatches)
image = next(o.id for o in editor.project.pages[0].objects if isinstance(o, ImageBox))
arrow = next(o.id for o in editor.project.pages[0].objects if isinstance(o, ShapeBox) and o.shape == 'arrow')
footer = group(palette, arrow, image)
editor.begin_operation()
editor.items_by_id[footer].setScale(.94)
editor.items_by_id[footer].setRotation(-2)
editor.finish_operation('그룹 크기·회전')

body = next(o for o in editor.project.pages[0].objects if isinstance(o, TextBox) and o.source_text and len(o.text) > 70)
select(body.id)
editor.apply_paragraph_settings(dict(line_spacing=1.15, space_before=0, space_after=4, margin=6))
item = editor.items_by_id[body.id]
if item.document().size().height() > item.model.height:
    editor.begin_operation()
    item.prepareGeometryChange()
    item.model.height = item.document().size().height()+4
    item.setTransformOriginPoint(item.model.width/2, item.model.height/2)
    editor.finish_operation('문단 높이')

editor.save_to(out / '그룹편집.twproj')
editor.export_to(out / '그룹편집.png')
expected = (out / '그룹편집.png').read_bytes()
editor.load_path(out / '그룹편집.twproj')
editor.export_to(out / '다시열기.png')
assert expected == (out / '다시열기.png').read_bytes()
select(header)
editor.source_dock.hide()
editor.canvas.fit_page()
app.processEvents()
editor.grab().save(str(out / 'window.png'))
editor.enter_group(header)
select(title.id)
app.processEvents()
editor.grab().save(str(out / 'inside-group.png'))
editor.leave_group()

# Real drag positions produce the guides; export must still match the card.
select(header)
editor.snap_drag()
app.processEvents()
editor.grab().save(str(out / 'guides.png'))
editor.scene.snap_guides = []
editor.rebuild_scene([body.id])
def capture_dialog():
    dialog = app.activeModalWidget()
    assert isinstance(dialog, QDialog)
    assert len(dialog.findChildren(QDoubleSpinBox)) == 4
    dialog.grab().save(str(out / 'paragraph-dialog.png'))
    dialog.reject()
QTimer.singleShot(150, capture_dialog)
editor.paragraph_dialog()

# Keep the structured clipboard populated through an actual Windows event-loop exit.
select(footer)
editor.copy_objects()
assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
report = {
    'version': editor.project.version,
    'objects': len(editor.project.pages[0].objects),
    'groups': sum(isinstance(o, GroupBox) for o in editor.project.pages[0].objects),
    'nested_group': editor.items_by_id[palette].model.parent_id == footer,
    'group_scale': editor.items_by_id[footer].model.scale,
    'group_rotation': editor.items_by_id[footer].model.rotation,
    'paragraph_line_spacing': editor.items_by_id[body.id].model.paragraphs[0].line_spacing,
    'original_project_unchanged': True,
    'reopen_png_identical': True,
}
(out / 'result.json').write_text(json.dumps(report, indent=2), 'utf-8')
print(json.dumps(report), flush=True)
QTimer.singleShot(150, editor.close)
raise SystemExit(app.exec())
