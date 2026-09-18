"""Translation preferences, terminology suggestions and reviewed memory UI."""
from copy import deepcopy
import re
from PySide6.QtCore import Qt

from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                              QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                              QLineEdit, QListWidget, QMessageBox, QPushButton,
                              QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit,
                              QVBoxLayout, QWidget, QFileDialog, QProgressDialog)

from .translation_quality import (ENGINES, memory_suggestions, prepare_source,
                                  request_for, validate_translation_data)
from .translation_service import TranslationService
from .jobs import Job
from . import model_packs


def label(text):
    widget = QLabel(text)
    widget.setWordWrap(True)
    return widget


def buttons(dialog):
    box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    box.button(QDialogButtonBox.Save).setText("저장")
    box.button(QDialogButtonBox.Cancel).setText("취소")
    box.rejected.connect(dialog.reject)
    return box


class TranslationTools:
    def init_translation_tools(self, layout):
        self.translation_service = TranslationService(self.data_dir)
        self.translation_settings_action = self.action("번역 설정·용어집", self.edit_translation_settings)
        self.chrome_connect_action = self.action("Chrome 연결", self.open_chrome_translation)
        self.file_menu.addActions([self.translation_settings_action, self.chrome_connect_action])
        self.offline_install_action = self.action("오프라인 팩 설치…", self.install_offline_pack)
        self.offline_connect_action = self.action("기존 모델 폴더 연결…", self.connect_offline_folder)
        self.file_menu.addActions([self.offline_install_action, self.offline_connect_action])
        self.translation_context_button = QPushButton("화자·문맥·문단 입력")
        self.translation_context_button.clicked.connect(self.edit_translation_context)
        self.memory_button = QPushButton("확정 번역에서 찾기")
        self.memory_button.clicked.connect(self.choose_memory_translation)
        self.glossary_suggestion_button = QPushButton("용어 표기 제안")
        self.glossary_suggestion_button.clicked.connect(self.suggest_terminology)
        for widget in (self.translation_context_button, self.memory_button, self.glossary_suggestion_button):
            layout.addWidget(widget)

    def update_translation_tools(self):
        if not hasattr(self, "translation_settings_action"):
            return
        ready = bool(self.project) and not self.comparing
        idle = self.job is None and not getattr(self, "io_job", None)
        self.translation_settings_action.setEnabled(ready and idle)
        self.chrome_connect_action.setEnabled(idle)
        self.offline_install_action.setEnabled(idle)
        self.offline_connect_action.setEnabled(idle)
        obj = self.current_source()
        editable = ready and obj is not None and not self.effective_locked(obj)
        self.translation_context_button.setEnabled(editable and idle)
        self.memory_button.setEnabled(editable and idle and bool(self.project.translation_memory))
        self.glossary_suggestion_button.setEnabled(editable and idle and bool(obj.text if obj else "")
                                                   and bool(self.project.glossary if self.project else []))

    def open_chrome_translation(self):
        if self.job or getattr(self, "io_job", None):
            return
        try:
            self.translation_service.open_chrome()
            self.status.setText("Chrome 번역 도우미에서 번역 준비를 눌러 주세요")
        except (OSError, RuntimeError) as exc:
            QMessageBox.information(self, "Chrome 번역 연결", str(exc))

    def connect_offline_folder(self):
        if self.job or getattr(self, "io_job", None):
            return
        folder = QFileDialog.getExistingDirectory(self, "model.bin과 origin.json이 있는 오프라인 모델 폴더")
        if not folder:
            return
        try:
            root = model_packs.connect_folder(folder, self.data_dir)
            self.translation_service.reset_local()
            self.status.setText("오프라인 모델 연결 완료 · " + str(root))
        except (OSError, ValueError) as exc:
            QMessageBox.information(self, "오프라인 모델 연결", str(exc))

    def install_offline_pack(self):
        if self.job or getattr(self, "io_job", None):
            return
        path, _ = QFileDialog.getOpenFileName(self, "치pdf 오프라인 팩 선택", "", "오프라인 팩 (*.zip)")
        if not path:
            return
        self.finish_edit()
        progress = QProgressDialog("오프라인 팩을 설치합니다…", "중단", 0, 0, self)
        progress.setWindowTitle("오프라인 팩 설치")
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        data_dir = self.data_dir
        job = Job(lambda cancel, report: model_packs.install_pack(path, data_dir, cancel, report))
        self.job = job
        self.update_workflow_tools()
        progress.canceled.connect(job.cancelled.set)
        job.signals.progress.connect(progress.setLabelText)
        def complete(result):
            self.job = None
            progress.close()
            progress.deleteLater()
            if self.loading:
                return
            if result["value"]:
                self.translation_service.reset_local()
                self.status.setText("오프라인 팩 설치 완료 · 번역 설정에서 오프라인 엔진을 선택하세요")
            elif result["cancelled"] or job.cancelled.is_set():
                self.status.setText("오프라인 팩 설치 중단 · 기존 모델과 작업은 유지됩니다")
            else:
                QMessageBox.information(self, "오프라인 팩 설치", result["error"] or "팩을 설치하지 못했습니다.")
            self.update_workflow_tools()
        job.signals.finished.connect(complete)
        progress.show()
        self.pool.start(job)

    def edit_translation_settings(self):
        if not self.project or self.job or self.comparing or getattr(self, "io_job", None):
            return
        self.finish_edit()
        project = self.project
        dialog = QDialog(self)
        dialog.setWindowTitle("작품 번역 설정")
        dialog.resize(760, 530)
        layout = QVBoxLayout(dialog)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        general = QWidget()
        general_layout = QVBoxLayout(general)
        engine = QComboBox()
        for key, title in ENGINES.items():
            engine.addItem(title, key)
        engine.setCurrentIndex(engine.findData(project.translation_engine))
        form = QFormLayout()
        form.addRow("번역 엔진", engine)
        general_layout.addLayout(form)
        general_layout.addWidget(label("Chrome 내장 번역: Chrome 보조 창에서 번역 준비를 누른 뒤 사용합니다. "
                                       "처음에는 언어팩을 내려받으며 API 키나 구독은 필요하지 않습니다."))
        general_layout.addWidget(label("오프라인 번역: 별도 M2M100 팩 또는 연결한 기존 모델을 사용합니다. "
                                       "엔진을 바꾸어도 기존 번역문은 유지됩니다."))
        general_layout.addWidget(label("오프라인 모델 상태: " + model_packs.status(self.data_dir)))
        general_layout.addWidget(label("번역·지우기 → 오프라인 팩 메뉴에서 팩 ZIP을 설치하거나 기존 모델 폴더를 연결하세요. "
                                       "Chrome 번역에는 이 팩이 필요하지 않습니다."))
        general_layout.addWidget(label("‘검토 완료’한 번역은 이 작품의 확정 번역에 저장됩니다. 같은 원문·화자·문맥의 "
                                       "빈 번역문에 재사용하며, ‘다시 번역해 비교’는 새 엔진 결과를 요청합니다."))
        general_layout.addStretch()
        tabs.addTab(general, "번역")
        glossary_page = QWidget()
        glossary_layout = QVBoxLayout(glossary_page)
        glossary_layout.addWidget(label("인명·장소·단서의 권장 표기를 등록하세요. ‘피할 표기’는 쉼표로 구분합니다. "
                                        "번역 결과의 표기를 확인하고 교체 후보를 제안합니다."))
        glossary = QTableWidget(len(project.glossary), 3)
        glossary.setHorizontalHeaderLabels(["일본어 원문", "한국어 권장 표기", "피할 표기"])
        glossary.horizontalHeader().setStretchLastSection(True)
        glossary.setSelectionBehavior(QAbstractItemView.SelectRows)
        for index, term in enumerate(project.glossary):
            for column, value in enumerate((term["source"], term["target"], ", ".join(term["forbidden"]))):
                glossary.setItem(index, column, QTableWidgetItem(value))
        glossary_layout.addWidget(glossary)
        row = QHBoxLayout()
        add, remove = QPushButton("용어 추가"), QPushButton("선택 삭제")
        def add_term():
            if glossary.rowCount() >= 500:
                return
            index = glossary.rowCount()
            glossary.insertRow(index)
            for column in range(3):
                glossary.setItem(index, column, QTableWidgetItem(""))
            glossary.setCurrentCell(index, 0)
            glossary.editItem(glossary.item(index, 0))
        add.clicked.connect(add_term)
        remove.clicked.connect(lambda: [glossary.removeRow(index) for index in
                                        sorted({item.row() for item in glossary.selectedItems()}, reverse=True)])
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch()
        glossary_layout.addLayout(row)
        tabs.addTab(glossary_page, "용어집")
        memory_page = QWidget()
        memory_layout = QVBoxLayout(memory_page)
        memory_layout.addWidget(label("직접 검토 완료한 번역입니다. 필요 없는 기록은 선택해 삭제할 수 있습니다."))
        memory_rows = deepcopy(project.translation_memory)
        memory = QTableWidget(len(memory_rows), 3)
        memory.setHorizontalHeaderLabels(["원문", "확정 번역", "화자"])
        memory.setEditTriggers(QAbstractItemView.NoEditTriggers)
        memory.setSelectionBehavior(QAbstractItemView.SelectRows)
        memory.horizontalHeader().setStretchLastSection(True)
        for index, entry in enumerate(memory_rows):
            for column, key in enumerate(("source", "target", "speaker")):
                memory.setItem(index, column, QTableWidgetItem(entry[key]))
        memory_layout.addWidget(memory)
        remove_memory = QPushButton("선택한 확정 번역 삭제")
        def delete_memory():
            for index in sorted({item.row() for item in memory.selectedItems()}, reverse=True):
                memory.removeRow(index)
                memory_rows.pop(index)
        remove_memory.clicked.connect(delete_memory)
        memory_layout.addWidget(remove_memory)
        tabs.addTab(memory_page, "확정 번역")
        footer = buttons(dialog)
        layout.addWidget(footer)
        result = {}
        def save():
            entries = []
            for index in range(glossary.rowCount()):
                values = [(glossary.item(index, column).text() if glossary.item(index, column) else "").strip()
                          for column in range(3)]
                if not any(values):
                    continue
                entries.append({"source": values[0], "target": values[1],
                                "forbidden": list(dict.fromkeys(word.strip() for word in values[2].split(",") if word.strip()))})
            try:
                validate_translation_data(engine.currentData(), entries, memory_rows)
            except ValueError as exc:
                QMessageBox.information(dialog, "번역 설정", str(exc))
                return
            result.update(engine=engine.currentData(), glossary=entries, memory=memory_rows)
            dialog.accept()
        footer.accepted.connect(save)
        if dialog.exec() != QDialog.Accepted or self.project is not project:
            return
        self.begin_operation()
        project.translation_engine = result["engine"]
        project.glossary = result["glossary"]
        project.translation_memory = result["memory"]
        if project.translation_engine == "chrome":
            self.translation_service.reset_local()
        self.finish_operation("번역 설정")
        self.status.setText("번역 설정을 저장했습니다 · " + ENGINES[project.translation_engine])

    def edit_translation_context(self):
        self.finish_edit()
        obj = self.current_source()
        if obj is None or self.job or self.comparing or self.effective_locked(obj):
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("화자·문맥·문단 입력")
        dialog.resize(580, 470)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        speaker, context = QLineEdit(obj.speaker), QLineEdit(obj.translation_context)
        speaker.setMaxLength(200)
        context.setMaxLength(2000)
        context.setPlaceholderText("예: 사건 설명 / 레지나의 독백. 비워 두면 앞뒤 원문으로 구분")
        form.addRow("화자", speaker)
        form.addRow("문맥 구분", context)
        layout.addLayout(form)
        layout.addWidget(label("화자와 문맥은 확정 번역 재사용을 구분합니다. Chrome 번역기에 별도 지시문으로 전달되지는 않습니다."))
        join = QCheckBox("상자 안에서 이어지는 원문 줄을 문단으로 연결")
        join.setChecked(obj.join_source_lines)
        layout.addWidget(join)
        layout.addWidget(label("원문은 보존합니다. 표·목록·서식이 복잡한 원문은 줄 연결을 끄고 아래 입력을 확인하세요."))
        preview = QTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(prepare_source(obj.source_text, join.isChecked()))
        join.toggled.connect(lambda checked: preview.setPlainText(prepare_source(obj.source_text, checked)))
        layout.addWidget(preview)
        footer = buttons(dialog)
        footer.accepted.connect(dialog.accept)
        layout.addWidget(footer)
        if dialog.exec() != QDialog.Accepted:
            return
        item = self.items_by_id.get(obj.id)
        if item is None or item.model is not obj or self.effective_locked(obj) or self.comparing:
            return
        self.begin_operation()
        obj.speaker = speaker.text().strip()
        obj.translation_context = context.text().strip()
        obj.join_source_lines = join.isChecked()
        obj.reviewed = False
        obj.candidate_text = obj.candidate_source = obj.candidate_engine = ""
        self.finish_operation("번역 문맥 설정")

    def propose_translation(self, obj, text, engine):
        self.begin_operation()
        obj.candidate_text, obj.candidate_source, obj.candidate_engine = text, obj.source_text, engine
        self.finish_operation("번역 후보 선택")
        self.show_source()

    def choose_memory_translation(self):
        self.finish_edit()
        obj = self.current_source()
        if obj is None or self.job or self.comparing or self.effective_locked(obj):
            return
        entries = memory_suggestions(request_for(self.project, self.current_page, obj), self.project.translation_memory)
        if not entries:
            self.status.setText("비슷한 확정 번역이 없습니다. 번역문을 검토 완료하면 이 작품에 저장됩니다.")
            return
        source, target = obj.source_text, obj.text
        dialog = QDialog(self)
        dialog.setWindowTitle("확정 번역에서 찾기")
        dialog.resize(620, 480)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label("문맥이 다르거나 유사한 원문은 자동 적용하지 않습니다. 선택한 결과를 후보로 확인하세요."))
        listing, preview = QListWidget(), QTextEdit()
        preview.setReadOnly(True)
        for entry in entries:
            tag = "같은 원문·문맥" if entry["exact"] and entry["same_context"] else "다른 문맥" if entry["exact"] else "유사 원문"
            listing.addItem(f"{tag} · {round(entry['score'] * 100)}% · {entry['source'][:70]}")
        def display(index):
            if 0 <= index < len(entries):
                entry = entries[index]
                preview.setPlainText("원문\n" + entry["source"] + "\n\n확정 번역\n" + entry["target"])
        listing.currentRowChanged.connect(display)
        listing.setCurrentRow(0)
        layout.addWidget(listing)
        layout.addWidget(preview)
        footer = buttons(dialog)
        footer.button(QDialogButtonBox.Save).setText("후보로 가져오기")
        footer.accepted.connect(dialog.accept)
        layout.addWidget(footer)
        if dialog.exec() != QDialog.Accepted or listing.currentRow() < 0:
            return
        item = self.items_by_id.get(obj.id)
        if item is not None and item.model is obj and (obj.source_text, obj.text) == (source, target) and not self.effective_locked(obj):
            self.propose_translation(obj, entries[listing.currentRow()]["target"], "memory")

    def suggest_terminology(self):
        self.finish_edit()
        obj = self.current_source()
        if obj is None or self.job or self.comparing or self.effective_locked(obj):
            return
        replacements = {}
        ambiguous = set()
        for term in self.project.glossary:
            if term["source"] not in obj.source_text:
                continue
            for word in term["forbidden"]:
                if word in replacements and replacements[word] != term["target"]:
                    ambiguous.add(word)
                replacements[word] = term["target"]
        for word in ambiguous:
            replacements.pop(word, None)
        if not replacements:
            self.status.setText("용어집에 피할 표기를 등록하면 교체 후보를 만들 수 있습니다.")
            return
        pattern = "|".join(re.escape(word) for word in sorted(replacements, key=len, reverse=True))
        proposed = re.sub(pattern, lambda match: replacements[match.group()], obj.text)
        if proposed == obj.text:
            self.status.setText("교체할 표기가 없습니다 · 권장 표기 누락은 원문·번역 안내에서 확인하세요")
            return
        self.propose_translation(obj, proposed, "glossary")
        self.status.setText("용어 교체 후보입니다 · 뜻과 한국어 조사를 확인한 뒤 적용하세요")
