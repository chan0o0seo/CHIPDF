"""User-selected OCR and brush repairs; original page assets stay untouched."""
from copy import deepcopy
from io import BytesIO

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QComboBox, QFileDialog, QLabel, QSpinBox, QToolBar

from .document_io import png_data
from .model import Paragraph, Project, Run, Style, TextBox
from .recognition import make_erase_patch, recognize_region
from .native_source import prefer_native_source
from .brush_options import BrushOptions


class RegionTools(BrushOptions):
    def init_region_tools(self):
        self.manual_task = None
        self.pdf_background_action = self.action('PDF 원래 배경 적용…', self.choose_pdf_background)
        self.file_menu.addAction(self.pdf_background_action)
        self.select_tool_action = self.action('선택', lambda: self.set_canvas_tool('select'), checkable=True)
        self.region_action = self.action('문장 선택', lambda: self.set_canvas_tool('ocr'), checkable=True)
        self.brush_action = self.action('브러시', lambda: self.set_canvas_tool('brush'), checkable=True)
        self.stamp_action = self.action('도장', lambda: self.set_canvas_tool('stamp'), checkable=True)
        self.tool_actions = {'select': self.select_tool_action, 'ocr': self.region_action,
                             'brush': self.brush_action, 'stamp': self.stamp_action}
        self.tool_action_group = QActionGroup(self)
        self.tool_action_group.setExclusive(True)
        for action in self.tool_actions.values():
            self.tool_action_group.addAction(action)
            self.main_toolbar.insertAction(self.translate_action, action)
        self.region_action.setToolTip('사각형으로 일본어 문장을 선택해 원문을 읽고 빈 입력 상자를 만듭니다.')
        self.brush_action.setToolTip('원본에서 지울 부분을 칠한 뒤 지우기를 누릅니다.')
        self.stamp_action.setToolTip('Alt+클릭으로 배경의 원본 지점을 정하고 드래그해 복제합니다. Ctrl+Z로 한 획을 취소합니다.')
        self.select_tool_action.setChecked(True)
        self.region_bar = QToolBar('선택 범위 도구')
        self.region_bar.setMovable(False)
        self.insertToolBar(self.format_bar, self.region_bar)
        self.orientation_box = QComboBox()
        self.orientation_box.addItems(['가로 원문', '세로 원문'])
        self.orientation_widget = self.region_bar.addWidget(self.orientation_box)
        self.brush_size_box = QSpinBox()
        self.brush_size_box.setRange(4, 256)
        self.brush_size_box.setValue(32)
        self.brush_size_box.setPrefix('브러시 ')
        self.brush_size_box.setSuffix(' px')
        self.brush_size_box.valueChanged.connect(self.canvas.set_brush_size)
        self.brush_size_widget = self.region_bar.addWidget(self.brush_size_box)
        self.init_brush_options()
        self.apply_erase_action = self.action('지우기', self.apply_brush_erase)
        self.cancel_region_action = self.action('선택 취소', self.cancel_region_selection)
        self.region_bar.addActions([self.apply_erase_action, self.cancel_region_action])
        self.stamp_hint_widget = self.region_bar.addWidget(QLabel('Alt+클릭: 원본 지정 · 드래그: 복제 · Ctrl+Z: 한 획 취소'))
        self.canvas.region_selected.connect(self.start_region_ocr)
        self.canvas.brush_selection_changed.connect(lambda _: self.update_region_tools())
        self.canvas.tool_changed.connect(self.canvas_tool_changed)
        self.update_region_tools()

    def set_canvas_tool(self, tool):
        self.finish_edit()
        self.canvas.set_tool(tool)
        self.update_region_tools()
        if tool != 'select' and hasattr(self, 'ribbon_tabs'):
            self.ribbon_tabs.setCurrentIndex(2)
        messages = {'ocr': '일본어 문장을 사각형으로 드래그하세요 · Esc로 취소',
                    'brush': 'Alt+클릭으로 글자색 선택 · 글씨 주변을 칠한 뒤 지우기 · Shift+드래그로 선택 빼기',
                    'stamp': 'Alt+클릭으로 원본 지점을 지정한 뒤 드래그하세요 · 휠 버튼 드래그로 화면 이동',
                    'select': '상자를 선택하거나 더블클릭해서 글자를 입력하세요'}
        if self.project:
            self.status.setText(messages[self.canvas.tool])

    def canvas_tool_changed(self, tool):
        if tool == 'select' and self.manual_task == 'brush' and self.job:
            self.cancel_job()
        self.update_region_tools()

    def update_region_tools(self):
        if not hasattr(self, 'tool_actions'):
            return
        ready = bool(self.project) and not self.comparing
        idle = not self.job and not getattr(self, 'io_job', None)
        self.pdf_background_action.setEnabled(ready and idle)
        tool = self.canvas.tool
        for name, action in self.tool_actions.items():
            action.setEnabled(ready and idle)
            action.setChecked(name == tool)
        self.region_bar.setVisible(ready and tool != 'select' and not hasattr(self, 'ribbon_tabs'))
        self.orientation_widget.setVisible(tool == 'ocr')
        self.orientation_box.setEnabled(idle)
        self.brush_size_widget.setVisible(tool in ('brush', 'stamp'))
        self.brush_size_box.setPrefix('도장 크기 ' if tool == 'stamp' else '브러시 ')
        self.brush_size_box.setEnabled(idle)
        for widget in (self.brush_mode_box, self.erase_engine_box):
            widget.setVisible(tool == 'brush')
            widget.setEnabled(ready and idle)
        self.erase_settings_action.setEnabled(ready and idle)
        self.erase_mask_action.setEnabled(ready and idle and self.canvas._has_brush_selection)
        self.stamp_hint_widget.setVisible(tool == 'stamp')
        self.apply_erase_action.setVisible(tool == 'brush')
        self.apply_erase_action.setEnabled(ready and idle and self.canvas._has_brush_selection)
        self.cancel_region_action.setEnabled(ready)
        self.cancel_region_action.setText('도장 끝내기' if tool == 'stamp' else '선택 취소')
        self.update_ribbon_region()

    def cancel_region_selection(self):
        if self.manual_task and self.job:
            self.cancel_job()
        self.canvas.cancel_tool()
        self.status.setText('선택 취소됨 · 작업 내용은 유지됩니다')

    def choose_pdf_background(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '작업에 사용한 원본 PDF 선택', '', 'PDF (*.pdf)')
        if paths:
            self.start_pdf_background_repair(paths)

    def start_pdf_background_repair(self, paths):
        if not self.project or self.job or self.comparing:
            return
        from .pdf_repair import prepare_pdf_repair
        self.finish_edit()
        self.canvas.cancel_tool()
        snapshot, assets = deepcopy(self.project), dict(self.assets)
        selected = [item.model.id for item in self.selected()]
        def accept(result):
            self.finish_edit()
            if self.project != snapshot:
                self.status.setText('처리 중 편집 내용이 바뀌었습니다 · PDF 원래 배경 적용을 다시 실행해 주세요')
                return
            project, updated_assets, pages, regions = result
            self.begin_operation()
            self.project, self.assets = project, updated_assets
            self.background_signature = None
            self.rebuild_scene(selected)
            self.refresh_card_list()
            self.finish_operation('PDF 원래 배경 적용')
            self.autosave()
            self.status.setText(f'원래 PDF 배경 적용 · {pages}장 · 원문 {regions}개 · 기존 번역문과 배치 유지')
        self.launch_job(lambda cancel, progress: prepare_pdf_repair(snapshot, assets, paths, cancel.is_set, progress), accept)

    def start_region_ocr(self, rect: QRectF):
        if not self.project or self.job or self.comparing:
            return
        if rect.width() < 24 or rect.height() < 24 or rect.width()*rect.height() > 600_000:
            self.status.setText('문장 범위를 너무 작거나 크게 잡았습니다 · 작은 문장 단위로 선택해 주세요')
            return
        if len(self.current_page.objects) >= 2000:
            self.status.setText('이 카드에는 상자를 더 추가할 수 없습니다')
            return
        self.finish_edit()
        original = self.original
        clean = self.assets.get(getattr(self.current_page, 'clean_asset', ''))
        bounds = [rect.x(), rect.y(), rect.width(), rect.height()]
        vertical = self.orientation_box.currentIndex() == 1
        self.manual_task = 'ocr'
        native_chars = deepcopy(self.current_page.native_chars)
        def read(cancelled, progress):
            region = recognize_region(original, bounds, cancelled, progress, vertical,
                                      **({'clean_background': clean} if clean else {}))
            return prefer_native_source(region, native_chars)
        self.launch_job(read, self.accept_manual_region)

    def accept_manual_region(self, region):
        self.manual_task = None
        if len(self.current_page.objects) >= 2000:
            self.status.setText('이 카드에는 상자를 더 추가할 수 없습니다')
            return
        self.finish_edit()
        x, y, width, height = region.rect
        obj = TextBox(x=x, y=y, width=width, height=height, margin=2,
                      z=max((o.z for o in self.current_page.objects), default=-1)+1,
                      paragraphs=[Paragraph([Run('', Style(size=max(9, min(28, region.line_height*.68))))])],
                      source_text=region.text, source_rect=list(region.rect),
                      source_method=region.source_method,
                      confidence=max(0, min(100, region.confidence)), erase_when_empty=True,
                      erase_rect=region.erase_rect, erase_patch=region.patch, erase_mask=region.mask)
        self.begin_operation()
        self.active_group_id = ''
        self.current_page.objects.append(obj)
        self.rebuild_scene([obj.id])
        self.finish_operation('문장 선택')
        self.autosave()
        self.show_source()
        self.canvas.setFocus(Qt.OtherFocusReason)
        self.items_by_id[obj.id].begin_edit()
        self.status.setText('원문 확인 후 한국어를 입력하거나 번역을 누르세요' if region.text else
                            '문장을 읽지 못했습니다 · 원문 수정에서 일본어를 입력하거나 한국어를 직접 입력하세요')

    def translate_selection(self):
        if not self.project or self.job or self.comparing:
            return
        self.finish_edit()
        obj = self.current_source()
        if obj is None:
            self.status.setText('번역할 문장 상자를 먼저 선택해 주세요')
        elif not obj.source_text.strip():
            self.show_source()
            self.status.setText('읽은 일본어가 없습니다 · 원문 수정에서 입력해 주세요')
        elif not self.effective_locked(obj):
            self.start_translation([obj], candidates=bool(obj.text.strip()))

    def apply_brush_erase(self):
        if not self.project or self.job or self.comparing or self.canvas.tool != 'brush':
            return
        mask = self.canvas.brush_mask_image()
        if mask.isNull():
            self.status.setText('브러시로 지울 부분을 먼저 칠해 주세요')
            return
        if len(self.current_page.background_patches) >= 2000:
            self.status.setText('이 카드의 지우기 기록이 너무 많습니다')
            return
        self.finish_edit()
        self.refresh_background()
        original = png_data(self.background_image if not self.background_image.isNull() else self.image)
        background = self.background_image if not self.background_image.isNull() else self.image
        try:
            selected = self.brush_erase_mask(background, mask)
            if hasattr(selected, 'isNull'):
                mask_png = png_data(selected)
            else:
                if not selected.getbbox():
                    self.status.setText('선택한 색의 글씨가 없습니다 · Alt+클릭으로 글자색을 고르세요')
                    return
                stream = BytesIO()
                selected.save(stream, 'PNG')
                mask_png = stream.getvalue()
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))
            return
        options = dict(self.erase_options)
        clean = self.assets.get(getattr(self.current_page, 'clean_asset', ''))
        native_original = self.original
        signature = self.background_signature
        self.manual_task = 'brush'
        def accept(patch):
            self.refresh_background()
            if self.background_signature != signature:
                self.status.setText('처리 중 배경이 바뀌었습니다 · 선택을 유지했으니 지우기를 다시 눌러 주세요')
                return
            self.accept_brush_erase(patch)
        self.launch_job(lambda cancelled, progress: make_erase_patch(original, mask_png, cancelled, progress,
                            engine=options['engine'], model_path=options['model_path'] or None,
                            **({'clean_background': clean, 'native_original': native_original} if clean else {})),
                        accept)

    def accept_brush_erase(self, patch):
        self.manual_task = None
        # Validate the proposed state before adding anything to the live history.
        trial = deepcopy(self.project)
        trial.pages[self.page_index].background_patches.append(patch)
        Project.from_dict(trial.to_dict())
        self.begin_operation()
        self.current_page.background_patches.append(patch)
        self.background_signature = None
        self.canvas.clear_tool_selection()
        self.refresh_background()
        self.finish_operation('브러시 지우기')
        self.autosave()
        self.status.setText('선택한 부분을 지웠습니다 · Ctrl+Z로 되돌릴 수 있습니다')
