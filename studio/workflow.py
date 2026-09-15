"""Card workflow kept separate from the editing window's formatting controls."""
from copy import deepcopy
import hashlib

from PySide6.QtCore import QRect, QRectF, Qt, QThreadPool, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QDockWidget, QInputDialog, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget)

from .jobs import Job
from .model import Paragraph, Run, Style, TextBox
from .recognition import recognize, restored_background
from .region_tools import RegionTools


def overlaps(a, b):
    x = max(0, min(a[0]+a[2], b[0]+b[2])-max(a[0], b[0]))
    y = max(0, min(a[1]+a[3], b[1]+b[3])-max(a[1], b[1]))
    return x*y / max(1, min(a[2]*a[3], b[2]*b[3])) > .45


class Workflow(RegionTools):
    def init_workflow(self, auto_ocr):
        self.auto_ocr = auto_ocr
        self.job = None
        self.generation = 0
        self.translator = None
        self.translation_after_ocr = False
        self.pending_ocr = False
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.background_signature = None
        self.background_image = QImage()
        self.background_timer = QTimer(self)
        self.background_timer.setSingleShot(True)
        self.background_timer.setInterval(80)
        self.background_timer.timeout.connect(self.refresh_background)
        self.last_job_result = None
        self.translate_action = self.action("번역", self.translate_selection)
        self.translate_action.setToolTip("선택한 문장을 번역합니다. 이미 입력한 글은 새 번역 후보와 비교합니다.")
        self.main_toolbar.insertAction(self.add_action, self.translate_action)
        self.source_action = self.action("원문 확인", self.show_source)
        self.format_bar.insertAction(self.duplicate_action, self.source_action)
        self.reread_action = self.action("페이지 자동 인식", lambda: self.start_ocr(force=True))
        self.vertical_ocr_action = self.action("페이지 자동 인식 · 세로 원문", lambda: self.start_ocr(force=True, vertical=True))
        self.file_menu.addActions([self.reread_action, self.vertical_ocr_action])
        self.translate_all_action = self.action('빈 번역문 모두 번역', self.translate_missing)
        self.file_menu.addAction(self.translate_all_action)
        self.stop_button = QPushButton("중단")
        self.stop_button.clicked.connect(self.cancel_job)
        self.statusBar().addPermanentWidget(self.stop_button)
        self.stop_button.hide()
        self.source_dock = QDockWidget("원문 확인", self)
        self.source_dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.source_dock.setFeatures(QDockWidget.DockWidgetClosable)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        self.source_state = QLabel()
        self.source_state.setWordWrap(True)
        layout.addWidget(self.source_state)
        self.source_crop = QLabel()
        self.source_crop.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.source_crop)
        self.source_text = QTextEdit()
        self.source_text.setReadOnly(True)
        self.source_text.setMinimumHeight(110)
        self.source_text.setMaximumHeight(220)
        layout.addWidget(self.source_text)
        self.edit_source_button = QPushButton("원문 수정")
        self.edit_source_button.clicked.connect(self.edit_source)
        layout.addWidget(self.edit_source_button)
        self.retranslate_button = QPushButton("다시 번역해 비교")
        self.retranslate_button.clicked.connect(self.retranslate)
        layout.addWidget(self.retranslate_button)
        self.candidate_text = QTextEdit()
        self.candidate_text.setReadOnly(True)
        self.candidate_text.setMaximumHeight(180)
        self.candidate_text.setPlaceholderText("새 번역 후보")
        layout.addWidget(self.candidate_text)
        self.apply_candidate_button = QPushButton("이 번역 적용")
        self.apply_candidate_button.clicked.connect(self.apply_candidate)
        layout.addWidget(self.apply_candidate_button)
        self.erase_button = QPushButton("원문 가리기")
        self.erase_button.setCheckable(True)
        self.erase_button.clicked.connect(self.toggle_erase)
        layout.addWidget(self.erase_button)
        self.review_button = QPushButton("검토 완료")
        self.review_button.clicked.connect(self.mark_reviewed)
        layout.addWidget(self.review_button)
        layout.addStretch()
        panel.setMinimumWidth(270)
        panel.setMaximumWidth(370)
        self.source_dock.setWidget(panel)
        self.addDockWidget(Qt.RightDockWidgetArea, self.source_dock)
        self.source_dock.hide()
        self.init_region_tools()
        self.update_workflow_tools()

    def current_source(self):
        selected = self.selected()
        return selected[0].model if len(selected) == 1 and isinstance(selected[0].model, TextBox) and (selected[0].model.source_text or selected[0].model.source_rect) else None

    def show_source(self):
        view = self.capture_canvas_view()
        self.source_dock.show()
        self.update_source_panel()

        self.update_region_tools()
        self.restore_canvas_view(view)

    def update_workflow_tools(self):
        if not hasattr(self, "review_button"):
            return
        ready = bool(self.project) and not self.comparing
        idle = self.job is None and not getattr(self, 'io_job', None)
        self.translate_action.setEnabled(ready and idle)
        self.reread_action.setEnabled(ready and idle)
        self.vertical_ocr_action.setEnabled(ready and idle)
        self.translate_all_action.setEnabled(ready and idle)
        self.source_action.setEnabled(ready and self.current_source() is not None)
        obj = self.current_source()
        self.retranslate_button.setEnabled(ready and idle and obj is not None and not self.effective_locked(obj))
        self.update_source_panel()
        self.update_region_tools()

    def update_source_panel(self):
        if not hasattr(self, "source_dock"):
            return
        obj = self.current_source()
        for widget in (self.edit_source_button, self.erase_button, self.review_button):
            widget.setEnabled(obj is not None and not self.effective_locked(obj) and not self.comparing)
        self.candidate_text.hide()
        self.apply_candidate_button.hide()
        if obj is None:
            self.source_state.setText("카드에서 원문 영역을 선택해 주세요.")
            self.source_text.clear()
            self.source_crop.clear()
            return
        status = "검토 완료" if obj.reviewed else "번역 초안 · 원문 대조 필요" if obj.text else "번역문을 기다리는 원문"
        if not obj.source_confirmed and obj.confidence < 75:
            status += "\n원문 인식이 불확실합니다. 먼저 확인해 주세요."
        self.source_state.setText(status)
        self.source_text.setPlainText(obj.source_text)
        if obj.source_rect:
            x, y, w, h = obj.source_rect
            crop = self.image.copy(QRect(max(0, int(x)-4), max(0, int(y)-4), int(w)+8, int(h)+8))
            self.source_crop.setPixmap(QPixmap.fromImage(crop).scaled(270, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.erase_button.setChecked(obj.erase_enabled)
        self.erase_button.setEnabled(bool(obj.erase_patch) and not self.effective_locked(obj) and not self.comparing)
        self.review_button.setEnabled(bool(obj.text) and not self.effective_locked(obj) and not self.comparing)
        if obj.candidate_text and obj.candidate_source == obj.source_text:
            self.candidate_text.setPlainText(obj.candidate_text)
            self.candidate_text.show()
            self.apply_candidate_button.show()
            self.apply_candidate_button.setEnabled(not self.effective_locked(obj) and not self.comparing)

    def edit_source(self):
        obj = self.current_source()
        if obj is None:
            return
        text, ok = QInputDialog.getMultiLineText(self, "원문 수정", "원본 이미지와 대조한 일본어 원문", obj.source_text)
        if ok and text.strip():
            self.commit_source(obj.id, text.strip())

    def commit_source(self, object_id, text):
        self.finish_edit()
        obj = self.items_by_id[object_id].model
        if self.effective_locked(obj) or self.comparing:
            return
        self.begin_operation()
        obj.source_text = text
        obj.source_confirmed = True
        obj.reviewed = False
        obj.candidate_text = obj.candidate_source = ""
        self.finish_operation("원문 수정")

    def mark_reviewed(self):
        self.finish_edit()
        obj = self.current_source()
        if obj and not self.effective_locked(obj) and not self.comparing:
            self.begin_operation()
            obj.reviewed = True
            self.finish_operation("검토 완료")

    def toggle_erase(self, checked):
        self.finish_edit()
        obj = self.current_source()
        if obj and not self.effective_locked(obj) and not self.comparing:
            self.begin_operation()
            obj.erase_enabled = checked
            self.finish_operation("원문 가리기")
            self.refresh_background()

    def apply_candidate(self):
        self.finish_edit()
        obj = self.current_source()
        if not obj or self.effective_locked(obj) or self.comparing or not obj.candidate_text or obj.candidate_source != obj.source_text:
            return
        self.begin_operation()
        self.set_target(obj, obj.candidate_text)
        obj.candidate_text = obj.candidate_source = ""
        self.rebuild_scene([obj.id])
        self.fit_fresh_targets([obj.id])
        self.finish_operation("번역 후보 적용")

    def refresh_background(self):
        if not self.project or not hasattr(self, "background_item") or not hasattr(self, "background_signature"):
            return
        active = [(o.id, o.erase_patch, o.erase_mask, o.erase_rect) for o in self.current_page.objects
                  if isinstance(o, TextBox) and (o.text.strip() or o.erase_when_empty) and o.erase_enabled and o.erase_patch]
        active += [(p.id, p.patch, p.mask, p.rect) for p in self.current_page.background_patches]
        signature = hashlib.sha256(repr(active).encode()).hexdigest()
        if self.comparing:
            self.background_item.setPixmap(QPixmap.fromImage(self.image))
        else:
            if self.background_signature != signature or self.background_image.isNull():
                self.background_image = QImage.fromData(restored_background(self.original, self.current_page.objects, self.current_page.background_patches), "PNG") if active else self.image
                self.background_signature = signature
            self.background_item.setPixmap(QPixmap.fromImage(self.background_image))

    def cancel_job(self):
        self.translation_after_ocr = False
        if self.job:
            self.job.cancelled.set()
            self.status.setText("중단 중… 현재 문장 처리가 끝나면 멈춥니다")

    def invalidate_jobs(self):
        if hasattr(self, "generation"):
            self.generation += 1
            self.cancel_job()
            self.pending_ocr = False
            self.background_signature = None

    def launch_job(self, operation, callback, keep_partial=False):
        if self.job:
            return False
        context = (self.project.id, self.current_page.id, self.generation)
        job = Job(operation)
        self.last_error = None
        self.job = job
        self.stop_button.show()
        self.update_workflow_tools()
        def progress(message):
            if self.project and (self.project.id, self.current_page.id, self.generation) == context and not job.cancelled.is_set():
                self.status.setText(message)
        def complete(result):
            self.job = None
            self.stop_button.hide()
            self.last_job_result = result
            self.manual_task = None
            valid = self.project and (self.project.id, self.current_page.id, self.generation) == context
            if valid and not result["cancelled"] and not job.cancelled.is_set():
                if result["error"]:
                    self.last_error = result["error"]
                    self.status.setText("처리 실패 · " + result["error"])
                    self.translation_after_ocr = False
                else:
                    callback(result["value"])
            elif valid:
                if keep_partial and result["value"]:
                    callback(result["value"])
                    self.status.setText("중단됨 · " + self.status.text())
                else:
                    self.status.setText("중단됨 · 편집 내용은 유지됩니다")
            self.update_workflow_tools()
            if self.pending_ocr:
                QTimer.singleShot(0, self.start_pending_ocr)
        job.signals.progress.connect(progress, Qt.QueuedConnection)
        job.signals.finished.connect(complete, Qt.QueuedConnection)
        self.pool.start(job)
        return True

    def start_pending_ocr(self):
        if self.pending_ocr and self.job is None:
            self.pending_ocr = False
            self.start_ocr()

    def start_ocr(self, checked=False, force=False, vertical=False):
        if not self.project or self.job or self.comparing or (self.current_page.ocr_done and not force):
            return
        self.canvas.cancel_tool()
        self.finish_edit()
        original = self.original
        clean = self.assets.get(getattr(self.current_page, 'clean_asset', ''))
        self.launch_job(lambda cancel, progress: recognize(original, cancel, progress, vertical,
                            **({'clean_background': clean} if clean else {})), self.accept_regions)

    def accept_regions(self, regions):
        self.finish_edit()
        self.begin_operation()
        page = self.current_page
        added = []
        for region in regions:
            existing = []
            for obj in page.objects:
                if isinstance(obj, TextBox):
                    if obj.source_rect:
                        existing.append(obj.source_rect)
                    else:
                        rect = self.items_by_id[obj.id].mapRectToScene(QRectF(0, 0, obj.width, obj.height))
                        existing.append([rect.x(), rect.y(), rect.width(), rect.height()])
            if any(overlaps(region.rect, rect) for rect in existing):
                continue
            x, y, w, h = region.rect
            obj = TextBox(x=max(0, x-6), y=max(0, y-5), width=max(24, w+12), height=max(32, h+12),
                          z=len(page.objects), paragraphs=[Paragraph([Run("", Style(size=max(9, min(28, region.line_height*.68))))])],
                          source_text=region.text, source_rect=region.rect, confidence=max(0, min(100, region.confidence)),
                          erase_rect=region.erase_rect, erase_patch=region.patch, erase_mask=region.mask)
            page.objects.append(obj)
            added.append(obj.id)
        page.ocr_done = True
        self.rebuild_scene()
        self.finish_operation("원문 읽기")
        self.autosave()
        self.status.setText(f"원문 {len(regions)}개 확인 · {len(added)}개 추가 · 기존 편집 유지")
        if self.translation_after_ocr:
            self.translation_after_ocr = False
            QTimer.singleShot(0, self.translate_missing)

    def translate_missing(self):
        if not self.project or self.job or self.comparing:
            return
        self.finish_edit()
        if self.auto_ocr and not self.current_page.ocr_done:
            self.translation_after_ocr = True
            self.start_ocr()
            return
        objects = [obj for obj in self.current_page.objects if isinstance(obj, TextBox) and obj.source_text and not obj.text.strip() and not self.effective_locked(obj)]
        if not objects:
            self.status.setText("빈 번역문이 없습니다 · 원문 확인에서 다시 번역해 비교할 수 있습니다")
            return
        self.start_translation(objects, candidates=False)

    def retranslate(self):
        self.finish_edit()
        obj = self.current_source()
        if obj and not self.effective_locked(obj) and not self.job:
            self.start_translation([obj], candidates=True)

    def start_translation(self, objects, candidates):
        snapshot = {obj.id: (obj.source_text, obj.text, deepcopy(obj.paragraphs)) for obj in objects}
        def translate(cancelled, progress):
            from .translation import LocalTranslator
            progress("로컬 번역 모델 준비 중…")
            if self.translator is None:
                self.translator = LocalTranslator()
            rows = []
            for index, (key, (source, target, paragraphs)) in enumerate(snapshot.items()):
                if cancelled.is_set():
                    break
                progress(f"번역 초안 {index + 1}/{len(snapshot)} · 완료 후 원문과 대조해 주세요")
                try:
                    target = self.translator.translate(source, cancelled)
                    if cancelled.is_set():
                        break
                    rows.append((key, target, None))
                except Exception as exc:
                    rows.append((key, "", str(exc)))
            return rows
        self.launch_job(translate, lambda rows: self.accept_translations(rows, snapshot, candidates), keep_partial=True)

    def set_target(self, obj, text):
        first = deepcopy(obj.paragraphs[0])
        style = first.runs[0].style
        obj.paragraphs = [Paragraph([Run(line, deepcopy(style))], first.align, first.line_spacing, first.space_before, first.space_after) for line in text.splitlines() or [""]]
        obj.target_origin = "machine"
        obj.reviewed = False

    def accept_translations(self, rows, snapshot, candidates):
        self.finish_edit()
        self.begin_operation()
        applied, skipped, failed = [], 0, 0
        for key, text, error in rows:
            item = self.items_by_id.get(key)
            if error or not text.strip():
                failed += 1
                continue
            if item is None or self.effective_locked(item.model) or (item.model.source_text, item.model.text, item.model.paragraphs) != snapshot[key]:
                skipped += 1
                continue
            obj = item.model
            if candidates:
                obj.candidate_text, obj.candidate_source = text, obj.source_text
            else:
                self.set_target(obj, text)
            applied.append(key)
        self.rebuild_scene(applied[:1])
        if not candidates:
            self.fit_fresh_targets(applied)
        self.finish_operation("번역 후보" if candidates else "번역 초안")
        self.autosave()
        self.status.setText(f"{'후보' if candidates else '초안'} {len(applied)}개 · 변경 보존 {skipped}개 · 실패 {failed}개 · 미처리 {len(snapshot)-len(rows)}개 · 원문 대조 필요")
        if applied:
            self.show_source()

    def fit_fresh_targets(self, ids):
        from .richtext import populate
        for key in ids:
            item = self.items_by_id[key]
            # Only newly generated plain-text drafts are fitted. Manual layouts remain intact.
            item.document().blockSignals(True)
            while (item.has_overflow() if item.is_vertical else item.document().size().height() > item.model.height) and item.model.paragraphs[0].runs[0].style.size > 9:
                for para in item.model.paragraphs:
                    for run in para.runs:
                        run.style.size = max(9, run.style.size - .5)
                populate(item.document(), item.model.paragraphs, item.model.margin)
                item.setTextWidth(item.model.width)
            item.document().blockSignals(False)
