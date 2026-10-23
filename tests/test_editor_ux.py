"""Canvas handles, slider undo steps, layers, geometry fields and the quick toolbar."""
import base64
from io import BytesIO
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / '.deps'), str(ROOT)]
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtWidgets import QApplication

from studio.agent_cli import load_fonts
from studio.document_io import png_data
from studio.model import ImageBox, Page, Paragraph, Project, Run, Style, TextBox
from studio.window import Editor


def png(color='#808080', size=(80, 60)):
    encoded = BytesIO()
    Image.new('RGB', size, color).save(encoded, 'PNG')
    return base64.b64encode(encoded.getvalue()).decode()


class EditorExperienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        load_fonts([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'qa', prefix='ux-')
        self.work = Path(self.temp.name)
        self.editor = Editor(self.work / 'data')
        self.editor.resize(1400, 900)
        self.editor.show()
        page = Page(width=800, height=600, name='Page')
        page.asset = f'assets/{page.id}.png'
        image = QImage(800, 600, QImage.Format_RGB32)
        image.fill(Qt.white)
        self.text = TextBox(x=100, y=100, width=300, height=120, z=1,
                            paragraphs=[Paragraph([Run('ABC', Style(size=18, color='#000000'))])])
        self.image = ImageBox(x=450, y=300, width=200, height=150, z=0, image_data=png())
        page.objects = [self.text, self.image]
        self.editor.install_collection(Project(name='UX', pages=[page]), {page.asset: png_data(image)})
        # Importing new material starts in sentence selection; editing uses the select tool.
        self.editor.set_canvas_tool('select')
        self.editor.canvas.fit_page()
        self.settle()

    def tearDown(self):
        self.editor.close()
        self.temp.cleanup()

    def settle(self):
        for _ in range(6):
            self.app.processEvents()

    def item(self, obj):
        return self.editor.items_by_id[obj.id]

    def current(self, obj):
        # Undo restores a snapshot, which replaces the model objects.
        return next(o for o in self.editor.current_page.objects if o.id == obj.id)

    def select(self, *objects):
        self.editor.scene.clearSelection()
        for obj in objects:
            self.item(obj).setSelected(True)
        self.settle()

    def drag(self, start, end):
        """Press, move and release the left button at scene points on the canvas."""
        viewport = self.editor.canvas.viewport()
        points = [self.editor.canvas.mapFromScene(point) for point in (start, end)]
        steps = [points[0] + (points[1]-points[0])*t/6 for t in range(7)]
        def send(kind, point, buttons):
            event = QMouseEvent(kind, QPointF(point), QPointF(viewport.mapToGlobal(point)),
                                Qt.LeftButton, buttons, Qt.NoModifier)
            QApplication.sendEvent(viewport, event)
        send(QEvent.MouseButtonPress, steps[0], Qt.LeftButton)
        for point in steps[1:]:
            send(QEvent.MouseMove, point, Qt.LeftButton)
        send(QEvent.MouseButtonRelease, steps[-1], Qt.NoButton)
        self.settle()

    def test_text_has_eight_handles_and_locked_ratio_image_has_corners(self):
        self.assertEqual(len(self.item(self.text).handle_names()), 8)
        self.assertEqual(set(self.item(self.image).handle_names()), {'tl', 'tr', 'br', 'bl'})
        self.image.aspect_locked = False
        self.assertEqual(len(self.item(self.image).handle_names()), 8)
        # Handles keep their screen size at any zoom.
        self.select(self.text)
        before = self.item(self.text).handle_rects()['br'].width()
        self.editor.canvas.zoom(2)
        self.settle()
        self.assertAlmostEqual(self.item(self.text).handle_rects()['br'].width(), before/2, delta=.01)

    def test_left_handle_resizes_and_keeps_the_right_edge(self):
        self.select(self.text)
        right = self.text.x + self.text.width
        start = QPointF(self.text.x, self.text.y + self.text.height/2)
        self.drag(start, start + QPointF(-60, 30))
        self.assertAlmostEqual(self.text.width, 360, delta=3)
        self.assertAlmostEqual(self.text.height, 120, delta=.5)
        self.assertAlmostEqual(self.text.x + self.text.width, right, delta=1)
        self.editor.undo()
        self.assertAlmostEqual(self.current(self.text).width, 300, delta=.01)

    def test_corner_handle_keeps_locked_image_ratio_and_opposite_corner(self):
        self.select(self.image)
        corner = QPointF(self.image.x, self.image.y)
        bottom_right = (self.image.x + self.image.width, self.image.y + self.image.height)
        self.drag(corner, corner + QPointF(-80, -10))
        self.assertAlmostEqual(self.image.width / self.image.height, 200/150, delta=.01)
        self.assertGreater(self.image.width, 260)
        self.assertAlmostEqual(self.image.x + self.image.width, bottom_right[0], delta=1)
        self.assertAlmostEqual(self.image.y + self.image.height, bottom_right[1], delta=1)

    def test_slider_drag_previews_and_records_one_undo_step(self):
        self.select(self.text)
        field = self.editor.inspector_outline_width
        before = self.editor.undo_stack.count()
        field.dragStarted.emit()
        for value in (2, 4, 6):
            field.previewed.emit(value)
            self.assertEqual(self.text.outline_width, value)
        field.committed.emit(6)
        self.assertEqual(self.editor.undo_stack.count(), before + 1)
        self.editor.undo()
        self.assertEqual(self.current(self.text).outline_width, 0)

    def test_separate_opacity_and_shadow_controls_update_the_model(self):
        self.select(self.text)
        self.editor.inspector_text_opacity.committed.emit(40)
        self.editor.inspector_fill_opacity.committed.emit(25)
        self.assertAlmostEqual(self.text.text_opacity, .4)
        self.assertAlmostEqual(self.text.fill_opacity, .25)
        self.assertEqual(self.text.opacity, 1)
        self.editor.inspector_shadow.setChecked(True)
        self.assertTrue(self.text.shadow_enabled)
        self.editor.inspector_shadow_angle.set_value(90)
        self.editor.inspector_shadow_distance.set_value(10)
        self.editor.inspector_shadow_distance.committed.emit(10)
        self.assertAlmostEqual(self.text.shadow_dx, 0, delta=.01)
        self.assertAlmostEqual(self.text.shadow_dy, 10, delta=.01)
        self.editor.inspector_highlight.picked.emit('#ffee00')
        self.assertEqual(self.text.highlight, '#ffee00')
        self.assertIn('#ffee00', self.editor.palette_colors()[1])

    def test_letter_spacing_and_image_adjustment_controls(self):
        self.select(self.text)
        self.editor.inspector_letter_spacing.committed.emit(200)
        self.assertEqual(self.text.paragraphs[0].runs[0].style.letter_spacing, 200)
        self.select(self.image)
        self.editor.inspector_image_adjust['brightness'].committed.emit(30)
        self.editor.inspector_corner.committed.emit(20)
        self.assertEqual((self.image.brightness, self.image.corner_radius), (30, 20))

    def test_layers_list_reorders_objects(self):
        self.editor.show_inspector('layers')
        self.select(self.text)
        layers = self.editor.inspector_layers
        self.assertEqual([layers.item(i).data(Qt.UserRole) for i in range(layers.count())], [self.text.id, self.image.id])
        self.assertTrue(layers.item(0).isSelected())
        moved = layers.model().moveRow(layers.model().index(1, 0).parent(), 1, layers.model().index(0, 0).parent(), 0)
        if not moved:
            row = layers.takeItem(1)
            layers.insertItem(0, row)
            self.editor._layers_moved()
        self.assertGreater(self.image.z, self.text.z)
        self.editor.undo()
        self.assertGreater(self.current(self.text).z, self.current(self.image).z)
        # Clicking a layer selects the object on the canvas.
        self.editor.scene.clearSelection()
        self.settle()
        row = next(layers.item(i) for i in range(layers.count()) if layers.item(i).data(Qt.UserRole) == self.image.id)
        row.setSelected(True)
        self.assertTrue(self.editor.items_by_id[self.image.id].isSelected())

    def test_geometry_fields_edit_the_selection(self):
        self.select(self.text)
        self.editor._geometry_changed('x', 222)
        self.editor._geometry_changed('width', 333)
        self.assertEqual((self.text.x, self.text.width), (222, 333))
        self.editor.arrange('right')
        self.assertAlmostEqual(self.text.x + self.text.width, 800, delta=.5)

    def test_quick_bar_follows_selection(self):
        self.editor.scene.clearSelection()
        self.settle()
        self.assertFalse(self.editor.quick_bar.isVisible())
        self.select(self.text)
        self.assertTrue(self.editor.quick_bar.isVisible())
        bar = self.editor.quick_bar.geometry()
        box = self.editor.canvas.mapFromScene(self.item(self.text).mapRectToScene(0, 0, 300, 120)).boundingRect()
        self.assertLessEqual(bar.bottom(), box.top())
        self.editor.duplicate_action.trigger()
        self.assertEqual(len(self.editor.current_page.objects), 3)


if __name__ == '__main__':
    unittest.main()
