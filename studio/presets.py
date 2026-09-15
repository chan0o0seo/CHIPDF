"""Local, content-free typography and explicit cross-card layout reuse."""
from copy import deepcopy
from dataclasses import asdict
import json
import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout,
                              QInputDialog, QLabel, QListWidget, QListWidgetItem,
                              QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .model import Paragraph, Project, Run, Style, TextBox
from .storage import atomic_write


STYLE_KEYS = {'style', 'paragraph', 'margin', 'writing_mode'}
PARAGRAPH_KEYS = {'align', 'line_spacing', 'space_before', 'space_after'}
GEOMETRY_KEYS = ('x', 'y', 'width', 'height', 'rotation', 'scale')
MAX_BYTES = 2_000_000
ORDER_LABEL = '위에서 아래로, 같은 높이에서는 왼쪽에서 오른쪽으로'


def _exact(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError('저장된 서식·배치의 구성이 올바르지 않습니다.')


def _number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('저장된 서식·배치의 숫자 범위가 올바르지 않습니다.')


def _name(value):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 80 or any(ord(c) < 32 for c in value):
        raise ValueError('이름은 앞뒤 공백 없이 1~80자로 입력해 주세요.')
    return value


def capture_style(box):
    paragraph = box.paragraphs[0] if box.paragraphs else Paragraph()
    style = paragraph.runs[0].style if paragraph.runs else Style()
    return {'style': asdict(style), 'paragraph': {key: getattr(paragraph, key) for key in PARAGRAPH_KEYS},
            'margin': box.margin, 'writing_mode': box.writing_mode}


def apply_style(box, preset):
    """Change appearance only: never rewrite target wording or workflow metadata."""
    box.margin, box.writing_mode = preset['margin'], preset['writing_mode']
    for paragraph in box.paragraphs:
        for key, value in preset['paragraph'].items():
            setattr(paragraph, key, value)
        for run in paragraph.runs:
            run.style = Style(**preset['style'])


def _validate_style(value):
    _exact(value, STYLE_KEYS)
    _exact(value['style'], asdict(Style()))
    _exact(value['paragraph'], PARAGRAPH_KEYS)
    _number(value['style']['size'], 1, 400)
    _number(value['margin'], 0, 200)
    if value['writing_mode'] not in ('horizontal', 'vertical-rl'):
        raise ValueError('저장된 글쓰기 방향이 올바르지 않습니다.')
    box = TextBox(paragraphs=[Paragraph([Run('')])])
    apply_style(box, value)
    trial = Project()
    trial.pages[0].objects = [box]
    Project.from_dict(trial.to_dict())


def validate_presets(value):
    """Reject unknown fields so imported JSON cannot smuggle source or target text."""
    try:
        _exact(value, {'version', 'styles', 'layouts'})
        if type(value['version']) is not int or value['version'] != 1:
            raise ValueError('지원하지 않는 서식·배치 파일 버전입니다.')
        for key, limit in (('styles', 200), ('layouts', 100)):
            if not isinstance(value[key], dict) or len(value[key]) > limit:
                raise ValueError('저장한 서식 또는 배치 수가 너무 많습니다.')
            for name in value[key]:
                _name(name)
        for preset in value['styles'].values():
            _validate_style(preset)
        total = 0
        for layout in value['layouts'].values():
            _exact(layout, {'width', 'height', 'order', 'slots'})
            if layout['order'] != 'top-left':
                raise ValueError('저장된 배치 순서가 올바르지 않습니다.')
            for key in ('width', 'height'):
                if type(layout[key]) is not int:
                    raise ValueError('저장된 카드 크기가 올바르지 않습니다.')
                _number(layout[key], 1, 16000)
            if layout['width']*layout['height'] > 80_000_000:
                raise ValueError('저장된 카드 크기가 너무 큽니다.')
            if not isinstance(layout['slots'], list) or not 1 <= len(layout['slots']) <= 2000:
                raise ValueError('배치에는 텍스트 상자 1~2000개가 필요합니다.')
            total += len(layout['slots'])
            for slot in layout['slots']:
                _exact(slot, {'geometry', 'format'})
                _exact(slot['geometry'], GEOMETRY_KEYS)
                for key, coordinate in slot['geometry'].items():
                    _number(coordinate, .0001 if key == 'scale' else 24 if key in ('width', 'height') else -100000,
                            10000 if key == 'scale' else 100000)
                _validate_style(slot['format'])
        if total > 4000:
            raise ValueError('저장된 배치의 텍스트 상자가 모두 합쳐 4000개를 넘습니다.')
    except (TypeError, KeyError, AttributeError, OverflowError) as exc:
        raise ValueError('저장된 서식·배치의 값이 올바르지 않습니다.') from exc
    return deepcopy(value)


def _visible_key(box):
    transform = QTransform()
    transform.translate(box.x+box.width/2, box.y+box.height/2)
    transform.rotate(box.rotation)
    transform.scale(box.scale, box.scale)
    transform.translate(-box.width/2, -box.height/2)
    bounds = transform.mapRect(QRectF(0, 0, box.width, box.height))
    return bounds.top(), bounds.left(), box.z, box.id


def _layout_boxes(page):
    boxes = [box for box in page.objects if isinstance(box, TextBox)]
    if not boxes:
        return [], '텍스트 상자가 없습니다'
    if any(box.parent_id for box in boxes):
        return [], '그룹 안 텍스트가 있습니다 · 그룹을 해제한 뒤 사용하세요'
    if any(box.locked for box in boxes):
        return [], '잠긴 텍스트 상자가 있습니다'
    return sorted(boxes, key=_visible_key), ''


class Presets:
    def init_presets(self):
        self.presets_path = self.data_dir / 'presets.json'
        self.presets = {'version': 1, 'styles': {}, 'layouts': {}}
        self.presets_load_error = None
        self._presets_bytes = None
        try:
            if self.presets_path.exists():
                if self.presets_path.stat().st_size > MAX_BYTES:
                    raise ValueError('서식·배치 파일은 2MB까지 지원합니다.')
                raw = self.presets_path.read_bytes()
                self.presets = validate_presets(json.loads(raw.decode('utf-8')))
                self._presets_bytes = raw
        except (OSError, ValueError, UnicodeError) as exc:
            self.presets_load_error = str(exc)
            self.status.setText('저장된 서식·배치를 읽지 못했습니다. 기존 파일은 보존됩니다.')
        self.save_text_preset_action = self.action('글자 서식 저장…', self.save_text_preset_dialog)
        self.apply_text_preset_action = self.action('저장한 글자 서식 적용…', self.apply_text_preset_dialog)
        self.text_format_menu.addSeparator()
        self.text_format_menu.addActions([self.save_text_preset_action, self.apply_text_preset_action])
        self.save_layout_preset_action = self.action('이 카드의 글상자 배치 저장…', self.save_layout_preset_dialog)
        self.apply_layout_preset_action = self.action('저장한 글상자 배치 적용…', self.apply_layout_preset_dialog)
        self.arrange_menu.addSeparator()
        self.arrange_menu.addActions([self.save_layout_preset_action, self.apply_layout_preset_action])
        for action in (self.save_text_preset_action, self.apply_text_preset_action):
            action.setToolTip('첫 글자와 첫 문단의 서식을 이름으로 저장해 선택한 상자 전체에 적용합니다. 문구는 유지됩니다.')
        self.save_layout_preset_action.setToolTip('그룹 밖 텍스트 상자의 위치·크기·회전과 서식을 저장합니다. 문구와 원문은 저장하지 않습니다.')
        self.apply_layout_preset_action.setToolTip('같은 크기·같은 수의 글상자를 가진 카드를 확인하고 배치를 적용합니다.')
        if self.presets_load_error:
            for action in (self.save_text_preset_action, self.apply_text_preset_action,
                           self.save_layout_preset_action, self.apply_layout_preset_action):
                action.setToolTip(f'기존 파일을 보존하기 위해 저장을 중단했습니다: {self.presets_load_error}\n{self.presets_path}')
        self.update_presets_tools()

    def update_presets_tools(self):
        if not hasattr(self, 'save_text_preset_action'):
            return
        selected = self.mutable_selection()
        text = bool(selected) and all(isinstance(item.model, TextBox) for item in selected)
        ready = bool(self.project) and not self.comparing and not self.presets_load_error
        self.save_text_preset_action.setEnabled(ready and text and len(selected) == 1)
        self.apply_text_preset_action.setEnabled(ready and text and bool(self.presets['styles']))
        self.save_layout_preset_action.setEnabled(ready and not self.active_group_id and not _layout_boxes(self.current_page)[1])
        self.apply_layout_preset_action.setEnabled(ready and not self.active_group_id and bool(self.presets['layouts']))

    def _write_presets(self, value):
        if self.presets_load_error:
            raise ValueError(f'기존 서식·배치 파일을 읽지 못해 저장을 중단했습니다. 파일을 확인한 뒤 다시 실행해 주세요.\n{self.presets_path}')
        value = validate_presets(value)
        encoded = json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')
        if len(encoded) > MAX_BYTES:
            raise ValueError('서식·배치 파일은 2MB까지 지원합니다.')
        if self.presets_path.exists() and self.presets_path.stat().st_size > MAX_BYTES:
            raise ValueError('서식·배치 파일이 외부에서 변경되었거나 너무 큽니다. 기존 파일을 확인해 주세요.')
        current = self.presets_path.read_bytes() if self.presets_path.exists() else None
        if current != self._presets_bytes:
            raise ValueError('다른 창이나 프로그램에서 서식·배치 파일을 변경했습니다. 프로그램을 다시 실행해 최신 파일을 불러와 주세요.')
        atomic_write(self.presets_path, encoded)
        self.presets, self._presets_bytes = value, encoded
        self.update_presets_tools()

    def _text_preset_targets(self):
        self.finish_edit()
        self.sync_positions()
        items = self.mutable_selection()
        if not items or any(not isinstance(item.model, TextBox) for item in items):
            raise ValueError('편집 가능한 텍스트 상자를 선택해 주세요.')
        return [item.model.id for item in items]

    def save_text_preset(self, name):
        _name(name)
        ids = self._text_preset_targets()
        if len(ids) != 1:
            raise ValueError('서식을 저장할 텍스트 상자 하나를 선택해 주세요.')
        preset = capture_style(self.items_by_id[ids[0]].model)
        trial = deepcopy(self.presets)
        trial['styles'][name] = preset
        self._write_presets(trial)
        self.status.setText(f'글자 서식 “{name}” 저장됨 · 다음 실행에도 사용할 수 있습니다')
        return deepcopy(preset)

    def apply_text_preset(self, name):
        if name not in self.presets['styles']:
            raise ValueError('저장한 글자 서식을 찾지 못했습니다.')
        ids = self._text_preset_targets()
        trial = deepcopy(self.project)
        for box in trial.pages[self.page_index].objects:
            if box.id in ids:
                apply_style(box, self.presets['styles'][name])
        Project.from_dict(trial.to_dict())
        self.begin_operation()
        self.project = trial
        self.rebuild_scene(ids)
        self.finish_operation(f'글자 서식 적용 · {name}')
        return len(ids)

    def save_layout_preset(self, name):
        _name(name)
        self.finish_edit()
        self.sync_positions()
        if not self.project or self.comparing or self.active_group_id:
            raise ValueError('그룹 편집을 끝내고 카드에서 배치를 저장해 주세요.')
        boxes, reason = _layout_boxes(self.current_page)
        if reason:
            raise ValueError(reason)
        preset = {'width': self.current_page.width, 'height': self.current_page.height, 'order': 'top-left',
                  'slots': [{'geometry': {key: getattr(box, key) for key in GEOMETRY_KEYS}, 'format': capture_style(box)} for box in boxes]}
        trial = deepcopy(self.presets)
        trial['layouts'][name] = preset
        self._write_presets(trial)
        self.status.setText(f'글상자 배치 “{name}” 저장됨 · {len(boxes)}개 위치와 서식')
        return deepcopy(preset)

    def layout_candidates(self, name):
        if name not in self.presets['layouts']:
            raise ValueError('저장한 글상자 배치를 찾지 못했습니다.')
        if not self.project:
            return []
        preset, result = self.presets['layouts'][name], []
        for index, page in enumerate(self.project.pages):
            boxes, reason = _layout_boxes(page)
            if (page.width, page.height) != (preset['width'], preset['height']):
                reason = '카드 크기가 다릅니다'
            elif not reason and len(boxes) != len(preset['slots']):
                reason = f'텍스트 상자가 {len(boxes)}개입니다 · {len(preset["slots"])}개 필요'
            mapping = [] if reason else [{'id': box.id, 'text': box.text,
                                         'current': {key: getattr(box, key) for key in GEOMETRY_KEYS},
                                         'target': deepcopy(slot['geometry'])} for box, slot in zip(boxes, preset['slots'])]
            result.append({'page_id': page.id, 'index': index, 'name': page.name, 'eligible': not reason,
                           'reason': reason, 'mapping': mapping})
        return result

    def apply_layout_preset(self, name, page_ids, include_style=False):
        self.finish_edit()
        self.sync_positions()
        if not self.project or self.comparing or self.active_group_id:
            raise ValueError('원본 비교와 그룹 편집을 끝내고 배치를 적용해 주세요.')
        page_ids = list(page_ids)
        if not page_ids or len(page_ids) != len(set(page_ids)):
            raise ValueError('배치를 적용할 카드를 한 장 이상 중복 없이 선택해 주세요.')
        candidates = {entry['page_id']: entry for entry in self.layout_candidates(name)}
        for key in page_ids:
            if key not in candidates or not candidates[key]['eligible']:
                raise ValueError(candidates[key]['reason'] if key in candidates else '선택한 카드를 찾지 못했습니다.')
        selected = [item.model.id for item in self.selected()]
        selected_rows = [self.card_list.row(item) for item in self.card_list.selectedItems()]
        trial = deepcopy(self.project)
        for page in trial.pages:
            if page.id not in page_ids:
                continue
            boxes = {box.id: box for box in page.objects}
            for mapping, slot in zip(candidates[page.id]['mapping'], self.presets['layouts'][name]['slots']):
                box = boxes[mapping['id']]
                for key, value in slot['geometry'].items():
                    setattr(box, key, value)
                if include_style:
                    apply_style(box, slot['format'])
        Project.from_dict(trial.to_dict())
        changed = sum(before != after for before, after in zip(self.project.pages, trial.pages))
        if not changed:
            return 0
        self.begin_operation()
        self.project = trial
        self.rebuild_scene(selected)
        self.finish_operation(f'글상자 배치 적용 · {name} · {changed}장')
        self.refresh_card_list()
        self.card_list.blockSignals(True)
        try:
            self.card_list.clearSelection()
            for row in selected_rows:
                self.card_list.item(row).setSelected(True)
        finally:
            self.card_list.blockSignals(False)
        return changed

    def _preset_name_dialog(self, kind, title, explanation):
        name, ok = QInputDialog.getText(self, title, explanation+'\n\n저장할 이름:')
        if not ok:
            return None
        name = name.strip()
        _name(name)
        if name in self.presets[kind] and QMessageBox.question(self, '같은 이름으로 저장', f'“{name}”을 지금 설정으로 바꿀까요?',
                                                            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return None
        return name

    def save_text_preset_dialog(self, checked=False):
        try:
            self.finish_edit()
            name = self._preset_name_dialog('styles', '글자 서식 저장',
                '선택한 상자의 첫 글자·첫 문단 서식, 여백과 글쓰기 방향을 저장합니다.\n다음에 적용할 때 선택한 상자 전체가 이 서식으로 통일됩니다.')
            if name:
                self.save_text_preset(name)
        except (OSError, ValueError) as exc:
            self.report_error('글자 서식을 저장하지 못했습니다', exc)

    def apply_text_preset_dialog(self, checked=False, name=None):
        try:
            self.finish_edit()
            if name is None:
                name, ok = QInputDialog.getItem(self, '저장한 글자 서식 적용',
                    '문구는 유지하며 선택한 상자 전체를 같은 서식으로 바꿉니다.\n부분별 글자 서식도 통일됩니다. 실행 취소로 되돌릴 수 있습니다.',
                    sorted(self.presets['styles']), 0, False)
                if not ok:
                    return
            self.apply_text_preset(name)
        except (OSError, ValueError) as exc:
            self.report_error('글자 서식을 적용하지 못했습니다', exc)

    def save_layout_preset_dialog(self, checked=False):
        try:
            self.finish_edit()
            name = self._preset_name_dialog('layouts', '이 카드의 글상자 배치 저장',
                '그룹 밖 텍스트 상자의 위치·크기·회전과 서식을 저장합니다.\n문구와 원문 정보는 저장하지 않습니다.')
            if name:
                self.save_layout_preset(name)
        except (OSError, ValueError) as exc:
            self.report_error('글상자 배치를 저장하지 못했습니다', exc)

    def apply_layout_preset_dialog(self, checked=False, name=None):
        try:
            self.finish_edit()
            self.sync_positions()
            if name is None:
                name, ok = QInputDialog.getItem(self, '저장한 글상자 배치 적용', '사용할 배치:', sorted(self.presets['layouts']), 0, False)
                if not ok:
                    return
            entries = self.layout_candidates(name)
            dialog = QDialog(self)
            dialog.setWindowTitle(f'글상자 배치 적용 · {name}')
            dialog.resize(870, 590)
            layout = QVBoxLayout(dialog)
            description = QLabel(f'같은 크기·같은 수의 텍스트 상자에만 적용합니다.\n{ORDER_LABEL} 상자를 대응시킵니다.\n카드를 누르면 문구와 이동 위치를 확인할 수 있습니다. 적용할 카드를 체크하세요.')
            description.setWordWrap(True)
            layout.addWidget(description)
            row = QHBoxLayout()
            cards = QListWidget()
            cards.setMinimumWidth(255)
            table = QTableWidget(0, 3)
            table.setHorizontalHeaderLabels(['순서', '대상 문구', '현재 위치 → 저장 위치'])
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            table.setSelectionBehavior(QTableWidget.SelectRows)
            table.verticalHeader().setVisible(False)
            table.setColumnWidth(0, 45)
            table.setColumnWidth(1, 190)
            table.horizontalHeader().setStretchLastSection(True)
            selected_rows = {self.card_list.row(item) for item in self.card_list.selectedItems()}
            for entry in entries:
                suffix = '' if entry['eligible'] else '\n'+entry['reason']
                item = QListWidgetItem(f'{entry["index"]+1}. {entry["name"]}{suffix}')
                item.setToolTip(entry['name']+suffix)
                if entry['eligible']:
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if entry['index'] in selected_rows and entry['index'] != self.page_index else Qt.Unchecked)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                cards.addItem(item)
            row.addWidget(cards, 1)
            row.addWidget(table, 2)
            layout.addLayout(row, 1)
            style = QCheckBox('저장한 글자 서식·문단·쓰기 방향도 적용 (부분 서식 통일)')
            style.setChecked(False)
            layout.addWidget(style)
            note = QLabel('기본값은 위치·크기·회전만 적용합니다. 각 카드의 문구·원문 제거 영역·검토 상태·도형·이미지는 유지됩니다.')
            note.setWordWrap(True)
            layout.addWidget(note)
            buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
            buttons.button(QDialogButtonBox.Cancel).setText('취소')
            apply = buttons.button(QDialogButtonBox.Apply)
            apply.setText('선택한 카드에 적용')
            apply.clicked.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)

            def refresh_mapping(index):
                mapping = entries[index]['mapping'] if 0 <= index < len(entries) else []
                table.setRowCount(len(mapping))
                for row_index, item in enumerate(mapping):
                    current, target = item['current'], item['target']
                    values = [str(row_index+1), item['text'].replace('\n', ' / ')[:90],
                              f'({current["x"]:.0f}, {current["y"]:.0f}) → ({target["x"]:.0f}, {target["y"]:.0f})\n{target["width"]:.0f} × {target["height"]:.0f} px · {target["rotation"]:.0f}°']
                    for column, value in enumerate(values):
                        cell = QTableWidgetItem(value)
                        cell.setToolTip(item['text'] if column == 1 else value)
                        table.setItem(row_index, column, cell)
                table.resizeRowsToContents()

            def refresh_enabled():
                apply.setEnabled(any(cards.item(index).checkState() == Qt.Checked for index, entry in enumerate(entries) if entry['eligible']))

            cards.currentRowChanged.connect(refresh_mapping)
            cards.itemChanged.connect(refresh_enabled)
            first = next((index for index, entry in enumerate(entries) if entry['eligible']), -1)
            cards.setCurrentRow(first)
            refresh_enabled()
            if dialog.exec() == QDialog.Accepted:
                ids = [entry['page_id'] for index, entry in enumerate(entries) if entry['eligible'] and cards.item(index).checkState() == Qt.Checked]
                count = self.apply_layout_preset(name, ids, include_style=style.isChecked())
                self.status.setText(f'“{name}” 배치 적용 · {count}장 · 실행 취소로 한 번에 되돌릴 수 있습니다')
        except (OSError, ValueError) as exc:
            self.report_error('글상자 배치를 적용하지 못했습니다', exc)
