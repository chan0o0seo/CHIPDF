"""Native mixed-object QA using a copy of the real-card draft project."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / ".deps"), str(ROOT)]
import hashlib
import json
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication
from studio.window import Editor
from studio.model import Paragraph, Run, Style, TextBox

QApplication.setAttribute(Qt.AA_Use96Dpi)
app = QApplication([])
app.setFont(QFont("맑은 고딕", 10))
out = ROOT / "qa" / "editing-03"
out.mkdir(parents=True, exist_ok=True)
editor = Editor(out / "data", auto_ocr=False)
editor.show()
source = ROOT / "qa" / "workflow-02" / "직접수정.twproj"
digest = hashlib.sha256(source.read_bytes()).hexdigest()
editor.load_path(source)
editor.save_to(out / "편집예시.twproj")
banner = editor.add_shape("roundrect")
banner.x, banner.y, banner.width, banner.height = 75, 70, 570, 64
banner.fill, banner.stroke_width = "#286a60", 0
editor.rebuild_scene([banner.id])
editor.toggle_lock()
title = editor.add_object(TextBox(width=500, height=52, paragraphs=[Paragraph([Run("번역 카드 · 편집 예시", Style(size=23, color="#ffffff", bold=True))])]), "예시 제목")
title.x, title.y = 97, 77
editor.rebuild_scene()
swatches = []
for x, color in [(80, "#286a60"), (270, "#61998a"), (510, "#d69a57")]:
    obj = editor.add_shape("ellipse")
    obj.x, obj.y, obj.width, obj.height = x, 409, 45, 45
    obj.fill, obj.stroke_width = color, 0
    editor.rebuild_scene()
    swatches.append(obj.id)
for key in swatches:
    editor.items_by_id[key].setSelected(True)
editor.arrange("horizontal")
arrow = editor.add_shape("arrow")
arrow.x, arrow.y, arrow.width, arrow.height = 565, 410, 42, 40
arrow.stroke_width = 3
editor.rebuild_scene()
asset = QImage(100, 100, QImage.Format_ARGB32)
asset.fill(Qt.transparent)
painter = QPainter(asset)
painter.setRenderHint(QPainter.Antialiasing)
painter.setPen(Qt.NoPen)
painter.setBrush(QColor("#286a60"))
painter.drawEllipse(10, 10, 80, 80)
painter.setPen(QPen(QColor("white"), 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
painter.drawLine(QPointF(30, 51), QPointF(44, 65))
painter.drawLine(QPointF(44, 65), QPointF(72, 36))
painter.end()
image = editor.insert_qimage(asset)
image.x, image.y, image.width, image.height = 612, 400, 64, 64
image.opacity = .85
editor.rebuild_scene([image.id])
editor.apply_crop(image.id, [.08, .08, .84, .84])
editor.save_to(out / "편집예시.twproj")
editor.export_to(out / "편집예시.png")
expected = (out / "편집예시.png").read_bytes()
editor.load_path(out / "편집예시.twproj")
editor.export_to(out / "다시열기.png")
assert expected == (out / "다시열기.png").read_bytes()
assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
editor.items_by_id[image.id].setSelected(True)
editor.source_dock.hide()
app.processEvents()
editor.canvas.fit_page()
app.processEvents()
editor.grab().save(str(out / "window.png"))
from studio.crop_dialog import CropDialog
dialog = CropDialog(asset, image.crop, editor)
dialog.show()
app.processEvents()
dialog.grab().save(str(out / "crop-dialog.png"))
dialog.reject()
report = {"objects": len(editor.project.pages[0].objects), "kinds": sorted({o.kind for o in editor.project.pages[0].objects}),
          "locked_banner": next(o for o in editor.project.pages[0].objects if o.id == banner.id).locked,
          "embedded_transparent_image": True, "original_project_unchanged": True, "reopen_png_identical": True}
(out / "result.json").write_text(json.dumps(report, indent=2), "utf-8")
print(json.dumps(report))
editor.close()
