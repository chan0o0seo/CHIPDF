"""Real-card end-to-end QA, using the same background jobs as the shipped UI."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / ".deps"), str(ROOT)]
import hashlib
import json
import time
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QInputMethodEvent, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from studio.window import Editor
from studio.storage import load_project

QApplication.setAttribute(Qt.AA_Use96Dpi)
app = QApplication([])
app.setFont(QFont("맑은 고딕", 10))
out = ROOT / "qa" / "workflow-02"
out.mkdir(parents=True, exist_ok=True)
_, original = load_project(ROOT / "qa" / "real-card" / "편집시험.twproj")
(out / "sample.png").write_bytes(original)
digest = hashlib.sha256(original).hexdigest()
editor = Editor(out / "data")
editor.show()

def wait_jobs():
    started = time.perf_counter()
    app.processEvents()
    while editor.job or editor.translation_after_ocr:
        # QTest.qWait can keep the GIL on this Windows wheel and starve workers.
        # Pump UI events, then explicitly let Python background jobs run.
        app.processEvents()
        time.sleep(.01)
        if time.perf_counter()-started > 90:
            editor.cancel_job()
            raise TimeoutError("Card job did not complete")
    app.processEvents()
    assert not editor.last_error, editor.last_error
    print("job finished: " + str(editor.last_job_result.get("error") if editor.last_job_result else None), flush=True)
    return round(time.perf_counter()-started, 3)

editor.load_path(out / "sample.png")
print("opened image", flush=True)
ocr_seconds = wait_jobs()
objects = editor.project.pages[0].objects
assert len(objects) >= 3
raw_sources = [o.source_text for o in objects]
title = objects[0]
# Explicit proofreading exercise, not an undisclosed OCR correction.
editor.commit_source(title.id, "エンジニアエンディング・a-1「悪夢」")
editor.translate_missing()
translate_seconds = wait_jobs()
assert all(o.text for o in editor.project.pages[0].objects)
initial = [{"source": o.source_text, "target": o.text, "confidence": o.confidence} for o in editor.project.pages[0].objects]
editor.save_to(out / "자동초안.twproj")
editor.export_to(out / "자동초안.png")

# Manual correction in the canvas; subsequent translation must preserve it.
title = editor.items_by_id[title.id]
editor.scene.clearSelection()
title.setSelected(True)
title.begin_edit()
cursor = title.textCursor()
cursor.select(QTextCursor.Document)
title.setTextCursor(cursor)
event = QInputMethodEvent()
event.setCommitString("엔지니어 엔딩 · a-1 ‘악몽’")
app.sendEvent(editor.scene, event)
title.finish_edit()
corrected = title.model.text
editor.translate_missing()
assert title.model.text == corrected
editor.retranslate()
wait_jobs()
title = editor.items_by_id[title.model.id]
assert title.model.text == corrected and title.model.candidate_text
editor.save_to(out / "직접수정.twproj")
editor.export_to(out / "직접수정.png")
expected = (out / "직접수정.png").read_bytes()
editor.load_path(out / "직접수정.twproj")
editor.export_to(out / "다시열기.png")
assert expected == (out / "다시열기.png").read_bytes()
first = next(iter(editor.items_by_id.values()))
first.setSelected(True)
editor.show_source()
app.processEvents()
editor.canvas.fit_page()
app.processEvents()
editor.grab().save(str(out / "window.png"))
assert hashlib.sha256((out / "sample.png").read_bytes()).hexdigest() == digest
report = {"ocr_seconds": ocr_seconds, "translate_seconds": translate_seconds, "regions": len(objects),
          "raw_ocr": raw_sources, "drafts": initial, "manual_target_preserved": True,
          "retranslation_is_candidate": True, "reopen_png_identical": True, "original_unchanged": True}
(out / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
print(json.dumps({k: v for k, v in report.items() if k not in ("raw_ocr", "drafts")}, ensure_ascii=True))
editor.close()
