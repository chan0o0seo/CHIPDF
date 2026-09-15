"""Drag a rectangle on the original image; commit only when Apply is pressed."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout, QWidget


class CropCanvas(QWidget):
    def __init__(self, image, crop, parent=None):
        super().__init__(parent)
        self.image = image
        self.crop = list(crop or [0, 0, 1, 1])
        self.anchor = None
        self.setMinimumSize(440, 320)

    def image_rect(self):
        scale = min((self.width()-32)/self.image.width(), (self.height()-32)/self.image.height())
        w, h = self.image.width()*scale, self.image.height()*scale
        return QRectF((self.width()-w)/2, (self.height()-h)/2, w, h)

    def relative_point(self, position):
        area = self.image_rect()
        return QPointF(max(0, min(1, (position.x()-area.x())/area.width())),
                       max(0, min(1, (position.y()-area.y())/area.height())))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor("#e8ebe9"))
        area = self.image_rect()
        painter.drawImage(area, self.image)
        x, y, w, h = self.crop
        selected = QRectF(area.x()+x*area.width(), area.y()+y*area.height(), w*area.width(), h*area.height())
        painter.fillRect(QRectF(area.left(), area.top(), area.width(), selected.top()-area.top()), QColor(0, 0, 0, 110))
        painter.fillRect(QRectF(area.left(), selected.bottom(), area.width(), area.bottom()-selected.bottom()), QColor(0, 0, 0, 110))
        painter.fillRect(QRectF(area.left(), selected.top(), selected.left()-area.left(), selected.height()), QColor(0, 0, 0, 110))
        painter.fillRect(QRectF(selected.right(), selected.top(), area.right()-selected.right(), selected.height()), QColor(0, 0, 0, 110))
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawRect(selected)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.image_rect().contains(event.position()):
            self.anchor = self.relative_point(event.position())

    def mouseMoveEvent(self, event):
        if self.anchor is not None:
            area = QRectF(self.anchor, self.relative_point(event.position())).normalized()
            if area.width() >= .01 and area.height() >= .01:
                self.crop = [area.x(), area.y(), area.width(), area.height()]
                self.update()

    def mouseReleaseEvent(self, event):
        self.mouseMoveEvent(event)
        self.anchor = None


class CropDialog(QDialog):
    def __init__(self, image, crop, parent=None):
        super().__init__(parent)
        self.setWindowTitle("이미지 자르기")
        self.resize(660, 530)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("드래그해서 남길 부분을 선택하세요. 원래 이미지는 보존됩니다."))
        self.canvas = CropCanvas(image, crop)
        layout.addWidget(self.canvas, 1)
        reset = QPushButton("전체 이미지로 되돌리기")
        reset.clicked.connect(self.reset)
        layout.addWidget(reset)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("적용")
        buttons.button(QDialogButtonBox.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def reset(self):
        self.canvas.crop = [0, 0, 1, 1]
        self.canvas.update()
