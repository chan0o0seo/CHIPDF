"""Group transforms, editing scope, guides, and paragraph preservation."""
from test_studio import APP, StudioTests
from copy import deepcopy
import unittest

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QInputMethodEvent, QTextCursor
from PySide6.QtTest import QTest

from studio.model import GroupBox, Paragraph, Project, Run, ShapeBox, Style, TextBox
from studio.richtext import extract


class LayoutTests(unittest.TestCase):
    setUp = StudioTests.setUp
    insert = StudioTests.insert
    pixels = StudioTests.pixels

    def tearDown(self):
        # The offscreen test platform lacks Windows' clipboard shutdown handling.
        # Release this test's Python-owned MIME payload before Qt is destroyed.
        if APP.platformName() == 'offscreen':
            APP.clipboard().clear()
        StudioTests.tearDown(self)

    def select(self, *ids):
        self.editor.scene.clearSelection()
        for key in ids:
            self.editor.items_by_id[key].setSelected(True)
        APP.processEvents()

    def pair(self):
        a = self.editor.add_shape('rect')
        b = self.editor.add_object(TextBox(paragraphs=[Paragraph([Run('그룹 안의 번역문', Style(size=18))])]), '텍스트')
        a.x, a.y, a.width, a.height, a.fill = 110, 180, 400, 160, '#daeadc'
        b.x, b.y, b.width, b.height = 130, 220, 330, 60
        self.editor.rebuild_scene([a.id, b.id])
        return a.id, b.id

    def group(self, *ids):
        self.select(*ids)
        self.editor.group_selected()
        return self.editor.selected()[0].model.id

    def corners(self, key):
        item = self.editor.items_by_id[key]
        return [item.mapToScene(point) for point in (QPointF(), QPointF(item.model.width, 0), QPointF(item.model.width, item.model.height))]

    def assert_points(self, a, b):
        for p, q in zip(a, b):
            self.assertAlmostEqual(p.x(), q.x(), places=6)
            self.assertAlmostEqual(p.y(), q.y(), places=6)

    def transform(self, key, angle, scale):
        self.editor.begin_operation()
        item = self.editor.items_by_id[key]
        item.setRotation(angle)
        item.setScale(scale)
        self.editor.finish_operation('그룹 변환')

    def test_group_click_selects_whole_and_real_mouse_transforms(self):
        a, b = self.pair()
        expected = self.pixels(self.editor.render_image())
        g = self.group(a, b)
        self.assertEqual(expected, self.pixels(self.editor.render_image()))
        self.editor.scene.clearSelection()
        view = self.editor.canvas
        point = view.mapFromScene(self.editor.items_by_id[b].mapToScene(QPointF(20, 20)))
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, point)
        self.assertEqual([i.model.id for i in self.editor.selected()], [g])
        self.assertFalse(self.editor.items_by_id[b].isSelected())
        item = self.editor.items_by_id[g]
        def drag(start, end):
            p, q = [view.mapFromScene(item.mapToScene(v)) for v in (start, end)]
            QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.AltModifier, p)
            QTest.mouseMove(view.viewport(), q, 20)
            QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.AltModifier, q)
            APP.processEvents()
        before = item.pos()
        drag(QPointF(40, 40), QPointF(85, 70))
        self.assertGreater(item.pos().x(), before.x()+30)
        w, h = item.model.width, item.model.height
        anchor = item.mapToScene(QPointF())
        drag(QPointF(w, h), QPointF(w*1.18, h*1.18))
        self.assertGreater(item.model.scale, 1.1)
        self.assert_points([anchor], [item.mapToScene(QPointF())])
        drag(QPointF(w/2, -23), QPointF(w+10, h/2))
        self.assertGreater(abs(item.model.rotation), 60)
        self.editor.undo()
        self.assertAlmostEqual(self.editor.items_by_id[g].model.rotation, 0)

    def test_nested_group_ungroup_preserves_world_layout_and_opacity(self):
        a, b = self.pair()
        inner = self.group(a, b)
        self.transform(inner, 23, .85)
        c = self.editor.add_shape('ellipse')
        self.editor.items_by_id[c.id].setPos(420, 370)
        self.editor.sync_positions()
        outer = self.group(inner, c.id)
        self.transform(outer, -17, 1.15)
        self.editor.set_property('opacity', .7, '투명도')
        before = {key: self.corners(key) for key in (a, b, c.id)}
        self.editor.ungroup_selected()
        for key in before:
            self.assert_points(before[key], self.corners(key))
        self.select(inner)
        self.editor.ungroup_selected()
        for key in before:
            self.assert_points(before[key], self.corners(key))
            self.assertAlmostEqual(self.editor.items_by_id[key].model.opacity, .7)
        path = self.root / '중첩해제.twproj'
        expected = self.pixels(self.editor.render_image())
        self.editor.save_to(path)
        self.editor.load_path(path)
        self.assertEqual(expected, self.pixels(self.editor.render_image()))

    def test_double_click_group_edit_ime_and_escape(self):
        a, b = self.pair()
        g = self.group(a, b)
        view = self.editor.canvas
        point = view.mapFromScene(self.editor.items_by_id[b].mapToScene(QPointF(20, 20)))
        QTest.mouseDClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, point)
        APP.processEvents()
        self.assertEqual(self.editor.active_group_id, g)
        self.assertTrue(self.editor.leave_group_action.isVisible())
        item = self.editor.items_by_id[b]
        item.begin_edit()
        cursor = item.textCursor()
        cursor.movePosition(QTextCursor.End)
        item.setTextCursor(cursor)
        event = QInputMethodEvent()
        event.setCommitString(' 수정')
        APP.sendEvent(self.editor.scene, event)
        self.assertTrue(item.model.text.endswith(' 수정'))
        QTest.keyClick(view.viewport(), Qt.Key_Escape)
        self.assertIsNone(self.editor.editing_item())
        self.assertEqual(self.editor.active_group_id, g)
        QTest.keyClick(view.viewport(), Qt.Key_Escape)
        self.assertEqual(self.editor.active_group_id, '')
        self.assertEqual(self.editor.selected()[0].model.id, g)

    def test_child_move_reframes_rotated_group_without_moving_sibling(self):
        a, b = self.pair()
        g = self.group(a, b)
        self.transform(g, 34, 1.25)
        self.editor.enter_group(g)
        self.select(b)
        fixed, moving = self.corners(a), self.corners(b)
        self.editor.nudge(-160, 25)
        self.assert_points(fixed, self.corners(a))
        self.assert_points([p+QPointF(-160, 25) for p in moving], self.corners(b))
        expected = self.pixels(self.editor.render_image())
        path = self.root / '안쪽편집.twproj'
        self.editor.save_to(path)
        self.editor.load_path(path)
        self.assertEqual(expected, self.pixels(self.editor.render_image()))

    def test_group_clipboard_duplicate_and_delete_undo(self):
        a, b = self.pair()
        g = self.group(a, b)
        self.editor.copy_objects()
        self.editor.paste_objects()
        pasted = self.editor.selected()[0].model.id
        self.assertNotEqual(g, pasted)
        self.assertEqual(len(self.editor.descendants([pasted])), 3)
        self.editor.duplicate()
        clone = self.editor.selected()[0].model.id
        self.assertEqual(len(self.editor.descendants([clone])), 3)
        ids = [o.id for o in self.editor.project.pages[0].objects]
        self.assertEqual(len(set(ids)), 9)
        self.editor.delete_selected()
        self.assertEqual(len(self.editor.project.pages[0].objects), 6)
        self.editor.undo()
        self.assertEqual(len(self.editor.project.pages[0].objects), 9)
        Project.from_dict(self.editor.project.to_dict())

    def test_group_source_coordinates_and_pending_translation_lock(self):
        a, b = self.pair()
        obj = self.editor.items_by_id[b].model
        obj.source_text, obj.source_rect, obj.erase_rect = '証拠', [10, 15, 90, 40], [8, 13, 94, 44]
        source = deepcopy((obj.source_rect, obj.erase_rect))
        g = self.group(a, b)
        self.transform(g, 15, 1.2)
        self.editor.nudge(40, 35)
        obj = self.editor.items_by_id[b].model
        self.assertEqual(source, (obj.source_rect, obj.erase_rect))
        snapshot = {b: (obj.source_text, obj.text, deepcopy(obj.paragraphs))}
        original = obj.text
        self.editor.toggle_lock()
        self.editor.enter_group(g)
        self.assertEqual(self.editor.active_group_id, '')
        self.editor.items_by_id[b].begin_edit()
        self.assertIsNone(self.editor.editing_item())
        self.editor.accept_translations([(b, '덮어쓰기', None)], snapshot, False)
        self.assertEqual(self.editor.items_by_id[b].model.text, original)
        self.editor.commit_source(b, '잠긴 원문 수정')
        self.assertEqual(self.editor.items_by_id[b].model.source_text, '証拠')

    def test_paste_into_group_remaps_parents_and_rejects_excess_depth_atomically(self):
        a, b = self.pair()
        g = self.group(a, b)
        self.editor.copy_objects()
        self.editor.enter_group(g)
        self.editor.paste_objects()
        pasted = self.editor.selected()[0].model
        self.assertEqual(pasted.parent_id, g)
        self.assertEqual(len(self.editor.descendants([pasted.id])), 3)
        # Reach eight group ancestors; pasting another two-level tree must fail intact.
        current = pasted.id
        for _ in range(6):
            nested = GroupBox(parent_id=current)
            self.editor.project.pages[0].objects.append(nested)
            current = nested.id
        self.editor.active_group_id = current
        self.editor.rebuild_scene()
        before = deepcopy(self.editor.project)
        self.editor.paste_objects()
        self.assertEqual(before, self.editor.project)
        self.assertIn('실패', self.editor.status.text())
        self.assertIsNone(self.editor.operation_before)

    def test_snap_threshold_alt_toggle_and_multi_selection(self):
        a, b = self.pair()
        self.editor.items_by_id[a].setPos(100, 300)
        self.editor.items_by_id[b].setPos(103, 100)
        self.editor.canvas.resetTransform()
        self.select(b)
        item = self.editor.items_by_id[b]
        self.editor.snap_drag(Qt.AltModifier)
        self.assertEqual(item.x(), 103)
        self.assertEqual(self.editor.scene.snap_guides, [])
        self.editor.snap_drag()
        self.assertEqual(item.x(), 100)
        self.assertIn(('x', 100), self.editor.scene.snap_guides)
        item.setX(104)
        self.editor.canvas.scale(2, 2)
        self.editor.snap_drag()
        self.assertEqual(item.x(), 104)
        self.editor.snap_action.setChecked(False)
        item.setX(101)
        self.editor.snap_drag()
        self.assertEqual(item.x(), 101)
        self.editor.snap_action.setChecked(True)
        self.editor.canvas.resetTransform()
        self.select(a, b)
        self.editor.items_by_id[a].setX(2)
        item.setX(130)
        distance = item.pos()-self.editor.items_by_id[a].pos()
        self.editor.snap_drag()
        self.assertEqual(self.editor.items_by_id[a].x(), 0)
        self.assertEqual(distance, item.pos()-self.editor.items_by_id[a].pos())

    def test_guides_and_group_scope_do_not_leak_into_png(self):
        a, b = self.pair()
        g = self.group(a, b)
        expected = self.pixels(self.editor.render_image())
        self.editor.enter_group(g)
        self.select(b)
        self.editor.scene.snap_guides = [('x', 300), ('y', 240)]
        APP.processEvents()
        self.assertEqual(expected, self.pixels(self.editor.render_image()))
        self.assertTrue(self.editor.scene.show_controls)

    def test_paragraph_spacing_changes_layout_preserves_runs_and_undo(self):
        item = self.insert('강조 내용\n다음 문단')
        item.finish_edit()
        obj = item.model
        obj.paragraphs[0].runs = [Run('강조 ', Style(bold=True, color='#a04050')), Run('내용')]
        self.editor.rebuild_scene([obj.id])
        before = deepcopy(self.editor.project)
        height = self.editor.items_by_id[obj.id].document().size().height()
        undo_count = self.editor.undo_stack.count()
        self.editor.apply_paragraph_settings(dict(line_spacing=1.6, space_before=5, space_after=9, margin=16))
        item = self.editor.items_by_id[obj.id]
        self.assertGreater(item.document().size().height(), height+20)
        self.assertEqual(item.document().documentMargin(), 16)
        self.assertEqual(item.model.paragraphs[0].runs, obj.paragraphs[0].runs)
        self.assertEqual(extract(item.document(), '#222222'), item.model.paragraphs)
        self.assertEqual(self.editor.undo_stack.count(), undo_count+1)
        self.editor.undo()
        self.assertEqual(self.editor.project, before)
        self.editor.redo()
        expected = self.pixels(self.editor.render_image())
        path = self.root / '문단.twproj'
        self.editor.save_to(path)
        self.editor.load_path(path)
        self.assertEqual(expected, self.pixels(self.editor.render_image()))

    def test_paragraph_settings_survive_ime_and_translation_candidate(self):
        item = self.insert('문단')
        item.finish_edit()
        key = item.model.id
        self.editor.apply_paragraph_settings(dict(line_spacing=1.3, space_before=3, space_after=7, margin=4))
        item = self.editor.items_by_id[key]
        item.begin_edit()
        event = QInputMethodEvent()
        event.setCommitString('한글')
        APP.sendEvent(self.editor.scene, event)
        item.finish_edit()
        self.assertEqual(item.model.paragraphs[0].line_spacing, 1.3)
        self.editor.set_target(item.model, '후보 번역\n둘째 문단')
        self.assertEqual(item.model.margin, 4)
        for paragraph in item.model.paragraphs:
            self.assertEqual((paragraph.line_spacing, paragraph.space_before, paragraph.space_after), (1.3, 3, 7))

    def test_invalid_group_links_and_paragraph_values_are_rejected(self):
        a, b = self.pair()
        g = self.group(a, b)
        original = self.editor.project.to_dict()
        for mutate in (
                lambda objects: setattr(objects[0], 'parent_id', 'missing'),
                lambda objects: setattr(objects[-1], 'parent_id', objects[-1].id),
                lambda objects: setattr(objects[1].paragraphs[0], 'line_spacing', float('nan')),
                lambda objects: setattr(objects[1], 'margin', -1)):
            trial = deepcopy(self.editor.project)
            mutate(trial.pages[0].objects)
            with self.assertRaises(ValueError):
                Project.from_dict(trial.to_dict())
        self.assertEqual(self.editor.project.to_dict(), original)

    def test_dragging_text_selection_does_not_snap_or_move_box(self):
        a, b = self.pair()
        item = self.editor.items_by_id[b]
        item.setX(self.editor.items_by_id[a].x()+3)
        self.editor.sync_positions()
        item.begin_edit()
        before = item.pos()
        view = self.editor.canvas
        points = [view.mapFromScene(item.mapToScene(p)) for p in (QPointF(12, 18), QPointF(140, 18))]
        QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, points[0])
        QTest.mouseMove(view.viewport(), points[1], 20)
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, points[1])
        self.assertEqual(item.pos(), before)
        self.assertTrue(item.textCursor().hasSelection())
        self.assertEqual(self.editor.scene.snap_guides, [])

    def test_group_copy_to_different_card_drops_descendant_source_links(self):
        a, b = self.pair()
        obj = self.editor.items_by_id[b].model
        obj.source_text, obj.source_rect = '証拠', [10, 15, 90, 40]
        self.group(a, b)
        self.editor.copy_objects()
        image = QImage(800, 800, QImage.Format_ARGB32)
        image.fill(QColor('#ffffff'))
        path = self.root / '다른원본.png'
        image.save(str(path))
        self.editor.load_path(path)
        self.editor.paste_objects()
        objects = self.editor.project.pages[0].objects
        self.assertEqual(len(objects), 3)
        copied = next(o for o in objects if isinstance(o, TextBox))
        self.assertEqual(copied.text, '그룹 안의 번역문')
        self.assertEqual(copied.source_text, '')
        self.assertIsNone(copied.source_rect)
        self.assertEqual(copied.parent_id, self.editor.selected()[0].model.id)

    def test_image_crop_inside_transformed_group_and_reopen(self):
        a, b = self.pair()
        image = QImage(100, 60, QImage.Format_ARGB32)
        image.fill(QColor('#237766'))
        obj = self.editor.insert_qimage(image)
        g = self.group(a, b, obj.id)
        self.transform(g, 18, .8)
        self.editor.enter_group(g)
        self.select(obj.id)
        self.editor.apply_crop(obj.id, [.2, 0, .6, 1])
        self.editor.flip_image('flip_h')
        self.editor.leave_group()
        expected = self.pixels(self.editor.render_image())
        path = self.root / '그룹이미지.twproj'
        self.editor.save_to(path)
        self.editor.load_path(path)
        self.assertEqual(expected, self.pixels(self.editor.render_image()))
        self.assertEqual(self.editor.items_by_id[obj.id].model.image_data, obj.image_data)


if __name__ == '__main__':
    unittest.main()
