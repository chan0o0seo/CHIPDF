"""Text-box page links and explicit recovery for older raster-only projects."""
from copy import deepcopy

from PySide6.QtWidgets import QInputDialog, QFileDialog

from .model import TextBox


class LinkTools:
    def init_link_tools(self):
        self.page_link_action = self.action('페이지 링크…', self.choose_page_link)
        self.page_link_action.setToolTip('선택한 텍스트 상자에 PDF 내부 페이지 이동 링크를 설정합니다.')
        self.text_format_menu.addSeparator()
        self.text_format_menu.addAction(self.page_link_action)
        self.restore_links_action = self.action('PDF 내부 링크 복원…', self.choose_link_repair)
        self.file_menu.addAction(self.restore_links_action)
        self.update_link_tools()

    def update_link_tools(self):
        if not hasattr(self, 'page_link_action'):
            return
        items = self.mutable_selection()
        self.page_link_action.setEnabled(len(items) == 1 and isinstance(items[0].model, TextBox))
        self.restore_links_action.setEnabled(bool(self.project) and not self.comparing and not self.job and not self.io_job)

    def set_page_link(self, mode, target=''):
        self.finish_edit()
        items = self.mutable_selection()
        if len(items) != 1 or not isinstance(items[0].model, TextBox):
            return
        if mode not in ('auto', 'none', 'page') or (mode == 'page' and target not in {p.id for p in self.project.pages}):
            raise ValueError('이동할 페이지를 선택해 주세요.')
        self.begin_operation()
        items[0].model.link_mode = mode
        items[0].model.link_page_id = target if mode == 'page' else ''
        self.finish_operation('페이지 링크')
        self.status.setText('페이지 링크 저장됨 · 완성본을 PDF로 저장하면 클릭해서 이동할 수 있습니다')

    def choose_page_link(self):
        if hasattr(self, 'inspector'):
            self.show_inspector('links')
            return
        self.finish_edit()
        items = self.mutable_selection()
        if len(items) != 1 or not isinstance(items[0].model, TextBox):
            return
        obj = items[0].model
        choices = ['원본 링크 자동 유지', '이 상자 링크 없음'] + [f'{i+1}페이지 · {p.name}' for i, p in enumerate(self.project.pages)]
        current = 0 if obj.link_mode == 'auto' else 1
        if obj.link_mode == 'page':
            current = next((i+2 for i, p in enumerate(self.project.pages) if p.id == obj.link_page_id), 0)
        choice, ok = QInputDialog.getItem(self, '페이지 링크',
            '이 텍스트 상자를 클릭하면 이동할 페이지\nPDF 출력에서 적용됩니다. 자동 유지는 문장 선택 영역의 원본 링크를 따릅니다.\n서로 다른 링크는 문장별 상자로 나누면 정확합니다.', choices, current, False)
        if ok:
            index = choices.index(choice)
            self.set_page_link('auto' if index == 0 else 'none' if index == 1 else 'page',
                               self.project.pages[index-2].id if index >= 2 else '')

    def choose_link_repair(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '작업에 사용한 원본 PDF 선택', '', 'PDF (*.pdf)')
        if paths:
            self.start_link_repair(paths)

    def start_link_repair(self, paths):
        if not self.project or self.job or self.io_job or self.comparing:
            return
        from .pdf_links import prepare_link_repair
        self.finish_edit()
        snapshot, assets = deepcopy(self.project), dict(self.assets)
        selected = [i.model.id for i in self.selected()]
        def accept(result):
            self.finish_edit()
            if self.project != snapshot:
                self.status.setText('처리 중 작업이 바뀌었습니다 · PDF 내부 링크 복원을 다시 실행해 주세요')
                return
            trial, count = result
            self.begin_operation()
            self.project = trial
            self.rebuild_scene(selected)
            self.finish_operation('PDF 내부 링크 복원')
            self.autosave()
            self.status.setText(f'PDF 내부 링크 {count}개 복원됨 · 번역문과 배치 유지 · PDF 출력에 적용')
        self.launch_job(lambda cancel, progress: prepare_link_repair(snapshot, assets, paths, cancel.is_set, progress), accept)
