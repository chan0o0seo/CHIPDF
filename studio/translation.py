"""Offline draft translation. Only CTranslate2 and SentencePiece are required at runtime."""
from pathlib import Path
import re
import sys


class LocalTranslator:
    name = "M2M100 · 로컬 초안"

    def __init__(self, root=None):
        import ctranslate2
        import sentencepiece
        root = Path(root) if root else Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "vendor" / "m2m100-int8"
        required = ("model.bin", "config.json", "shared_vocabulary.json", "sentencepiece.bpe.model")
        if not all((root / name).is_file() for name in required):
            raise ValueError("로컬 번역 모델이 없습니다. 모델이 포함된 배포본을 사용해 주세요.")
        self.tokenizer = sentencepiece.SentencePieceProcessor(model_proto=(root / "sentencepiece.bpe.model").read_bytes())
        files = {name: (root / name).read_bytes() for name in required[:3]}
        self.engine = ctranslate2.Translator("m2m100", files=files, device="cpu", compute_type="int8", intra_threads=4)

    def translate(self, text, cancelled):
        # Translate sentences independently; reject overlong input instead of truncating it.
        sentences = [s.strip() for s in re.split(r"(?<=[。！？!?])\s*|\n+", text) if s.strip()]
        targets = []
        for sentence in sentences:
            if cancelled.is_set():
                return ""
            tokens = self.tokenizer.encode(sentence, out_type=str)
            if len(tokens) > 440:
                raise ValueError("원문이 너무 깁니다. 문장을 나눠 다시 번역해 주세요.")
            output = self.engine.translate_batch([["__ja__"] + tokens + ["</s>"]], target_prefix=[["__ko__"]],
                                                 beam_size=4, max_decoding_length=440, max_input_length=0)[0]
            tokens = [t for t in output.hypotheses[0] if t not in ("__ko__", "<s>", "</s>", "<pad>")]
            if len(tokens) >= 439 or not tokens:
                raise ValueError("번역 초안을 끝까지 만들지 못했습니다. 원문을 나눠 주세요.")
            targets.append(self.tokenizer.decode(tokens))
        return " ".join(targets)
