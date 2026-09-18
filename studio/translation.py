"""Offline paragraph translation using an optional M2M100 1.2B pack."""
from pathlib import Path
import json
import re
import sys

from .translation_config import (MAX_SOURCE_TOKENS, MAX_TARGET_TOKENS, MODEL_DIRECTORY,
                                 MODEL_FILES, MODEL_ID, MODEL_NAME, MODEL_REVISION)


class LocalTranslator:
    name = MODEL_NAME

    def __init__(self, root=None, data_dir=None):
        from .model_packs import selected_root, origin_for
        root = Path(root) if root else selected_root(data_dir)
        origin_for(root)
        import ctranslate2
        import sentencepiece
        if not all((root / name).is_file() for name in (*MODEL_FILES, "origin.json")):
            raise ValueError("오프라인 모델 파일이 없습니다. 오프라인 팩을 설치하거나 기존 모델 폴더를 연결해 주세요.")
        origin = json.loads((root / "origin.json").read_text("utf-8"))
        if (origin.get("model"), origin.get("revision"), origin.get("quantization")) != (MODEL_ID, MODEL_REVISION, "int8"):
            raise ValueError("번역 모델 버전이 맞지 않습니다. 호환되는 오프라인 팩을 설치해 주세요.")
        self.tokenizer = sentencepiece.SentencePieceProcessor(model_proto=(root / "sentencepiece.bpe.model").read_bytes())
        # Supplying bytes keeps Korean/Japanese installation paths supported.
        files = {name: (root / name).read_bytes() for name in MODEL_FILES[:3]}
        self.engine = ctranslate2.Translator("m2m100", files=files, device="cpu", compute_type="int8", intra_threads=4)

    def _chunks(self, paragraph, cancelled):
        if cancelled.is_set():
            return
        if len(self.tokenizer.encode(paragraph, out_type=str)) <= MAX_SOURCE_TOKENS:
            yield paragraph
            return
        # Keep closing quotation marks with their sentence; only long paragraphs
        # are divided, and complete adjacent sentences share one model input.
        parts = re.split(r"([。！？!?]+[」』”’）】〉》]*)", paragraph)
        current = ""
        for index in range(0, len(parts), 2):
            if cancelled.is_set():
                return
            sentence = (parts[index] + (parts[index + 1] if index + 1 < len(parts) else "")).strip()
            if not sentence:
                continue
            if len(self.tokenizer.encode(sentence, out_type=str)) > MAX_SOURCE_TOKENS:
                raise ValueError("한 문장이 너무 깁니다. 원문 수정에서 문장을 나눠 주세요.")
            combined = current + sentence
            if current and len(self.tokenizer.encode(combined, out_type=str)) > MAX_SOURCE_TOKENS:
                yield current
                current = sentence
            else:
                current = combined
        if current and not cancelled.is_set():
            yield current

    def translate(self, text, cancelled):
        text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        paragraphs = [part.strip() for part in re.split(r"\n[ \t]*\n+", text) if part.strip()]
        translated = []
        for paragraph in paragraphs:
            targets = []
            for chunk in self._chunks(paragraph, cancelled):
                if cancelled.is_set():
                    return ""
                tokens = self.tokenizer.encode(chunk, out_type=str)
                output = self.engine.translate_batch(
                    [["__ja__"] + tokens + ["</s>"]], target_prefix=[["__ko__"]],
                    beam_size=6, max_decoding_length=MAX_TARGET_TOKENS, max_input_length=0,
                )[0]
                if cancelled.is_set():
                    return ""
                hypothesis = output.hypotheses[0]
                tokens = [token for token in hypothesis if token not in ("__ko__", "<s>", "</s>", "<pad>")]
                if len(hypothesis) >= MAX_TARGET_TOKENS - 1 or not tokens:
                    raise ValueError("번역문을 끝까지 만들지 못했습니다. 원문을 짧은 문단으로 나눠 주세요.")
                target = self.tokenizer.decode(tokens).strip()
                if not target:
                    raise ValueError("번역문을 만들지 못했습니다. 원문을 확인해 주세요.")
                targets.append(target)
            translated.append(" ".join(targets))
        return "" if cancelled.is_set() else "\n\n".join(translated)
