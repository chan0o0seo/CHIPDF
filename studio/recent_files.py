"""Persistent recent work, including recoverable edits of imported sources."""
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QPushButton

from .storage import atomic_write


RECENT_LIMIT = 12


def read_recent(path):
    try:
        values = json.loads(path.read_text('utf-8'))
        if isinstance(values, dict):  # Migrate the previous single-file record.
            values = [values]
        if not isinstance(values, list):
            return []
        result, seen = [], set()
        for entry in values:
            if not isinstance(entry, dict) or not isinstance(entry.get('path'), str) or not entry['path'].strip():
                continue
            try:
                file = Path(entry['path']).resolve()
            except (OSError, ValueError):
                continue
            if file in seen:
                continue
            seen.add(file)
            name = entry.get('name')
            result.append({'path': str(file), 'name': name if isinstance(name, str) and name else file.name})
            if len(result) == RECENT_LIMIT:
                break
        return result
    except (OSError, ValueError):
        return []


class RecentFiles:
    def init_recent_files(self, layout):
        self.recent_files = read_recent(self.data_dir / 'recent.json')
        self.recent_menu = self.file_menu.addMenu('최근 작업 열기')
        self.file_menu.insertMenu(self.save_action, self.recent_menu)
        self.recent_menu.aboutToShow.connect(self.refresh_recent_files)
        title = QLabel('최근 편집한 작업')
        title.setProperty('role', 'title')
        layout.addWidget(title)
        self.recent_list = QListWidget()
        self.recent_list.setAccessibleName('최근 편집한 작업')
        self.recent_list.setMinimumHeight(140)
        self.recent_list.setMaximumHeight(200)
        self.recent_list.setTextElideMode(Qt.ElideMiddle)
        self.recent_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.recent_list.itemActivated.connect(lambda item: self.open_recent_path(item.data(Qt.UserRole)))
        layout.addWidget(self.recent_list)
        self.recent_open_button = QPushButton('선택한 작업 불러오기')
        self.recent_open_button.clicked.connect(self.open_selected_recent)
        self.recent_list.currentItemChanged.connect(self.update_recent_open_button)
        layout.addWidget(self.recent_open_button, alignment=Qt.AlignCenter)
        self.refresh_recent_files()

    def update_recent_open_button(self, *args):
        item = self.recent_list.currentItem()
        self.recent_open_button.setEnabled(bool(item and item.flags() & Qt.ItemIsEnabled and item.data(Qt.UserRole)))

    def refresh_recent_files(self):
        current = self.recent_list.currentItem()
        selected = current.data(Qt.UserRole) if current else None
        self.recent_menu.clear()
        self.recent_list.clear()
        for entry in self.recent_files:
            path = Path(entry['path'])
            exists = path.is_file()
            recovery = path.parent == (self.data_dir / 'recovery').resolve()
            label = entry['name'] + (' · 자동 저장' if recovery else '')
            if not exists:
                label += ' · 파일 없음'
            short_path = self.fontMetrics().elidedText(str(path), Qt.ElideMiddle, 420)
            action = self.recent_menu.addAction((label + ' — ' + short_path).replace('&', '&&'))
            action.setToolTip(str(path))
            action.setEnabled(exists)
            action.triggered.connect(lambda checked=False, p=str(path): self.open_recent_path(p))
            item = QListWidgetItem(label + '\n' + str(path))
            item.setData(Qt.UserRole, str(path))
            item.setToolTip(str(path))
            if not exists:
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.recent_list.addItem(item)
            if str(path) == selected and exists:
                self.recent_list.setCurrentItem(item)
        if not self.recent_files:
            self.recent_menu.addAction('최근 작업이 없습니다').setEnabled(False)
            empty = QListWidgetItem('최근 작업이 없습니다. 파일을 열어 편집을 시작하세요.')
            empty.setFlags(Qt.NoItemFlags)
            self.recent_list.addItem(empty)
        self.update_recent_open_button()

    def remember_recent(self, path, replace_path=None):
        path = Path(path).resolve()
        replaced = Path(replace_path).resolve() if replace_path else None
        recovery = path.parent == (self.data_dir / 'recovery').resolve()
        entry = {'path': str(path), 'name': self.project.name if recovery else path.name}
        self.recent_files = [entry] + [old for old in self.recent_files
                                     if Path(old['path']) not in (path, replaced)]
        self.recent_files = self.recent_files[:RECENT_LIMIT]
        try:
            atomic_write(self.data_dir / 'recent.json',
                         json.dumps(self.recent_files, ensure_ascii=False).encode('utf-8'))
        except OSError:
            # A history failure must not turn a successful document save into a failure.
            self.statusBar().showMessage('최근 작업 목록을 저장하지 못했습니다. 이번 실행에만 반영됩니다.', 8000)
        self.refresh_recent_files()

    def open_selected_recent(self):
        item = self.recent_list.currentItem()
        if item:
            self.open_recent_path(item.data(Qt.UserRole))

    def open_recent_path(self, path):
        if not path:
            return
        if not Path(path).is_file():
            self.refresh_recent_files()
            self.status.setText('파일을 찾을 수 없습니다 · 이동한 파일은 열기에서 다시 선택해 주세요')
            return
        self.open_path(path)
