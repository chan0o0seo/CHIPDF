"""Office-style command surface using the editor's existing actions and handlers."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QScrollArea,
                              QSizePolicy, QStackedWidget, QTabBar, QToolBar,
                              QToolButton, QVBoxLayout, QWidget)

from ..model import ImageBox, ShapeBox, TextBox
from .icons import icon


def row(parent):
    layout = QHBoxLayout(parent)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    return layout


class RibbonGroup(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName('ribbonGroup')
        self.setFixedHeight(92)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 3)
        layout.setSpacing(3)
        self.body = QWidget()
        self.body_layout = row(self.body)
        layout.addWidget(self.body, 1)
        self.caption = QLabel(title)
        self.caption.setObjectName('ribbonGroupTitle')
        self.caption.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.caption)

    def column(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.body_layout.addWidget(container)
        return layout


class OfficeRibbon:
    def ribbon_button(self, action, large=False, compact=False):
        button = QToolButton()
        button.setDefaultAction(action)
        button.setProperty('ribbonSmall', not large)
        button.setFocusPolicy(Qt.TabFocus)
        button.setAccessibleName(action.text())
        button.setToolButtonStyle(Qt.ToolButtonIconOnly if compact else
                                  Qt.ToolButtonTextUnderIcon if large else Qt.ToolButtonTextBesideIcon)
        button.setIconSize(QSize(28, 28) if large else QSize(18, 18))
        button.setFixedHeight(62 if large else 28)
        if large:
            button.setMinimumWidth(64)
        if compact:
            button.setFixedWidth(30)
        return button

    def ribbon_menu(self, label, menu, name='more', large=False):
        button = QToolButton()
        button.setText(label)
        button.setProperty('ribbonSmall', not large)
        button.setIcon(icon(name))
        button.setMenu(menu)
        button.setPopupMode(QToolButton.InstantPopup)
        button.setFocusPolicy(Qt.TabFocus)
        button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon if large else Qt.ToolButtonTextBesideIcon)
        button.setIconSize(QSize(28, 28) if large else QSize(18, 18))
        button.setFixedHeight(62 if large else 28)
        button.setAccessibleName(label)
        return button

    def take_ribbon_widget(self, toolbar, widget):
        # Release the old toolbar's widget association before reparenting.
        for action in toolbar.actions():
            if toolbar.widgetForAction(action) is widget:
                toolbar.removeAction(action)
                break
        widget.setParent(self)
        widget.setMinimumHeight(28)
        widget.setMaximumHeight(28)
        widget.show()
        return widget

    def ribbon_page(self, label):
        self.ribbon_tabs.addTab(label)
        page = QWidget()
        page.setObjectName('ribbonPage')
        layout = row(page)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(0)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(page)
        self.ribbon_stack.addWidget(scroll)
        return layout

    def init_ribbon(self):
        icon_names = {
            'open': 'open', 'save': 'save', 'save_as': 'save', 'export': 'export',
            'undo': 'undo', 'redo': 'redo', 'copy': 'copy', 'cut': 'cut', 'paste': 'paste',
            'add': 'text', 'image': 'image', 'duplicate': 'duplicate', 'delete': 'delete',
            'bold': 'bold', 'italic': 'italic', 'underline': 'underline', 'color': 'color',
            'fill': 'shape', 'paragraph': 'paragraph', 'vertical': 'vertical',
            'select_tool': 'select', 'region': 'ocr', 'translate': 'translate',
            'reread': 'ocr', 'vertical_ocr': 'vertical', 'translate_all': 'translate',
            'brush': 'brush', 'stamp': 'stamp', 'apply_erase': 'brush', 'cancel_region': 'check',
            'source': 'panel', 'page_link': 'link', 'restore_links': 'link',
            'compare': 'compare', 'group': 'group', 'ungroup': 'group', 'lock': 'lock',
            'geometry': 'settings', 'snap': 'align', 'font_favorite': 'star',
            'folder': 'folder', 'append': 'open', 'leave_group': 'check',
            'translation_settings': 'settings', 'chrome_connect': 'translate',
        }
        for name, symbol in icon_names.items():
            action = getattr(self, name + '_action', None)
            if action is not None:
                action.setIcon(icon(symbol))
        for action in (self.shape_fill, self.shape_clear, self.shape_stroke):
            action.setIcon(icon('shape'))
        for action, symbol in zip(self.image_tools, ('image', 'fit', 'compare', 'compare', 'lock')):
            action.setIcon(icon(symbol))

        # Preserve all original menu actions and shortcuts, including infrequent tools.
        original_menu_bar = self.menuBar()
        self.all_commands_menu = QMenu('모든 메뉴', self)
        for action in original_menu_bar.actions():
            if action.menu():
                self.all_commands_menu.addMenu(action.menu())
        original_menu_bar.hide()
        for toolbar in (self.main_toolbar, self.context_bar, self.region_bar):
            self.removeToolBar(toolbar)
            toolbar.hide()

        shell = QWidget()
        shell.setObjectName('ribbonShell')
        shell.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        header = QWidget()
        header.setObjectName('documentHeader')
        header.setFixedHeight(42)
        header_layout = row(header)
        header_layout.setContentsMargins(16, 4, 12, 4)
        brand = QLabel('치pdf')
        brand.setObjectName('appBrand')
        header_layout.addWidget(brand)
        header_layout.addSpacing(12)
        for action in (self.save_action, self.undo_action, self.redo_action):
            header_layout.addWidget(self.ribbon_button(action, compact=True))
        header_layout.addSpacing(12)
        self.document_title = QLabel('새 작업을 시작하세요')
        self.document_title.setObjectName('documentTitle')
        self.document_title.setMinimumWidth(0)
        self.document_title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        header_layout.addWidget(self.document_title, 1)
        self.document_save_state = QLabel()
        self.document_save_state.setObjectName('saveState')
        header_layout.addWidget(self.document_save_state)
        header_layout.addSpacing(8)
        export = self.ribbon_button(self.export_action)
        export.setObjectName('primaryButton')
        export.setToolButtonStyle(Qt.ToolButtonTextOnly)
        header_layout.addWidget(export)
        shell_layout.addWidget(header)

        tabs_row = QWidget()
        tabs_row.setObjectName('ribbonTabsSurface')
        tabs_layout = row(tabs_row)
        tabs_layout.setContentsMargins(10, 0, 10, 0)
        tabs_row.setFixedHeight(36)
        tabs_layout.addWidget(self.ribbon_menu('파일', self.file_menu, 'open'))
        self.ribbon_tabs = QTabBar()
        self.ribbon_tabs.setObjectName('ribbonTabs')
        self.ribbon_tabs.setExpanding(False)
        self.ribbon_tabs.setDrawBase(False)
        self.ribbon_tabs.setUsesScrollButtons(True)
        self.ribbon_tabs.setAccessibleName('편집 리본 탭')
        tabs_layout.addWidget(self.ribbon_tabs, 1)
        tabs_layout.addWidget(self.ribbon_menu('모든 메뉴', self.all_commands_menu))
        shell_layout.addWidget(tabs_row)
        self.ribbon_stack = QStackedWidget()
        self.ribbon_stack.setFixedHeight(108)
        shell_layout.addWidget(self.ribbon_stack)

        home = self.ribbon_page('홈')
        clipboard = RibbonGroup('클립보드')
        clipboard.body_layout.addWidget(self.ribbon_button(self.paste_action, large=True))
        col = clipboard.column()
        for action in (self.cut_action, self.copy_action):
            col.addWidget(self.ribbon_button(action))
        home.addWidget(clipboard)

        font = RibbonGroup('글꼴')
        col = font.column()
        first, second = QWidget(), QWidget()
        first_row, second_row = row(first), row(second)
        self.take_ribbon_widget(self.format_bar, self.font_box)
        self.take_ribbon_widget(self.format_bar, self.size_box)
        self.font_box.setFixedWidth(170)
        self.size_box.setMinimumWidth(104)
        self.size_box.setMaximumWidth(128)
        self.font_box.setAccessibleName('글꼴')
        self.size_box.setAccessibleName('글자 크기')
        first_row.addWidget(self.font_box)
        first_row.addWidget(self.size_box)
        for action in (self.bold_action, self.italic_action, self.underline_action, self.color_action,
                       self.font_favorite_action):
            second_row.addWidget(self.ribbon_button(action, compact=True))
        second_row.addWidget(self.ribbon_menu('서식', self.text_format_menu, 'settings'))
        second_row.addStretch()
        col.addWidget(first)
        col.addWidget(second)
        home.addWidget(font)

        paragraph = RibbonGroup('문단')
        col = paragraph.column()
        self.take_ribbon_widget(self.format_bar, self.align_box)
        self.align_box.setAccessibleName('문단 정렬')
        col.addWidget(self.align_box)
        paragraph_row = QWidget()
        layout = row(paragraph_row)
        layout.addWidget(self.ribbon_button(self.vertical_action, compact=True))
        layout.addWidget(self.ribbon_button(self.paragraph_action, compact=True))
        layout.addWidget(self.ribbon_button(self.fill_action, compact=True))
        col.addWidget(paragraph_row)
        home.addWidget(paragraph)

        arrange = RibbonGroup('배치')
        col = arrange.column()
        col.addWidget(self.ribbon_menu('맞춤 · 순서', self.arrange_menu, 'align'))
        buttons = QWidget()
        layout = row(buttons)
        for action in (self.group_action, self.lock_action, self.delete_action):
            layout.addWidget(self.ribbon_button(action, compact=True))
        col.addWidget(buttons)
        home.addWidget(arrange)
        quick = RibbonGroup('빠른 작업')
        quick.body_layout.addWidget(self.ribbon_button(self.region_action, large=True))
        quick.body_layout.addWidget(self.ribbon_button(self.translate_action, large=True))
        home.addWidget(quick)
        home.addStretch()

        insert = self.ribbon_page('삽입')
        objects = RibbonGroup('개체')
        for action in (self.add_action, self.image_action):
            objects.body_layout.addWidget(self.ribbon_button(action, large=True))
        shape_menu = QMenu('도형', self)
        for action in self.insert_menu.actions():
            if action not in (self.add_action, self.image_action):
                action.setIcon(icon('shape'))
                shape_menu.addAction(action)
        self.ribbon_shape_button = self.ribbon_menu('도형', shape_menu, 'shape', large=True)
        objects.body_layout.addWidget(self.ribbon_shape_button)
        insert.addWidget(objects)
        links = RibbonGroup('문서 탐색')
        links.body_layout.addWidget(self.ribbon_button(self.page_link_action, large=True))
        insert.addWidget(links)
        files = RibbonGroup('페이지 가져오기')
        for action in (self.append_action, self.folder_action):
            files.body_layout.addWidget(self.ribbon_button(action, large=True))
        insert.addWidget(files)
        insert.addStretch()

        translate = self.ribbon_page('번역·지우기')
        tools = RibbonGroup('영역 도구')
        for action in (self.select_tool_action, self.region_action, self.brush_action, self.stamp_action):
            tools.body_layout.addWidget(self.ribbon_button(action, large=True))
        translate.addWidget(tools)
        options = RibbonGroup('도구 옵션')
        col = options.column()
        self.take_ribbon_widget(self.region_bar, self.orientation_box)
        self.take_ribbon_widget(self.region_bar, self.brush_size_box)
        self.orientation_box.setAccessibleName('원문 인식 방향')
        self.brush_size_box.setAccessibleName('브러시 또는 도장 크기')
        col.addWidget(self.orientation_box)
        col.addWidget(self.brush_size_box)
        self.ribbon_tool_hint = QLabel('영역 도구를 선택하세요')
        self.ribbon_tool_hint.setProperty('role', 'secondary')
        self.ribbon_tool_hint.setWordWrap(True)
        self.ribbon_tool_hint.setFixedWidth(154)
        col.addWidget(self.ribbon_tool_hint)
        finish_row = QWidget()
        layout = row(finish_row)
        layout.addWidget(self.ribbon_button(self.apply_erase_action))
        layout.addWidget(self.ribbon_button(self.cancel_region_action))
        col.addWidget(finish_row)
        translate.addWidget(options)
        erase = RibbonGroup('글씨 지우기')
        col = erase.column()
        for widget in (self.brush_mode_box, self.erase_engine_box):
            self.take_ribbon_widget(self.region_bar, widget)
            col.addWidget(widget)
        col = erase.column()
        col.addWidget(self.ribbon_button(self.erase_settings_action))
        col.addWidget(self.ribbon_button(self.erase_mask_action))
        translate.addWidget(erase)
        self.ribbon_erase_group = erase
        reading = RibbonGroup('번역')
        reading.body_layout.addWidget(self.ribbon_button(self.translate_action, large=True))
        col = reading.column()
        col.addWidget(self.ribbon_button(self.source_action))
        batch_menu = QMenu('페이지 작업', self)
        batch_menu.addActions([self.reread_action, self.vertical_ocr_action, self.translate_all_action])
        col.addWidget(self.ribbon_menu('페이지 작업', batch_menu, 'ocr'))
        translate.addWidget(reading)
        engine = RibbonGroup('번역 설정')
        col = engine.column()
        col.addWidget(self.ribbon_button(self.translation_settings_action))
        col.addWidget(self.ribbon_button(self.chrome_connect_action))
        packs = QMenu('오프라인 팩', self)
        packs.addActions([self.offline_install_action, self.offline_connect_action])
        engine.body_layout.addWidget(self.ribbon_menu('오프라인 팩', packs, 'folder', large=True))
        translate.addWidget(engine)
        translate.addStretch()

        view = self.ribbon_page('보기')
        display = RibbonGroup('작업 화면')
        self.pages_panel_action = self.action('페이지 목록', self.toggle_pages_panel, checkable=True)
        self.pages_panel_action.setChecked(True)
        self.pages_panel_action.setIcon(icon('pages'))
        self.inspector_panel_action = self.source_dock.toggleViewAction()
        self.inspector_panel_action.setText('속성 패널')
        self.inspector_panel_action.setIcon(icon('panel'))
        for action in (self.pages_panel_action, self.inspector_panel_action, self.compare_action):
            display.body_layout.addWidget(self.ribbon_button(action, large=True))
        view.addWidget(display)
        zoom = RibbonGroup('확대 / 축소')
        self.fit_action = self.action('화면에 맞춤', self.canvas.fit_page)
        self.actual_size_action = self.action('100%', lambda: self.canvas.zoom(1 / self.canvas.transform().m11()))
        self.fit_action.setIcon(icon('fit'))
        self.actual_size_action.setIcon(icon('zoom_in'))
        for action in (self.fit_action, self.actual_size_action):
            zoom.body_layout.addWidget(self.ribbon_button(action, large=True))
        view.addWidget(zoom)
        guides = RibbonGroup('편집 안내')
        col = guides.column()
        col.addWidget(self.ribbon_button(self.snap_action))
        col.addWidget(self.ribbon_button(self.leave_group_action))
        view.addWidget(guides)
        view.addStretch()

        contextual = self.ribbon_page('개체 서식')
        self.object_tab_index = self.ribbon_tabs.count() - 1
        shape = RibbonGroup('도형')
        col = shape.column()
        colors = QWidget()
        layout = row(colors)
        for action in (self.shape_fill, self.shape_clear, self.shape_stroke):
            layout.addWidget(self.ribbon_button(action))
        col.addWidget(colors)
        self.take_ribbon_widget(self.object_bar, self.stroke_box)
        col.addWidget(self.stroke_box)
        contextual.addWidget(shape)
        self.ribbon_shape_group = shape
        picture = RibbonGroup('그림')
        for action in self.image_tools:
            picture.body_layout.addWidget(self.ribbon_button(action, large=True))
        contextual.addWidget(picture)
        self.ribbon_picture_group = picture
        common = RibbonGroup('크기와 배치')
        col = common.column()
        self.take_ribbon_widget(self.object_bar, self.opacity_box)
        col.addWidget(self.opacity_box)
        col.addWidget(self.ribbon_menu('배치', self.arrange_menu, 'align'))
        common.body_layout.addWidget(self.ribbon_button(self.geometry_action, large=True))
        contextual.addWidget(common)
        contextual.addStretch()
        self.ribbon_tabs.setTabVisible(self.object_tab_index, False)
        self.ribbon_tabs.currentChanged.connect(self.ribbon_stack.setCurrentIndex)
        self.ribbon_tabs.setCurrentIndex(0)
        self.ribbon_stack.setCurrentIndex(0)

        bar = QToolBar('리본', self)
        bar.setObjectName('officeRibbonBar')
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setStyleSheet('QToolBar#officeRibbonBar { border: 0; padding: 0; spacing: 0; }')
        bar.addWidget(shell)
        self.addToolBar(Qt.TopToolBarArea, bar)
        self.office_ribbon_bar = bar
        self.canvas.setObjectName('workspace')

    def toggle_pages_panel(self, visible):
        view = self.capture_canvas_view()
        self.page_sidebar.setVisible(visible)
        self.restore_canvas_view(view)

    def update_document_header(self, state=None):
        if not hasattr(self, 'document_title'):
            return
        self.document_title.setText(self.project.name if self.project else '새 작업을 시작하세요')
        self.document_title.setToolTip(str(self.project_path or (self.project.name if self.project else '')))
        if self.project:
            self.document_save_state.setText(state or ('저장 중…' if self.dirty else
                                             '자동 복구본 저장' if not self.project_path else '저장됨'))
            self.page_position_label.setText(f'{self.page_index + 1} / {len(self.project.pages)} 페이지  ')
            self.page_panel_title.setText(f'페이지  ·  {len(self.project.pages)}')
        else:
            self.document_save_state.clear()
            self.page_position_label.clear()
            self.page_panel_title.setText('페이지')

    def update_ribbon_region(self):
        if not hasattr(self, 'ribbon_tool_hint'):
            return
        tool = self.canvas.tool
        self.orientation_box.setVisible(tool == 'ocr')
        self.brush_size_box.setVisible(tool in ('brush', 'stamp'))
        self.ribbon_erase_group.setVisible(tool == 'brush')
        self.ribbon_tool_hint.setVisible(tool in ('select', 'stamp'))
        self.ribbon_tool_hint.setText('Alt+클릭으로 원본 지정' if tool == 'stamp' else '영역 도구를 선택하세요')

    def update_ribbon(self):
        if not hasattr(self, 'object_tab_index'):
            return
        self.context_bar.hide()
        self.region_bar.hide()
        selected = self.selected()
        mutable = bool(self.mutable_selection())
        text = bool(selected) and all(isinstance(item.model, TextBox) for item in selected)
        shape = bool(selected) and all(isinstance(item.model, ShapeBox) for item in selected)
        image = bool(selected) and all(isinstance(item.model, ImageBox) for item in selected)
        for widget in (self.font_box, self.size_box, self.align_box):
            widget.setEnabled(mutable and text)
        for action in (self.bold_action, self.italic_action, self.underline_action, self.color_action, self.fill_action):
            action.setEnabled(mutable and text)
        contextual = bool(selected) and not text and not self.comparing
        if not contextual and self.ribbon_tabs.currentIndex() == self.object_tab_index:
            self.ribbon_tabs.setCurrentIndex(0)
        self.ribbon_tabs.setTabVisible(self.object_tab_index, contextual)
        self.ribbon_tabs.setTabText(self.object_tab_index, '그림 서식' if image else '도형 서식' if shape else '개체 서식')
        self.ribbon_shape_group.setVisible(shape)
        self.ribbon_picture_group.setVisible(image)
        self.stroke_box.setEnabled(shape and mutable)
        self.ribbon_shape_button.setEnabled(bool(self.project) and not self.comparing)
        self.fit_action.setEnabled(bool(self.project))
        self.actual_size_action.setEnabled(bool(self.project))
        self.update_ribbon_region()
        self.update_document_header()
