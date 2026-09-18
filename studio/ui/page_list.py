"""Page thumbnails with selection decoration outside the document image."""
from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate


PAGE_NUMBER_ROLE = Qt.UserRole + 1
PAGE_NAME_ROLE = Qt.UserRole + 2


class PageThumbnailDelegate(QStyledItemDelegate):
    """Keep document pixels unchanged when Qt selects a page item."""

    def sizeHint(self, option, index):
        return QSize(164, 178)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        card = QRectF(option.rect.adjusted(6, 4, -6, -4))
        background = '#EAF3FC' if selected else '#F3F7FC' if hovered else '#FFFFFF'
        border = '#0F6CBD' if selected else '#DDE3EA'
        painter.setBrush(QColor(background))
        painter.setPen(QPen(QColor(border), 2 if selected else 1))
        painter.drawRoundedRect(card, 7, 7)

        preview = QRect(option.rect.x() + 14, option.rect.y() + 12,
                        max(1, option.rect.width() - 28), 124)
        icon = index.data(Qt.DecorationRole)
        if isinstance(icon, QIcon) and not icon.isNull():
            # Selected/disabled icon modes can recolor a document. Always
            # request Normal mode and draw selection on the surrounding card.
            icon.paint(painter, preview, Qt.AlignCenter, QIcon.Normal, QIcon.Off)
        else:
            placeholder = QRectF(preview.adjusted(24, 5, -24, -5))
            painter.setPen(QPen(QColor('#E2E7EE'), 1))
            painter.setBrush(QColor('#F7F9FC'))
            painter.drawRoundedRect(placeholder, 3, 3)

        label_y = option.rect.bottom() - 31
        badge = QRectF(option.rect.x() + 15, label_y, 24, 22)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor('#0F6CBD' if selected else '#EDF1F6'))
        painter.drawRoundedRect(badge, 4, 4)
        font = QFont(option.font)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor('#FFFFFF' if selected else '#616161'))
        number = str(index.data(PAGE_NUMBER_ROLE) or index.row() + 1)
        painter.drawText(badge, Qt.AlignCenter, number)

        font.setBold(selected)
        painter.setFont(font)
        painter.setPen(QColor('#242424'))
        label = QRect(option.rect.x() + 47, label_y,
                      max(1, option.rect.width() - 62), 22)
        name = index.data(PAGE_NAME_ROLE) or index.data(Qt.DisplayRole) or ''
        painter.drawText(label, Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(name, Qt.ElideRight, label.width()))

        if option.state & QStyle.State_HasFocus:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor('#0F6CBD'), 1, Qt.DotLine))
            painter.drawRoundedRect(card.adjusted(3, 3, -3, -3), 4, 4)
        painter.restore()
