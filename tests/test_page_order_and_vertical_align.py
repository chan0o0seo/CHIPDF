"""Check editing coordinates, persistence and PDF output for document layout."""
import os
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / '.deps'), str(ROOT)]
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QFont, QImage, QInputMethodEvent, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QDoubleSpinBox, QToolButton, QPushButton, QWidget
from pypdf import PdfReader
import pypdfium2

from studio.agent_cli import load_fonts
from studio.canvas import TextItem
from studio.document_io import export_collection, png_data, render_page
from studio.model import Page, Paragraph, Project, Run, Style, TextBox
from studio.storage import load_bundle, save_project
from studio.ui.page_list import PAGE_ID_ROLE, PAGE_NUMBER_ROLE
from studio.window import Editor


class DocumentLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / 'qa').mkdir(exist_ok=True)
        cls.app = QApplication.instance() or QApplication([])
        load_fonts(())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'qa', prefix='layout-')
        self.work = Path(self.temp.name)
        self.editor = Editor(self.work / 'data')
        self.editor.show()
        self.app.processEvents()

    def tearDown(self):
        self.editor.close()
        self.editor.io_pool.waitForDone()
        self.app.processEvents()
        self.editor.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.temp.cleanup()

    def install(self, count=4, text=False):
        pages, assets = [], {}
        colors = ['#ff0000', '#00ff00', '#0000ff', '#ffff00']
        for i in range(count):
            page = Page(width=400, height=400, name=f'Page {i+1}')
            page.asset = f'assets/{page.id}.png'
            image = QImage(400, 400, QImage.Format_RGB32)
            image.fill(Qt.white if text else colors[i])
            assets[page.asset] = png_data(image)
            if text:
                page.objects = [TextBox(x=20, y=20, width=320, height=300,
                    paragraphs=[Paragraph([Run('ABCDEFG', Style(size=18, color='#000000'))])])]
            pages.append(page)
        project = Project(name='Layout', pages=pages)
        self.editor.install_collection(project, assets)
        self.app.processEvents()
        return pages

    def select_pages(self, rows):
        self.editor.card_list.clearSelection()
        for row in rows:
            self.editor.card_list.item(row).setSelected(True)

    def test_reorder_keeps_current_page_objects_selection_and_undo(self):
        pages = self.install(text=True)
        original_ids = [page.id for page in pages]
        self.editor.switch_page(1)
        active = self.editor.current_page.id
        self.select_pages([1, 3])
        self.editor.move_pages([pages[3].id, pages[1].id], 0)
        expected = [original_ids[i] for i in [1, 3, 0, 2]]
        self.assertEqual([page.id for page in self.editor.project.pages], expected)
        self.assertEqual(self.editor.current_page.id, active)
        self.assertEqual(self.editor.page_index, 0)
        self.assertEqual({item.data(PAGE_ID_ROLE) for item in self.editor.card_list.selectedItems()}, {original_ids[1], original_ids[3]})
        self.assertEqual([self.editor.card_list.item(i).data(PAGE_NUMBER_ROLE) for i in range(4)], [1, 2, 3, 4])
        self.editor.undo()
        self.assertEqual([page.id for page in self.editor.project.pages], original_ids)
        self.assertEqual(self.editor.current_page.id, active)
        self.editor.redo()
        self.assertEqual([page.id for page in self.editor.project.pages], expected)
        path = self.work / 'reordered.twproj'
        save_project(path, self.editor.project, self.editor.assets)
        loaded, assets = load_bundle(path)
        self.assertEqual(loaded, self.editor.project)
        self.assertEqual(assets, self.editor.assets)

    def test_drop_and_step_move_preserve_relative_order_and_noops(self):
        pages = self.install()
        original = [page.id for page in pages]
        self.select_pages([0, 1])
        widget = self.editor.card_list
        event = SimpleNamespace(source=lambda: widget,
            position=lambda: QPointF(widget.visualItemRect(widget.item(3)).bottomRight()),
            setDropAction=lambda action: None, accept=lambda: None)
        widget.dropEvent(event)
        self.assertEqual([page.id for page in self.editor.project.pages], [original[i] for i in [2, 3, 0, 1]])
        self.editor.move_page_step({original[0], original[1]}, -1)
        expected = [original[i] for i in [2, 0, 1, 3]]
        self.assertEqual([page.id for page in self.editor.project.pages], expected)
        steps = self.editor.undo_stack.count()
        self.editor.move_pages([original[0], original[1]], 2)
        self.editor.reorder_pages([original[0]] * 4)
        self.assertEqual(self.editor.undo_stack.count(), steps)
        self.assertEqual([page.id for page in self.editor.project.pages], expected)

    def test_export_order_and_internal_link_destination(self):
        pages = self.install(3)
        first, middle, last = pages
        first.pdf_links = [{'rect': [10, 10, 40, 40], 'page_id': last.id}]
        self.editor.move_pages([last.id], 0)
        path = self.work / 'ordered.pdf'
        self.editor.export_pages(path, [0, 1, 2], 'pdf')
        reader = PdfReader(path)
        self.assertEqual(len(reader.pages), 3)
        link = reader.pages[1]['/Annots'][0].get_object()
        self.assertEqual(link['/Dest'][0], reader.pages[0].indirect_reference)
        pdf = pypdfium2.PdfDocument(str(path))
        try:
            for i, color in enumerate([(0, 0, 255), (255, 0, 0), (0, 255, 0)]):
                page = pdf[i]
                bitmap = page.render(scale=1)
                self.assertEqual(bitmap.to_pil().convert('RGB').getpixel((70, 70)), color)
                bitmap.close()
                page.close()
        finally:
            pdf.close()

    def test_text_alignment_pixels_persistence_and_old_projects(self):
        page = self.install(1, text=True)[0]
        box = page.objects[0]
        offsets, bounds = [], []
        for alignment in ['top', 'center', 'bottom']:
            box.vertical_align = alignment
            item = TextItem(box, SimpleNamespace(changed=lambda: None))
            offsets.append(item.text_offset())
            image = render_page(deepcopy(page), self.editor.assets[page.asset])
            ys = [y for y in range(400) for x in range(20, 340)
                  if image.pixelColor(x, y).red() < 100]
            bounds.append((min(ys), max(ys)))
        self.assertEqual(offsets[0], 0)
        self.assertAlmostEqual(offsets[1] * 2, offsets[2])
        for i in [1, 2]:
            self.assertAlmostEqual(bounds[i][0] - bounds[0][0], offsets[i], delta=1)
            self.assertAlmostEqual(bounds[i][1] - bounds[0][1], offsets[i], delta=1)
        path = self.work / 'aligned.twproj'
        save_project(path, self.editor.project, self.editor.assets)
        project, assets = load_bundle(path)
        self.assertEqual(project.pages[0].objects[0].vertical_align, 'bottom')
        old = project.to_dict()
        old['version'] = 10
        del old['pages'][0]['objects'][0]['vertical_align']
        self.assertEqual(Project.from_dict(old).pages[0].objects[0].vertical_align, 'top')
        old['pages'][0]['objects'][0]['vertical_align'] = 'invalid'
        with self.assertRaises(ValueError):
            Project.from_dict(old)

    def test_center_bottom_mouse_caret_ime_and_text_undo(self):
        self.install(1, text=True)
        for alignment in ['center', 'bottom']:
            box = self.editor.current_page.objects[0]
            box.vertical_align = alignment
            self.editor.rebuild_scene([box.id])
            item = self.editor.items_by_id[box.id]
            self.app.processEvents()
            item.begin_edit()
            doc = item.document()
            block = doc.begin()
            line = block.layout().lineAt(0)
            block_rect = doc.documentLayout().blockBoundingRect(block)
            x = line.cursorToX(3)[0] + block_rect.x()
            y = block_rect.y() + line.height()/2 + item.text_offset()
            point = self.editor.canvas.mapFromScene(item.mapToScene(QPointF(x, y)))
            QTest.mouseClick(self.editor.canvas.viewport(), Qt.LeftButton, Qt.NoModifier, point)
            self.assertEqual(item.textCursor().position(), 3, alignment)
            rectangle = item.inputMethodQuery(Qt.ImCursorRectangle)
            self.assertAlmostEqual(rectangle.top(), block_rect.y()+item.text_offset(), delta=1)
            cursor = item.textCursor()
            cursor.movePosition(QTextCursor.End)
            item.setTextCursor(cursor)
            event = QInputMethodEvent()
            event.setCommitString('한글')
            self.editor.scene.sendEvent(item, event)
            self.assertEqual(item.model.text, 'ABCDEFG한글')
            self.editor.undo()
            self.assertEqual(item.model.text, 'ABCDEFG')
            item.finish_edit()

    def test_overflow_resize_multi_selection_and_alignment_undo(self):
        page = self.install(1, text=True)[0]
        box = page.objects[0]
        self.editor.items_by_id[box.id].setSelected(True)
        self.editor.inspector_vertical_align.activated.emit(2)
        self.assertEqual(box.vertical_align, 'bottom')
        item = self.editor.items_by_id[box.id]
        before = item.text_offset()
        box.height += 50
        self.assertAlmostEqual(item.text_offset(), before+50)
        box.height -= 50
        self.editor.undo()
        self.assertEqual(self.editor.current_page.objects[0].vertical_align, 'top')
        self.editor.redo()
        self.assertEqual(self.editor.current_page.objects[0].vertical_align, 'bottom')
        box = self.editor.current_page.objects[0]
        box.paragraphs = [Paragraph([Run('long\n' * 30)])]
        item = TextItem(box, SimpleNamespace(changed=lambda: None))
        self.assertTrue(item.has_overflow())
        self.assertEqual(item.text_offset(), 0)
        box.writing_mode = 'vertical-rl'
        self.assertEqual(item.text_offset(), 0)

    def test_home_and_inspector_alignment_sync_multiple_boxes_and_undo(self):
        page = self.install(1, text=True)[0]
        first = page.objects[0]
        second = deepcopy(first)
        from studio.model import uid
        second.id = uid()
        second.y = 70
        second.vertical_align = 'bottom'
        page.objects.append(second)
        self.editor.set_canvas_tool('select')
        self.editor.rebuild_scene([first.id, second.id])
        home = self.editor.vertical_align_box
        inspector = self.editor.inspector_vertical_align
        self.assertEqual(home.currentIndex(), -1)
        self.assertEqual(inspector.currentIndex(), -1)
        self.assertTrue(home.isEnabled())
        home.activated.emit(1)
        self.assertEqual([box.vertical_align for box in page.objects], ['center', 'center'])
        self.assertEqual(inspector.currentIndex(), 1)
        self.assertEqual(home.currentIndex(), 1)
        inspector.activated.emit(2)
        self.assertEqual(home.currentIndex(), 2)
        self.assertEqual([box.vertical_align for box in page.objects], ['bottom', 'bottom'])
        self.editor.undo()
        self.assertEqual([box.vertical_align for box in self.editor.current_page.objects], ['center', 'center'])
        self.assertEqual(len(self.editor.selected()), 2)
        self.assertEqual(home.currentIndex(), 1)
        self.assertEqual(inspector.currentIndex(), 1)
        self.editor.redo()
        self.assertEqual(home.currentIndex(), 2)
        box = self.editor.current_page.objects[0]
        box.locked = True
        self.editor.update_tools()
        self.assertFalse(home.isEnabled())
        self.assertFalse(inspector.isEnabled())
        box.locked = False
        box.writing_mode = 'vertical-rl'
        self.editor.update_tools()
        self.assertFalse(home.isEnabled())
        home.activated.emit(0)
        self.assertEqual(box.vertical_align, 'bottom')

    def test_inspector_fields_fit_narrow_panel_and_larger_fonts(self):
        page = self.install(1, text=True)[0]
        self.editor.items_by_id[page.objects[0].id].setSelected(True)
        self.editor.update_tools()
        original_font = self.app.font()
        try:
            for font_size, window_width, panel_width in [(10, 900, 280), (10, 1440, 304), (13, 900, 280), (13, 1440, 420)]:
                self.app.setFont(QFont('Malgun Gothic', font_size))
                self.editor.resize(window_width, 700)
                self.editor.resizeDocks([self.editor.source_dock], [panel_width], Qt.Horizontal)
                for key in ['source', 'format', 'layout', 'links']:
                    self.editor.show_inspector(key)
                    for _ in range(5):
                        self.app.processEvents()
                    scroll = self.editor.inspector.stack.currentWidget()
                    content = scroll.widget()
                    viewport_width = scroll.viewport().width()
                    context = (font_size, window_width, panel_width, key)
                    self.assertLessEqual(content.width(), viewport_width, context)
                    self.assertEqual(scroll.horizontalScrollBar().maximum(), 0, context)
                    for widget in content.findChildren(QWidget):
                        if not isinstance(widget, (QComboBox, QDoubleSpinBox, QToolButton, QPushButton)) or not widget.isVisible():
                            continue
                        left = widget.mapTo(content, QPoint(0, 0)).x()
                        self.assertGreaterEqual(left, 0, (context, widget.objectName()))
                        self.assertLessEqual(left + widget.width(), viewport_width, (context, type(widget).__name__))
                    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
                    self.app.processEvents()
                    self.assertLessEqual(content.width(), scroll.viewport().width(), context)
        finally:
            self.app.setFont(original_font)


if __name__ == '__main__':
    unittest.main()
