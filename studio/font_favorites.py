"""Personal font shortcuts, shared across projects and saved independently."""
import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QMenu, QToolButton

from .storage import atomic_write
from .model import TextBox


class FontFavorites:
    def init_font_favorites(self):
        self.font_favorites_path = self.data_dir / 'font-favorites.json'
        self.font_favorites = []
        self.font_favorites_load_error = None
        try:
            if self.font_favorites_path.exists():
                if self.font_favorites_path.stat().st_size > 1_000_000:
                    raise ValueError('글꼴 즐겨찾기 파일이 너무 큽니다.')
                value = json.loads(self.font_favorites_path.read_text('utf-8'))
                if (not isinstance(value, list) or
                        any(not isinstance(name, str) or not name.strip() or len(name) > 256
                            for name in value)):
                    raise ValueError('글꼴 즐겨찾기 파일 형식이 올바르지 않습니다.')
                self.font_favorites = sorted(set(value), key=str.casefold)
        except (OSError, ValueError) as exc:
            self.font_favorites_load_error = str(exc)
            self.status.setText('글꼴 즐겨찾기를 읽지 못했습니다 · 기존 파일을 보존합니다')

        self.font_favorite_action = self.action('☆', self.toggle_font_favorite, checkable=True)
        self.font_favorite_action.setIconText('☆')
        self.font_favorites_menu = QMenu('글꼴 즐겨찾기', self)
        self.font_favorites_menu.aboutToShow.connect(self.populate_font_favorites_menu)
        self.font_favorites_button = QToolButton()
        self.font_favorites_button.setText('즐겨찾기')
        self.font_favorites_button.setToolTip('저장한 글꼴을 선택해 적용합니다')
        self.font_favorites_button.setFocusPolicy(Qt.NoFocus)
        self.font_favorites_button.setPopupMode(QToolButton.InstantPopup)
        self.font_favorites_button.setMenu(self.font_favorites_menu)
        # Keep both shortcuts immediately beside the existing font picker.
        before_action = next(action for action in self.format_bar.actions()
                             if self.format_bar.widgetForAction(action) is self.size_box)
        self.format_bar.insertAction(before_action, self.font_favorite_action)
        self.format_bar.insertWidget(before_action, self.font_favorites_button)
        self.text_format_menu.addMenu(self.font_favorites_menu)
        self.font_box.currentFontChanged.connect(self.update_font_favorite)
        self.update_font_favorite()

    def update_font_favorite(self):
        if not hasattr(self, 'font_favorite_action'):
            return
        family = self.font_box.currentFont().family()
        saved = family in self.font_favorites
        self.font_favorite_action.setChecked(saved)
        self.font_favorite_action.setText('★' if saved else '☆')
        self.font_favorite_action.setIconText('★' if saved else '☆')
        self.font_favorite_action.setToolTip(
            f'{family} · 즐겨찾기에서 삭제' if saved else f'{family} · 즐겨찾기에 추가')
        self.font_favorite_action.setEnabled(bool(family) and not self.font_favorites_load_error)

    def toggle_font_favorite(self):
        family = self.font_box.currentFont().family()
        self.set_font_favorite(family, family not in self.font_favorites)

    def set_font_favorite(self, family, enabled):
        if not family or self.font_favorites_load_error:
            self.update_font_favorite()
            return
        updated = set(self.font_favorites)
        if enabled:
            updated.add(family)
        else:
            updated.discard(family)
        updated = sorted(updated, key=str.casefold)
        try:
            atomic_write(self.font_favorites_path,
                         json.dumps(updated, ensure_ascii=False, indent=2).encode('utf-8'))
        except OSError as exc:
            self.status.setText(f'글꼴 즐겨찾기를 저장하지 못했습니다 · {exc}')
        else:
            self.font_favorites = updated
            self.status.setText(f'{family} · 즐겨찾기에 추가됨' if enabled else f'{family} · 즐겨찾기에서 삭제됨')
        self.update_font_favorite()

    def populate_font_favorites_menu(self):
        menu = self.font_favorites_menu
        menu.clear()
        if not self.font_favorites:
            action = menu.addAction('글꼴 옆 ☆를 눌러 즐겨찾기에 추가하세요')
            action.setEnabled(False)
            return
        installed = set(QFontDatabase.families())
        selected = self.mutable_selection()
        can_apply = (bool(selected) and not self.comparing and
                     all(isinstance(item.model, TextBox) for item in selected))
        for family in self.font_favorites:
            available = family in installed
            action = menu.addAction(family if available else f'{family} (설치되지 않음)')
            action.setFont(QFont(family))
            action.setEnabled(available and can_apply)
            action.triggered.connect(lambda checked=False, name=family: self.apply_favorite_font(name))
        menu.addSeparator()
        remove_menu = menu.addMenu('즐겨찾기에서 삭제')
        for family in self.font_favorites:
            action = remove_menu.addAction(family)
            action.triggered.connect(lambda checked=False, name=family: self.set_font_favorite(name, False))

    def apply_favorite_font(self, family):
        self.font_box.setCurrentFont(QFont(family))
        self.format_font()
        self.update_font_favorite()
