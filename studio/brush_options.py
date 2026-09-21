"""Brush selection controls shared by the legacy and optional LaMa engines."""
from io import BytesIO
import json

from PIL import Image
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import (QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                              QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                              QLineEdit, QPushButton, QSpinBox, QVBoxLayout)

from .document_io import png_data
from .storage import atomic_write
from .text_mask import make_text_mask


class BrushOptions:
    def init_brush_options(self):
        self.erase_options = {'mode': 'text', 'engine': 'legacy', 'color': '#000000',
                              'tolerance': 65, 'expansion': 1, 'model_path': ''}
        try:
            path = self.data_dir / 'brush-settings.json'
            if path.stat().st_size < 16384:
                values = json.loads(path.read_text('utf-8'))
                if not isinstance(values, dict):
                    raise ValueError('Invalid brush settings')
                for key, choices in (('mode', ('text', 'all')), ('engine', ('legacy', 'lama'))):
                    if values.get(key) in choices:
                        self.erase_options[key] = values[key]
                color = values.get('color')
                if isinstance(color, str) and QColor(color).isValid():
                    self.erase_options['color'] = QColor(color).name()
                for key, upper in (('tolerance', 200), ('expansion', 5)):
                    value = values.get(key)
                    if type(value) is int and 0 <= value <= upper:
                        self.erase_options[key] = value
                if isinstance(values.get('model_path'), str):
                    self.erase_options['model_path'] = values['model_path']
        except (OSError, ValueError, TypeError):
            pass
        self.brush_mode_box = QComboBox()
        self.brush_mode_box.addItem('글자만 선택', 'text')
        self.brush_mode_box.addItem('칠한 부분 전체', 'all')
        self.brush_mode_box.setCurrentIndex(self.brush_mode_box.findData(self.erase_options['mode']))
        self.brush_mode_box.setToolTip('글자만 선택: Alt+클릭으로 글자색을 고른 뒤 글씨 주변을 칠하세요.')
        self.brush_mode_box.setAccessibleName('브러시 선택 방식')
        self.erase_engine_box = QComboBox()
        self.erase_engine_box.addItem('주변색 보간', 'legacy')
        self.erase_engine_box.addItem('사진 복원 · LaMa', 'lama')
        self.erase_engine_box.setCurrentIndex(self.erase_engine_box.findData(self.erase_options['engine']))
        self.erase_engine_box.setAccessibleName('배경 복원 방식')
        self.erase_settings_action = self.action('지우기 설정…', self.edit_erase_settings)
        self.erase_mask_action = self.action('지울 글씨 확인', self.refresh_brush_preview)
        self.region_bar.addWidget(self.brush_mode_box)
        self.region_bar.addWidget(self.erase_engine_box)
        self.region_bar.addActions([self.erase_settings_action, self.erase_mask_action])
        self.brush_mode_box.currentIndexChanged.connect(self.erase_option_changed)
        self.erase_engine_box.currentIndexChanged.connect(self.erase_option_changed)
        self.canvas.brush_stroke_finished.connect(self.refresh_brush_preview)
        self.canvas.brush_color_sampled.connect(self.sample_erase_color)

    def save_erase_options(self):
        try:
            atomic_write(self.data_dir / 'brush-settings.json',
                         json.dumps(self.erase_options, ensure_ascii=False).encode('utf-8'))
        except OSError:
            self.status.setText('지우기 설정은 이번 실행에만 적용됩니다 · 설정 저장 실패')

    def erase_option_changed(self, *args):
        self.erase_options['mode'] = self.brush_mode_box.currentData()
        self.erase_options['engine'] = self.erase_engine_box.currentData()
        self.save_erase_options()
        self.refresh_brush_preview()

    def brush_erase_mask(self, background, selection):
        if self.erase_options['mode'] == 'all':
            return selection
        with Image.open(BytesIO(png_data(background))) as image:
            source = image.convert('RGBA')
        with Image.open(BytesIO(png_data(selection))) as image:
            selected = image.convert('L')
        options = self.erase_options
        return make_text_mask(source, selected, options['color'], options['tolerance'], options['expansion'])

    def refresh_brush_preview(self, *args):
        if not self.project or self.job or self.comparing or self.canvas.tool != 'brush':
            return
        selection = self.canvas.brush_mask_image()
        if selection.isNull():
            return
        self.refresh_background()
        background = self.background_image if not self.background_image.isNull() else self.image
        try:
            mask = self.brush_erase_mask(background, selection)
            if isinstance(mask, QImage):
                with Image.open(BytesIO(png_data(mask))) as opened:
                    mask = opened.convert('L')
            overlay = Image.new('RGBA', mask.size, (220, 66, 103, 0))
            overlay.putalpha(mask.point(lambda value: 110 if value else 0))
            stream = BytesIO()
            overlay.save(stream, 'PNG')
            self.canvas.set_brush_preview(QImage.fromData(stream.getvalue()))
            count = sum(mask.histogram()[1:])
            if not count:
                self.status.setText('선택한 색의 글씨가 없습니다 · Alt+클릭으로 글자색을 고르거나 지우기 설정을 조절하세요')
            else:
                self.status.setText(f'지울 영역 {count:,}픽셀 · Alt+클릭: 글자색 · Shift+드래그: 선택 빼기')
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))

    def sample_erase_color(self, point):
        if not self.project or self.job or self.comparing:
            return
        self.refresh_background()
        background = self.background_image if not self.background_image.isNull() else self.image
        x, y = int(point.x()), int(point.y())
        if not (0 <= x < background.width() and 0 <= y < background.height()):
            return
        color = background.pixelColor(x, y)
        if color.alpha() == 0:
            self.status.setText('투명한 부분에서는 글자색을 고를 수 없습니다')
            return
        self.erase_options['color'] = color.name()
        self.brush_mode_box.setCurrentIndex(self.brush_mode_box.findData('text'))
        self.save_erase_options()
        self.refresh_brush_preview()
        self.status.setText(f'글자색 {color.name()} 선택됨 · 글씨 주변을 칠하세요')

    def edit_erase_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('글씨 지우기 설정')
        dialog.setMinimumWidth(480)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        color = QPushButton(self.erase_options['color'])
        def choose_color():
            picked = QColorDialog.getColor(QColor(color.text()), dialog, '지울 글자색')
            if picked.isValid():
                color.setText(picked.name())
        color.clicked.connect(choose_color)
        form.addRow('글자색', color)
        tolerance = QSpinBox()
        tolerance.setRange(0, 200)
        tolerance.setValue(self.erase_options['tolerance'])
        form.addRow('비슷한 색 포함', tolerance)
        expansion = QSpinBox()
        expansion.setRange(0, 5)
        expansion.setSuffix(' px')
        expansion.setValue(self.erase_options['expansion'])
        form.addRow('글자 테두리 확장', expansion)
        layout.addLayout(form)
        hint = QLabel('Alt+클릭으로 사진에서 글자색을 고를 수 있습니다.\nShift+드래그로 보호할 부분을 선택에서 빼세요.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        model = QLineEdit(self.erase_options['model_path'])
        model.setPlaceholderText('LaMa 모델 파일을 연결하세요 (.onnx)')
        model_row = QHBoxLayout()
        model_row.addWidget(model)
        browse = QPushButton('파일 선택…')
        def choose_model():
            filename, _ = QFileDialog.getOpenFileName(dialog, 'LaMa 모델 연결', model.text(), 'ONNX 모델 (*.onnx)')
            if filename:
                model.setText(filename)
        browse.clicked.connect(choose_model)
        model_row.addWidget(browse)
        layout.addWidget(QLabel('사진 복원 · LaMa'))
        layout.addLayout(model_row)
        from .inpaint_engine import lama_status
        state = QLabel(lama_status(self.erase_options['model_path'] or None)['message'])
        state.setWordWrap(True)
        layout.addWidget(state)
        model.editingFinished.connect(lambda: state.setText(lama_status(model.text().strip() or None)['message']))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.Accepted:
            self.erase_options.update(color=color.text(), tolerance=tolerance.value(),
                                      expansion=expansion.value(), model_path=model.text().strip())
            self.save_erase_options()
            self.refresh_brush_preview()
