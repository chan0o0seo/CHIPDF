"""Reusable appearance never transports wording or overrides incompatible cards."""
from test_studio import APP, StudioTests
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from studio.model import GroupBox, Paragraph, Run, ShapeBox, Style, TextBox, uid
from studio.presets import apply_style, validate_presets
from studio.window import Editor


class PresetTests(unittest.TestCase):
    setUp = StudioTests.setUp
    tearDown = StudioTests.tearDown
    insert = StudioTests.insert

    def select(self, *ids):
        self.editor.scene.clearSelection()
        for key in ids:
            self.editor.items_by_id[key].setSelected(True)

    def cards(self, count=3):
        editor = self.editor
        template = deepcopy(editor.current_page)
        editor.project.pages = []
        for index in range(count):
            page = deepcopy(template)
            page.id, page.asset, page.name = uid(), f'assets/{uid()}.png', f'카드 {index+1}'
            page.objects = [TextBox(x=35+index*13, y=55+index*15, width=420-index*17, height=180, rotation=index*3,
                                   paragraphs=[Paragraph([Run(f'비공개 문구 {index+1} 첫째', Style(size=19+index)),
                                                         Run(' 굵은 부분', Style(size=24, bold=True))], 'center', 1.2, 3, 7)],
                                   source_text=f'비공개 원문 {index}', source_rect=[10, 20, 90, 130],
                                   erase_rect=[11, 21, 89, 129], candidate_text='비공개 후보', candidate_source='비공개 후보 원문',
                                   source_confirmed=True, target_origin='machine', reviewed=True, margin=13,
                                   fill='#ffffff', opacity=.7, writing_mode='vertical-rl' if index == 0 else 'horizontal'),
                            TextBox(x=40+index*12, y=330+index*14, width=390, height=160,
                                    paragraphs=[Paragraph([Run(f'비공개 문구 {index+1} 둘째')])]),
                            ShapeBox(x=500, y=650, width=80, height=80, fill='#ddaabb')]
            editor.project.pages.append(page)
            editor.assets[page.asset] = editor.original
        editor.activate_page(0)
        editor.refresh_card_list()
        editor.undo_stack.clear()
        return editor.project.pages

    def reopened(self):
        editor = Editor(self.editor.data_dir, auto_ocr=False)
        self.addCleanup(lambda: (setattr(editor, 'dirty', False), editor.close(), editor.deleteLater(), APP.processEvents()))
        return editor

    def test_saved_style_is_content_free_persistent_and_preserves_target_metadata(self):
        pages = self.cards()
        source, target = pages[0].objects[0], pages[0].objects[1]
        self.select(source.id)
        preset = self.editor.save_text_preset('본문 세로')
        raw = self.editor.presets_path.read_text('utf-8')
        self.assertNotIn('비공개', raw)
        self.assertNotIn('source_rect', raw)
        self.assertEqual(self.reopened().presets, self.editor.presets)
        before = deepcopy(target)
        before_project = deepcopy(self.editor.project)
        expected = deepcopy(target)
        apply_style(expected, preset)
        self.select(target.id)
        self.assertEqual(self.editor.apply_text_preset('본문 세로'), 1)
        result = self.editor.items_by_id[target.id].model
        self.assertEqual(result, expected)
        self.assertEqual(result.text, before.text)
        self.assertEqual(result.writing_mode, 'vertical-rl')
        self.editor.undo()
        self.assertEqual(self.editor.project, before_project)
        self.editor.redo()
        self.assertEqual(self.editor.items_by_id[target.id].model, expected)

    def test_style_applies_whole_selection_in_one_undo_without_marking_reviewed_text_manual(self):
        self.cards()
        source = self.editor.current_page.objects[0]
        self.select(source.id)
        self.editor.save_text_preset('읽기 쉬운 본문')
        self.editor.switch_page(1)
        ids = [box.id for box in self.editor.current_page.objects if isinstance(box, TextBox)]
        self.select(*ids)
        before, index = deepcopy(self.editor.project), self.editor.undo_stack.index()
        self.assertEqual(self.editor.apply_text_preset('읽기 쉬운 본문'), 2)
        self.assertEqual(self.editor.undo_stack.index(), index+1)
        target = self.editor.current_page.objects[0]
        self.assertEqual(target.text, before.pages[1].objects[0].text)
        self.assertEqual(target.target_origin, 'machine')
        self.assertTrue(target.reviewed)
        self.assertEqual(len({run.style.size for paragraph in target.paragraphs for run in paragraph.runs}), 1)
        self.assertEqual({item.model.id for item in self.editor.selected()}, set(ids))
        self.editor.undo()
        self.assertEqual(self.editor.project, before)

    def test_corrupt_or_future_store_is_never_overwritten_on_next_save(self):
        self.insert('새 텍스트').finish_edit()
        for raw in (b'{broken', b'{"version": 99,"styles":{},"layouts":{}}'):
            self.editor.presets_path.parent.mkdir(parents=True, exist_ok=True)
            self.editor.presets_path.write_bytes(raw)
            restored = self.reopened()
            self.assertTrue(restored.presets_load_error)
            with self.assertRaises(ValueError):
                restored._write_presets({'version': 1, 'styles': {}, 'layouts': {}})
            self.assertEqual(restored.presets_path.read_bytes(), raw)
            self.assertFalse(restored.save_text_preset_action.isEnabled())

    def test_failed_atomic_save_and_external_changes_preserve_memory_and_file(self):
        self.insert('아무 데도 저장되지 않는 문구').finish_edit()
        self.editor.save_text_preset('첫 서식')
        before = deepcopy(self.editor.presets)
        disk = self.editor.presets_path.read_bytes()
        with patch('studio.presets.atomic_write', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                self.editor.save_text_preset('실패한 서식')
        self.assertEqual(self.editor.presets, before)
        self.assertEqual(self.editor.presets_path.read_bytes(), disk)
        modified = disk+b'\n'
        self.editor.presets_path.write_bytes(modified)
        with self.assertRaises(ValueError):
            self.editor.save_text_preset('다른 창 보호')
        self.assertEqual(self.editor.presets, before)
        self.assertEqual(self.editor.presets_path.read_bytes(), modified)

    def test_store_rejects_unknown_content_fields_bounds_and_invalid_modes(self):
        self.cards()
        self.select(self.editor.current_page.objects[0].id)
        self.editor.save_text_preset('기본')
        self.editor.save_layout_preset('두 칸')
        for change in (lambda store: store['styles']['기본'].update(source_text='never'),
                       lambda store: store['styles']['기본']['style'].update(size=True),
                       lambda store: store['styles']['기본'].update(writing_mode='diagonal'),
                       lambda store: store['layouts']['두 칸']['slots'][0]['geometry'].update(scale=float('nan')),
                       lambda store: store['layouts']['두 칸']['slots'][0].update(text='never'),
                       lambda store: store['layouts']['두 칸'].update(width=0)):
            trial = deepcopy(self.editor.presets)
            change(trial)
            with self.assertRaises(ValueError):
                validate_presets(trial)

    def test_layout_preview_and_multi_page_geometry_only_preserve_words_styles_and_sources(self):
        pages = self.cards()
        self.editor.save_layout_preset('두 영역')
        self.assertNotIn('비공개', self.editor.presets_path.read_text('utf-8'))
        self.assertEqual(self.reopened().presets, self.editor.presets)
        candidates = self.editor.layout_candidates('두 영역')
        self.assertTrue(all(entry['eligible'] for entry in candidates))
        self.assertEqual(candidates[1]['mapping'][0]['text'], pages[1].objects[0].text)
        before = deepcopy(self.editor.project)
        selected_id = pages[0].objects[0].id
        self.select(selected_id)
        self.editor.card_list.item(1).setSelected(True)
        self.editor.card_list.item(2).setSelected(True)
        self.assertEqual(self.editor.apply_layout_preset('두 영역', [pages[1].id, pages[2].id]), 2)
        self.assertEqual(self.editor.undo_stack.count(), 1)
        self.assertEqual(self.editor.page_index, 0)
        self.assertEqual([item.model.id for item in self.editor.selected()], [selected_id])
        self.assertEqual(len(self.editor.card_list.selectedItems()), 3)
        for index in (1, 2):
            for box_index in (0, 1):
                target = self.editor.project.pages[index].objects[box_index]
                expected = deepcopy(before.pages[index].objects[box_index])
                for key, value in self.editor.presets['layouts']['두 영역']['slots'][box_index]['geometry'].items():
                    setattr(expected, key, value)
                self.assertEqual(target, expected)
            self.assertEqual(self.editor.project.pages[index].objects[2], before.pages[index].objects[2])
        after = deepcopy(self.editor.project)
        self.editor.switch_page(2)
        self.editor.undo()
        self.assertEqual(self.editor.project, before)
        self.assertEqual(self.editor.page_index, 0)
        self.editor.redo()
        self.assertEqual(self.editor.project, after)

    def test_layout_optional_uniform_style_retains_source_and_review_state(self):
        pages = self.cards()
        self.editor.save_layout_preset('글자도 재사용')
        before = deepcopy(pages[1].objects[0])
        self.editor.apply_layout_preset('글자도 재사용', [pages[1].id], include_style=True)
        target = self.editor.project.pages[1].objects[0]
        self.assertEqual(target.text, before.text)
        self.assertEqual(target.source_rect, before.source_rect)
        self.assertEqual(target.erase_rect, before.erase_rect)
        self.assertEqual(target.source_text, before.source_text)
        self.assertEqual(target.target_origin, before.target_origin)
        self.assertEqual(target.reviewed, before.reviewed)
        self.assertEqual(target.fill, before.fill)
        self.assertEqual(target.opacity, before.opacity)
        self.assertEqual(target.writing_mode, 'vertical-rl')

    def test_ineligible_locked_grouped_size_or_count_rejected_without_partial_change(self):
        pages = self.cards(5)
        self.editor.save_layout_preset('정상 카드')
        pages[1].objects[0].locked = True
        group = GroupBox(locked=True)
        pages[2].objects.append(group)
        pages[2].objects[0].parent_id = group.id
        pages[3].width += 1
        pages[4].objects = pages[4].objects[1:]
        candidates = self.editor.layout_candidates('정상 카드')
        self.assertTrue(candidates[0]['eligible'])
        self.assertTrue(all(not entry['eligible'] for entry in candidates[1:]))
        before = deepcopy(self.editor.project)
        for target in pages[1:]:
            with self.assertRaises(ValueError):
                self.editor.apply_layout_preset('정상 카드', [pages[0].id, target.id])
            self.assertEqual(self.editor.project, before)
            self.assertEqual(self.editor.undo_stack.count(), 0)
        with self.assertRaises(ValueError):
            self.editor.apply_layout_preset('정상 카드', ['unknown'])
        with self.assertRaises(ValueError):
            self.editor.apply_layout_preset('정상 카드', [pages[0].id, pages[0].id])

    def test_grouped_style_target_obeys_ancestor_lock(self):
        pages = self.cards()
        source = pages[0].objects[0]
        self.select(source.id)
        self.editor.save_text_preset('글꼴')
        group = GroupBox(locked=True)
        source.parent_id = group.id
        self.editor.current_page.objects.append(group)
        self.editor.active_group_id = group.id
        self.editor.rebuild_scene([source.id])
        before = deepcopy(self.editor.project)
        with self.assertRaises(ValueError):
            self.editor.apply_text_preset('글꼴')
        self.assertEqual(self.editor.project, before)

    def test_existing_quick_style_copy_is_independent_of_saved_presets(self):
        pages = self.cards()
        source, target = pages[0].objects[:2]
        self.select(source.id)
        self.editor.copy_style()
        copied = deepcopy(self.editor.copied_style)
        self.editor.save_text_preset('영구 보관')
        self.select(target.id)
        margin, writing_mode = target.margin, target.writing_mode
        self.editor.paste_style()
        result = self.editor.items_by_id[target.id].model
        self.assertEqual(result.paragraphs[0].runs[0].style, copied)
        self.assertEqual(result.margin, margin)
        self.assertEqual(result.writing_mode, writing_mode)
        self.assertEqual(list(self.editor.presets['styles']), ['영구 보관'])


if __name__ == '__main__':
    unittest.main()
