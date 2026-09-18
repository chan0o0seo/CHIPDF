"""One canvas, a page list, and document-wide persistence and output."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QSize, Qt, QThreadPool, QTimer
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox,
                              QFileDialog, QFormLayout, QFrame, QLabel, QListView, QListWidgetItem,
                              QProgressDialog, QVBoxLayout)

from .document_io import Cancelled, export_collection, folder_images, import_files, render_page
from .jobs import Job
from .model import Project
from .storage import atomic_write, validate_asset_sizes
from .ui.page_list import PAGE_NAME_ROLE, PAGE_NUMBER_ROLE, PageThumbnailDelegate
from . import APP_NAME


class Collection:
    @property
    def current_page(self):
        return self.project.pages[self.page_index]

    def init_collection(self):
        self.io_job = None
        self.io_pool = QThreadPool(self)
        self.io_pool.setMaxThreadCount(1)
        self.pages_pending_ocr = set()
        self.thumbnail_queue = []
        self.thumbnail_timer = QTimer(self)
        self.thumbnail_timer.setInterval(35)
        self.thumbnail_timer.timeout.connect(self.next_thumbnail)
        self.card_list.setObjectName('pageList')
        self.card_list.setViewMode(QListView.ListMode)
        self.card_list.setFlow(QListView.TopToBottom)
        self.card_list.setWrapping(False)
        self.card_list.setResizeMode(QListView.Adjust)
        self.card_list.setMovement(QListView.Static)
        self.card_list.setSpacing(2)
        self.card_list.setUniformItemSizes(True)
        self.card_list.setMouseTracking(True)
        self.card_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.card_list.setItemDelegate(PageThumbnailDelegate(self.card_list))
        self.card_list.setAccessibleName('문서 페이지 목록')
        self.card_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.card_list.currentRowChanged.connect(self.switch_page)
        self.folder_action = self.action('이미지 폴더 열기…', self.choose_folder)
        self.append_action = self.action('자료 추가…', lambda: self.choose_sources(append=True))
        self.file_menu.insertAction(self.save_action, self.folder_action)
        self.file_menu.insertAction(self.save_action, self.append_action)
        self.action('다음 카드', lambda: self.switch_page(self.page_index+1), 'Ctrl+PgDown')
        self.action('이전 카드', lambda: self.switch_page(self.page_index-1), 'Ctrl+PgUp')

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, '이미지 폴더 열기')
        if path:
            self.open_sources([path])

    def choose_sources(self, append=False):
        paths, _ = QFileDialog.getOpenFileNames(self, '자료 추가' if append else '자료 열기', '',
                    '자료 (*.pdf *.png *.jpg *.jpeg *.bmp)' if append else '자료 (*.pdf *.png *.jpg *.jpeg *.bmp *.twproj *.twproj.bak)')
        if paths:
            self.open_sources(paths, append=append)

    def open_sources(self, paths, append=False):
        if self.io_job:
            return
        self.finish_edit()
        dialog = QProgressDialog('자료 준비 중…', '중단', 0, 0, self)
        dialog.setWindowTitle('자료 가져오기')
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        job = Job(lambda cancelled, progress: import_files(paths, cancelled.is_set, progress))
        self.io_job = job
        dialog.canceled.connect(job.cancelled.set)
        job.signals.progress.connect(dialog.setLabelText, Qt.QueuedConnection)
        def complete(result):
            stopped = result['cancelled'] or job.cancelled.is_set()
            self.io_job = None
            dialog.reset()
            dialog.deleteLater()
            if stopped:
                self.status.setText('가져오기 중단됨 · 기존 작업 유지')
                return
            try:
                if result['error']:
                    raise ValueError(result['error'])
                self.install_collection(*result['value'], append=append)
            except (ValueError, OSError) as exc:
                self.report_error('자료를 열지 못했습니다', exc)
        job.signals.finished.connect(complete, Qt.QueuedConnection)
        dialog.show()
        self.io_pool.start(job)

    def install_collection(self, project, assets, project_file=None, append=False):
        self.finish_edit()
        if append and self.project:
            if project_file:
                raise ValueError('추가할 이미지 또는 PDF를 선택해 주세요.')
            trial = deepcopy(self.project)
            first = len(trial.pages)
            incoming_pages = deepcopy(project.pages)
            retained_chars = sum(len(page.native_chars) for page in trial.pages)
            for page in incoming_pages:
                if retained_chars + len(page.native_chars) > 200000:
                    page.native_chars = []
                retained_chars += len(page.native_chars)
            trial.pages.extend(incoming_pages)
            Project.from_dict(trial.to_dict())
            used = {key for p in trial.pages for key in (p.asset, p.clean_asset) if key}
            merged = {**self.assets, **assets}
            validate_asset_sizes(trial, merged)
            if sum(len(merged[key]) for key in used) > 512_000_000:
                raise ValueError('작품 원본 용량이 512MB를 넘습니다.')
            self.begin_operation()
            self.invalidate_jobs()
            self.project, self.assets = trial, merged
            if self.auto_ocr:
                self.pages_pending_ocr.update(p.id for p in project.pages)
            self.activate_page(first)
            self.refresh_card_list()
            self.finish_operation('자료 추가')
            self.queue_current_ocr()
            if not self.auto_ocr:
                self.set_canvas_tool('ocr')
            return
        if self.dirty and not self.autosave():
            raise OSError('현재 작업 저장이 실패했습니다. 다른 이름으로 저장한 뒤 다시 열어 주세요.')
        self.invalidate_jobs()
        self.loading = True
        self.project, self.assets = project, assets
        path = Path(project_file).resolve() if project_file else None
        self.project_path = None if path is None or path.suffix == '.bak' or path.parent == self.data_dir / 'recovery' else path
        self.operation_before = None
        self.undo_stack.clear()
        self.pages_pending_ocr = {p.id for p in project.pages if not p.ocr_done} if self.auto_ocr and path is None else set()
        self.activate_page(0)
        self.refresh_card_list()
        self.center.setCurrentWidget(self.canvas)
        self.dirty = self.project_path is None
        if self.dirty:
            self.autosave()
        else:
            atomic_write(self.data_dir / 'recent.json', json.dumps({'path': str(self.project_path)}, ensure_ascii=False).encode('utf-8'))
            self.status.setText(f'작품 열림 · {len(project.pages)}장')
        self.queue_current_ocr()

        if not self.auto_ocr and project_file is None:
            self.set_canvas_tool('ocr')

    def activate_page(self, index, selection=(), keep_scope=False, fit_view=True):
        tool = self.canvas.tool if not fit_view else 'select'
        self.canvas.cancel_tool()
        self.page_index = index
        page = self.current_page
        self.original = self.assets[page.asset]
        self.image = QImage.fromData(self.original, 'PNG')
        self.source_path = Path(page.source_file).resolve() if page.source_file else None
        if not keep_scope or not any(o.id == self.active_group_id for o in page.objects):
            self.active_group_id = ''
        self.comparing = False
        self.compare_action.setChecked(False)
        self.background_signature = None
        self.rebuild_scene(selection)
        self.canvas.set_tool(tool)
        self.setWindowTitle(f'{self.project.name} · {index+1}/{len(self.project.pages)} — {APP_NAME}')
        if fit_view:
            context = (self.project.id, page.id)
            def fit_current_page():
                if self.project and (self.project.id, self.current_page.id) == context:
                    self.canvas.fit_page()
            QTimer.singleShot(0, fit_current_page)

    def queue_current_ocr(self):
        self.pending_ocr = self.current_page.id in self.pages_pending_ocr and not self.current_page.ocr_done
        if self.pending_ocr:
            QTimer.singleShot(0, self.start_pending_ocr)

    def switch_page(self, index):
        if not self.project or not 0 <= index < len(self.project.pages) or index == self.page_index or self.loading:
            return
        self.finish_edit()
        self.sync_positions()
        self.update_thumbnail(self.page_index, edited=True)
        self.invalidate_jobs()
        self.activate_page(index)
        if self.card_list.currentRow() != index:
            self.card_list.blockSignals(True)
            self.card_list.setCurrentRow(index)
            self.card_list.blockSignals(False)
        self.status.setText(f'{index+1}/{len(self.project.pages)} · {self.current_page.name}')
        self.queue_current_ocr()

    def refresh_card_list(self):
        self.card_list.blockSignals(True)
        self.card_list.clear()
        for index, page in enumerate(self.project.pages):
            entry = QListWidgetItem(f'{index+1}. {page.name}')
            entry.setData(PAGE_NUMBER_ROLE, index+1)
            entry.setData(PAGE_NAME_ROLE, page.name)
            entry.setData(Qt.AccessibleDescriptionRole, f'{index+1}페이지 · {page.name}')
            entry.setTextAlignment(Qt.AlignHCenter)
            entry.setToolTip(f'{index+1}페이지 · {page.name}')
            entry.setSizeHint(QSize(164, 178))
            self.card_list.addItem(entry)
        self.card_list.setCurrentRow(self.page_index)
        self.card_list.blockSignals(False)
        self.update_thumbnail(self.page_index, edited=True)
        self.thumbnail_queue = [i for i in range(len(self.project.pages)) if i != self.page_index]
        self.thumbnail_timer.start()

    def next_thumbnail(self):
        if not self.thumbnail_queue:
            self.thumbnail_timer.stop()
            return
        self.update_thumbnail(self.thumbnail_queue.pop(0), edited=True)

    def update_thumbnail(self, index, edited=False):
        if not self.project or not 0 <= index < self.card_list.count():
            return
        page = self.project.pages[index]
        image = render_page(deepcopy(page), self.assets[page.asset]) if edited and (page.objects or page.background_patches) else QImage.fromData(self.assets[page.asset], 'PNG')
        self.card_list.item(index).setIcon(QIcon(QPixmap.fromImage(image).scaled(140, 125, Qt.KeepAspectRatio, Qt.SmoothTransformation)))

    def check_output_path(self, path):
        path = Path(path).resolve()
        protected = {Path(p.source_file).resolve() for p in self.project.pages if p.source_file}
        protected.update(p for p in (self.source_path, self.project_path) if p)
        if path in protected:
            raise ValueError('원본과 작업 파일은 보존합니다. 다른 이름으로 저장해 주세요.')
        return path

    def export_pages(self, path, indices, kind, cancel=None, progress=lambda value: None):
        self.finish_edit()
        self.sync_positions()
        path = self.check_output_path(path)
        return export_collection(self.project, self.assets, indices, path, kind, cancel, progress)

    def choose_collection_export(self):
        if not self.project:
            return
        self.finish_edit()
        selected = sorted(self.card_list.row(item) for item in self.card_list.selectedItems())
        dialog = QDialog(self)
        dialog.setWindowTitle('완성본 저장')
        dialog.setMinimumWidth(430)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(16)
        heading = QLabel('편집한 문서를 저장하세요')
        heading.setObjectName('dialogTitle')
        layout.addWidget(heading)
        description = QLabel(self.project.name)
        description.setObjectName('secondaryText')
        description.setWordWrap(True)
        layout.addWidget(description)
        form = QFormLayout()
        form.setHorizontalSpacing(20)
        form.setVerticalSpacing(12)
        scope = QComboBox()
        scope.setAccessibleName('저장할 페이지 범위')
        scope.addItem(f'전체 페이지 ({len(self.project.pages)}장)', list(range(len(self.project.pages))))
        scope.addItem(f'현재 페이지 ({self.page_index+1}페이지)', [self.page_index])
        if selected:
            scope.addItem(f'선택한 페이지 ({len(selected)}장)', selected)
        kind = QComboBox()
        kind.setAccessibleName('완성본 파일 형식')
        kind.addItem('PNG 이미지', 'png')
        kind.addItem('PDF 문서', 'pdf')
        form.addRow('저장 범위', scope)
        form.addRow('파일 형식', kind)
        layout.addLayout(form)

        summary_card = QFrame()
        summary_card.setObjectName('infoCard')
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        summary_layout.setSpacing(8)
        count_label = QLabel()
        count_label.setObjectName('exportSummary')
        summary_layout.addWidget(count_label)
        note = QLabel()
        note.setObjectName('secondaryText')
        note.setWordWrap(True)
        summary_layout.addWidget(note)
        layout.addWidget(summary_card)
        project_note = QLabel('계속 편집할 작업은 파일 → 작업 저장에서 .twproj로 보관하세요.')
        project_note.setObjectName('secondaryText')
        project_note.setWordWrap(True)
        layout.addWidget(project_note)

        def update_summary():
            count = len(scope.currentData())
            if kind.currentData() == 'pdf':
                count_label.setText(f'{count}페이지 · PDF 파일 1개')
                note.setText('현재 모습과 내부 페이지 링크를 함께 저장합니다.\n'
                             '저장 범위에 포함되지 않은 페이지로 가는 링크는 제외됩니다.')
            else:
                count_label.setText(f'{count}페이지 · PNG 이미지 {count}개')
                note.setText('페이지마다 이미지로 저장합니다. PNG에는 페이지 링크가 포함되지 않습니다.'
                             + ('\n여러 이미지는 새 폴더에 함께 저장합니다.' if count > 1 else ''))
        scope.currentIndexChanged.connect(update_summary)
        kind.currentIndexChanged.connect(update_summary)
        update_summary()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('저장 위치 선택')
        buttons.button(QDialogButtonBox.Ok).setObjectName('primaryButton')
        buttons.button(QDialogButtonBox.Ok).setDefault(True)
        buttons.button(QDialogButtonBox.Cancel).setText('취소')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        indices, format_name = scope.currentData(), kind.currentData()
        if format_name == 'pdf':
            destination, _ = QFileDialog.getSaveFileName(self, 'PDF 완성본 저장', self.project.name+'_번역.pdf', 'PDF 문서 (*.pdf)')
            if destination and not destination.lower().endswith('.pdf'):
                destination += '.pdf'
        elif len(indices) == 1:
            destination, _ = QFileDialog.getSaveFileName(self, 'PNG 완성본 저장', f'{indices[0]+1:03d}_번역.png', 'PNG 이미지 (*.png)')
            if destination:
                if not destination.lower().endswith('.png'):
                    destination += '.png'
                try:
                    from .document_io import png_data
                    path = self.check_output_path(destination)
                    atomic_write(path, png_data(render_page(deepcopy(self.project.pages[indices[0]]), self.assets[self.project.pages[indices[0]].asset])))
                    self.status.setText('완성본 저장됨 · '+path.name)
                except (OSError, ValueError) as exc:
                    self.report_error('완성본 저장 실패', exc)
            return
        else:
            directory = QFileDialog.getExistingDirectory(self, 'PNG 묶음을 저장할 위치')
            destination = Path(directory) / ('번역카드_'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:4]) if directory else None
        if not destination:
            return
        progress = QProgressDialog('완성본 만드는 중…', '중단', 0, len(indices), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        def advance(value):
            progress.setValue(value)
            progress.setLabelText(f'완성본 만드는 중 · {value}/{len(indices)}')
            QApplication.processEvents()
        try:
            self.export_pages(destination, indices, format_name, progress.wasCanceled, advance)
            self.status.setText(f'완성본 {len(indices)}장 저장됨 · {Path(destination).name}')
        except Cancelled as exc:
            self.status.setText(str(exc))
        except (OSError, ValueError) as exc:
            self.report_error('완성본 저장 실패', exc)
        finally:
            progress.close()
