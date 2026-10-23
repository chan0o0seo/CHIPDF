"""A small floating toolbar above the selection, as in design tools."""
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QToolButton


class QuickBar(QFrame):
    def __init__(self, editor):
        super().__init__(editor.canvas.viewport())
        self.editor = editor
        self.setObjectName("quickBar")
        self.setFrameShape(QFrame.NoFrame)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)
        for action in (editor.duplicate_action, editor.delete_action, editor.lock_action):
            layout.addWidget(self._button(action=action))
        layout.addWidget(self._button("앞으로", "한 단계 앞으로", lambda: editor.reorder("raise")))
        layout.addWidget(self._button("뒤로", "한 단계 뒤로", lambda: editor.reorder("lower")))
        layout.addWidget(self._button("서식", "서식·효과 패널 열기", lambda: editor.show_inspector("format")))
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.reposition)
        canvas = editor.canvas
        editor.scene.selectionChanged.connect(self.schedule)
        editor.scene.changed.connect(self.schedule)
        canvas.zoom_changed.connect(self.schedule)
        canvas.horizontalScrollBar().valueChanged.connect(self.schedule)
        canvas.verticalScrollBar().valueChanged.connect(self.schedule)

    def _button(self, text=None, tip=None, handler=None, action=None):
        button = QToolButton(self)
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.NoFocus)
        if action is not None:
            button.setDefaultAction(action)
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        else:
            button.setText(text)
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.clicked.connect(handler)
        return button

    def schedule(self, *_args):
        self._timer.start()

    def reposition(self):
        editor = self.editor
        items = editor.mutable_selection() if editor.project else []
        busy = (QApplication.mouseButtons() & Qt.LeftButton or editor.editing_item() or editor.comparing or
                editor.canvas.tool != "select")
        if not items or busy:
            self.hide()
            if items and QApplication.mouseButtons() & Qt.LeftButton:
                # Come back once the drag ends.
                QTimer.singleShot(150, self.schedule)
            return
        bounds = QRectF()
        for item in items:
            rect = item.mapRectToScene(QRectF(0, 0, item.model.width, item.model.height))
            bounds = rect if bounds.isNull() else bounds.united(rect)
        view = editor.canvas.mapFromScene(bounds).boundingRect()
        self.adjustSize()
        viewport = editor.canvas.viewport().rect()
        # Clear the rotate handle above the selection.
        y = view.top() - self.height() - 48
        if y < 4:
            y = view.bottom() + 14
        x = view.center().x() - self.width() // 2
        x = max(4, min(viewport.width() - self.width() - 4, x))
        y = max(4, min(viewport.height() - self.height() - 4, y))
        self.move(int(x), int(y))
        self.show()
        self.raise_()
