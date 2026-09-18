"""Behavioral coverage for recognition, draft review and asynchronous data loss."""
from test_studio import APP, ROOT, StudioTests
from copy import deepcopy
import base64
import io
import json
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image, ImageDraw
from PySide6.QtGui import QInputMethodEvent, QTextCursor
from studio.model import Project, Paragraph, Run, TextBox
from studio.recognition import Region, prepare_patch, restored_background
from studio.translation import LocalTranslator


class WorkflowTests(unittest.TestCase):
    setUp = StudioTests.setUp
    tearDown = StudioTests.tearDown
    insert = StudioTests.insert

    def pump(self, condition, timeout=10):
        deadline = time.monotonic() + timeout
        while not condition():
            APP.processEvents()
            time.sleep(.005)
            self.assertLess(time.monotonic(), deadline, "Background job timed out")
        APP.processEvents()

    def regions(self):
        self.editor.accept_regions([Region("原文一", [40, 40, 240, 35], 90, 22),
                                    Region("原文二", [40, 140, 240, 35], 85, 22)])
        return self.editor.project.pages[0].objects

    def test_recognition_appends_without_replacing_manual_objects(self):
        item = self.insert("수동 입력")
        item.finish_edit()
        before = deepcopy(item.model)
        self.editor.accept_regions([Region("重複原文", [before.x, before.y, before.width, before.height], 90, 20),
                                    Region("新しい原文", [10, 10, 200, 30], 90, 20)])
        objects = self.editor.project.pages[0].objects
        self.assertEqual(objects[0], before)
        self.assertEqual(len(objects), 2)
        self.editor.accept_regions([Region("再認識", [10, 10, 200, 30], 90, 20)])
        self.assertEqual(len(objects), 2)

    def test_source_correction_invalidates_candidate_but_preserves_target(self):
        obj = self.regions()[0]
        self.editor.set_target(obj, "직접 고친 번역")
        obj.candidate_text, obj.candidate_source = "이전 후보", obj.source_text
        self.editor.rebuild_scene([obj.id])
        before = deepcopy(obj)
        self.editor.commit_source(obj.id, "修正された原文")
        self.assertEqual(obj.text, before.text)
        self.assertEqual(obj.candidate_text, "")
        self.assertTrue(obj.source_confirmed)
        self.editor.undo()
        self.assertEqual(self.editor.items_by_id[obj.id].model, before)

    def test_candidate_only_applies_explicitly_and_is_undoable(self):
        obj = self.regions()[0]
        self.editor.set_target(obj, "현재 번역")
        self.editor.rebuild_scene([obj.id])
        snapshot = {obj.id: (obj.source_text, obj.text, deepcopy(obj.paragraphs))}
        self.editor.accept_translations([(obj.id, "새 번역", None)], snapshot, True)
        self.assertEqual(obj.text, "현재 번역")
        self.editor.apply_candidate()
        self.assertEqual(obj.text, "새 번역")
        self.editor.undo()
        restored = self.editor.items_by_id[obj.id].model
        self.assertEqual(restored.text, "현재 번역")
        self.assertEqual(restored.candidate_text, "새 번역")

    def test_live_typing_is_preserved_when_worker_finishes(self):
        obj = self.regions()[0]
        entered, release = threading.Event(), threading.Event()
        class Translator:
            def translate(self, source, cancelled):
                entered.set()
                release.wait(5)
                return "기계 초안"
        self.editor.translator = Translator()
        self.editor.start_translation([obj], candidates=False)
        self.pump(entered.is_set)
        item = self.editor.items_by_id[obj.id]
        item.begin_edit()
        event = QInputMethodEvent()
        event.setCommitString("내가 입력한 번역")
        APP.sendEvent(self.editor.scene, event)
        release.set()
        self.pump(lambda: self.editor.job is None)
        self.assertEqual(obj.text, "내가 입력한 번역")
        self.assertIn("변경 보존 1개", self.editor.status.text())

    def test_source_or_format_changed_since_request_is_preserved(self):
        a, b = self.regions()
        snapshot = {o.id: (o.source_text, o.text, deepcopy(o.paragraphs)) for o in (a, b)}
        self.editor.commit_source(a.id, "新しい原文")
        b.paragraphs[0].runs[0].style.bold = True
        self.editor.accept_translations([(a.id, "오래된 번역", None), (b.id, "오래된 서식", None)], snapshot, False)
        self.assertFalse(a.text or b.text)
        self.assertTrue(b.paragraphs[0].runs[0].style.bold)

    def test_cancel_keeps_completed_drafts_and_resume_only_fills_missing(self):
        a, b = self.regions()
        entered, release = threading.Event(), threading.Event()
        class Translator:
            calls = []
            def translate(self, source, cancelled):
                self.calls.append(source)
                if source == b.source_text and len(self.calls) == 2:
                    entered.set()
                    release.wait(5)
                return "초안 " + source
        translator = Translator()
        self.editor.translator = translator
        self.editor.translate_missing()
        self.pump(entered.is_set)
        self.editor.cancel_job()
        release.set()
        self.pump(lambda: self.editor.job is None)
        self.assertTrue(a.text)
        self.assertFalse(b.text)
        self.assertIn("미처리 1개", self.editor.status.text())
        self.editor.translate_missing()
        self.pump(lambda: self.editor.job is None)
        self.assertTrue(b.text)
        self.assertEqual(translator.calls.count(a.source_text), 1)
        self.assertEqual(translator.calls.count(b.source_text), 2)

    def test_undo_invalidates_running_job(self):
        self.regions()
        entered, release = threading.Event(), threading.Event()
        delivered = []
        def operation(cancel, progress):
            entered.set()
            release.wait(5)
            return "stale"
        self.editor.launch_job(operation, delivered.append)
        self.pump(entered.is_set)
        self.editor.undo()
        release.set()
        self.pump(lambda: self.editor.job is None)
        self.assertEqual(delivered, [])
        self.assertEqual(self.editor.project.pages[0].objects, [])

    def test_open_during_ocr_discards_old_result_and_reads_new_card(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def recognize(original, cancelled, progress, vertical):
            calls.append(original)
            if len(calls) == 1:
                entered.set()
                release.wait(5)
                return [Region("古いカード", [10, 10, 150, 30], 90, 20)]
            return [Region("新しいカード", [20, 20, 200, 30], 90, 20)]
        self.editor.auto_ocr = True
        with patch("studio.workflow.recognize", side_effect=recognize):
            self.editor.start_ocr()
            self.pump(entered.is_set)
            self.editor.load_path(self.source)
            release.set()
            self.pump(lambda: self.editor.job is None and not self.editor.pending_ocr)
        self.assertEqual(len(calls), 2)
        self.assertEqual([o.source_text for o in self.editor.project.pages[0].objects], ["新しいカード"])

    def test_corrupt_inactive_patch_cannot_replace_open_document(self):
        obj = self.regions()[0]
        data = self.editor.project.to_dict()
        target = data["pages"][0]["objects"][0]
        target.update(erase_patch="not-base64", erase_mask="not-base64", erase_rect=[0, 0, 30, 30], erase_enabled=False)
        before = deepcopy(self.editor.project)
        path = self.root / "손상.twproj"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("manifest.json", json.dumps(data))
            archive.writestr("assets/original.png", self.source_bytes)
        with self.assertRaises(ValueError):
            self.editor.load_path(path)
        self.assertEqual(self.editor.project, before)

    def test_v1_migration_preserves_editing_data(self):
        self.insert("이전 버전의 번역").finish_edit()
        data = self.editor.project.to_dict()
        data["version"] = 1
        data["pages"][0].pop("ocr_done")
        for obj in data["pages"][0]["objects"]:
            for key in ("confidence", "source_confirmed", "target_origin", "reviewed", "candidate_text", "candidate_source", "erase_enabled", "erase_patch", "erase_mask"):
                obj.pop(key)
        migrated = Project.from_dict(data)
        self.assertEqual(migrated.version, 9)
        self.assertEqual(migrated.pages[0].objects[0].text, "이전 버전의 번역")
        self.assertEqual(migrated.pages[0].objects[0].source_text, "")

    def test_erasure_preserves_alpha_outside_mask_and_rule_and_does_not_follow_box(self):
        source = Image.new("RGBA", (300, 140), (205, 225, 240, 137))
        draw = ImageDraw.Draw(source)
        draw.rectangle((30, 40, 43, 57), fill=(0, 0, 0, 137))
        draw.rectangle((70, 40, 83, 57), fill=(0, 0, 0, 137))
        draw.line((20, 60, 260, 60), fill=(0, 0, 0, 137))
        region = Region("試験", [20, 38, 240, 25], 90, 20,
                        glyphs=[[30, 40, 43, 57]], lines=[[20, 38, 260, 62]])
        patch_png, mask_png, rect = prepare_patch(source, region)
        obj = TextBox(paragraphs=[Paragraph([Run("번역")])], erase_patch=patch_png, erase_mask=mask_png, erase_rect=rect)
        stream = io.BytesIO()
        source.save(stream, "PNG")
        result = Image.open(io.BytesIO(restored_background(stream.getvalue(), [obj])))
        mask = Image.new("L", source.size)
        mask.paste(Image.open(io.BytesIO(base64.b64decode(mask_png))), tuple(rect[:2]))
        self.assertEqual(result.getchannel("A").tobytes(), source.getchannel("A").tobytes())
        for original, restored, selected in zip(source.getdata(), result.getdata(), mask.getdata()):
            if not selected:
                self.assertEqual(original, restored)
        self.assertGreater(result.getpixel((76, 48))[0], 180, "Unrecognized glyph was not removed")
        self.assertEqual(result.getpixel((70, 60)), source.getpixel((70, 60)))
        expected = result.tobytes()
        obj.x += 200
        obj.rotation = 37
        self.assertEqual(Image.open(io.BytesIO(restored_background(stream.getvalue(), [obj]))).tobytes(), expected)
        obj.erase_enabled = False
        self.assertEqual(Image.open(io.BytesIO(restored_background(stream.getvalue(), [obj]))).tobytes(), source.tobytes())

    def test_long_translation_is_rejected_without_silent_truncation(self):
        from studio.translation_config import MAX_SOURCE_TOKENS
        translator = LocalTranslator.__new__(LocalTranslator)
        class Tokenizer:
            def encode(self, text, out_type):
                return ["token"] * (MAX_SOURCE_TOKENS + 1)
        translator.tokenizer = Tokenizer()
        with self.assertRaises(ValueError):
            translator.translate("長い原文", threading.Event())
        cancelled = threading.Event()
        cancelled.set()
        self.assertEqual(translator.translate("原文", cancelled), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
