"""Render recent-work and spin-control UI using disposable sample documents."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import test_studio as base
from PySide6.QtGui import QFont, QFontDatabase
from studio.window import Editor
out = base.ROOT / 'qa' / 'recent-ui'
out.mkdir(parents=True, exist_ok=True)
QFontDatabase.addApplicationFont('C:/Windows/Fonts/malgun.ttf')
QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
base.APP.setFont(QFont('Malgun Gothic', 10))
case = base.StudioTests()
case.setUp()
try:
    case.insert('화살표 확인')
    case.editor.finish_edit()
    case.editor.ribbon_tabs.setCurrentIndex(0)
    base.APP.processEvents()
    case.editor.grab().save(str(out / 'editor.png'))
    case.editor.size_box.grab().save(str(out / 'font-size.png'))
    for i in range(3):
        case.editor.save_to(case.root / f'편집 작업 {i + 1}.twproj')
    welcome = Editor(case.editor.data_dir)
    welcome.show()
    base.APP.processEvents()
    welcome.grab().save(str(out / 'welcome.png'))
    welcome.resize(900, 600)
    base.APP.processEvents()
    welcome.grab().save(str(out / 'welcome-small.png'))
    welcome.close()
    welcome.deleteLater()
finally:
    case.tearDown()
