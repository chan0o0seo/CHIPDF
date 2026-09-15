"""Read-only real-card verification; write results only inside this app's qa folder."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / ".deps"), str(ROOT)]
import hashlib
import json
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QInputMethodEvent, QTextCursor
from PySide6.QtWidgets import QApplication
from studio.window import Editor

QApplication.setAttribute(Qt.AA_Use96Dpi)
app = QApplication([])
app.setFont(QFont("맑은 고딕", 10))
source = Path(sys.argv[1]).resolve()
before = hashlib.sha256(source.read_bytes()).hexdigest()
output = ROOT / "qa" / "real-card"
output.mkdir(parents=True, exist_ok=True)
editor = Editor(output / "data", auto_ocr=False)
editor.show()
editor.load_path(source)
app.processEvents()
editor.add_text()
item = editor.editing_item()
event = QInputMethodEvent()
event.setCommitString("한글 편집 테스트\n더블클릭해서 문장을 고쳐 보세요.")
app.sendEvent(editor.scene, event)
item.finish_edit()
page = editor.project.pages[0]
editor.begin_operation()
item.setPos(page.width * .14, page.height * .70)
item.model.fill = "#ffffff"
item.prepareGeometryChange()
item.model.width = page.width * .72
item.model.height = max(110, page.height * .16)
item.setTextWidth(item.model.width)
editor.finish_operation("테스트 배치")
editor.size_box.setValue(max(12, min(24, page.width / 40)))
editor.update_tools()
editor.save_to(output / "편집시험.twproj")
editor.export_to(output / "편집시험.png")
before_doc = next(iter(editor.items_by_id.values())).document()
(output / "before.html").write_text(before_doc.toHtml(), "utf-8")
first_png = (output / "편집시험.png").read_bytes()
editor.load_path(output / "편집시험.twproj")
editor.export_to(output / "다시열기.png")
after_doc = next(iter(editor.items_by_id.values())).document()
(output / "after.html").write_text(after_doc.toHtml(), "utf-8")
assert first_png == (output / "다시열기.png").read_bytes(), "Reopening changed rendered PNG"
next(iter(editor.items_by_id.values())).setSelected(True)
editor.canvas.fit_page()
app.processEvents()
editor.grab().save(str(output / "window.png"))
assert before == hashlib.sha256(source.read_bytes()).hexdigest(), "Original was modified"
report = {"source_name": source.name, "source_sha256": before, "width": page.width, "height": page.height,
          "reopen_png_identical": True, "original_unchanged": True}
(output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
print(json.dumps(report, ensure_ascii=True))
editor.close()
