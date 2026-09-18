"""Replaceable translation engines; reviewed memory and bounded session cache."""
from collections import OrderedDict
import re
from threading import Lock

from .chrome_translation import ChromeTranslator
from .translation_quality import MAX_TEXT, digest, memory_identity


def chrome_chunks(text):
    """Bound requests at sentence boundaries while preserving paragraph breaks."""
    for paragraph in re.split(r'\n[ \t]*\n+', text):
        if not paragraph.strip():
            continue
        if len(paragraph) <= 2400:
            yield [paragraph]
            continue
        sentences = re.split(r'(?<=[。！？!?])(?=[^」』”’）】〉》])|\n', paragraph)
        chunks, current = [], ""
        for sentence in sentences:
            if len(sentence) > 6000:
                raise ValueError("한 문장이 너무 깁니다. 원문 수정에서 문단을 나눠 주세요.")
            if current and len(current) + len(sentence) > 2400:
                chunks.append(current)
                current = ""
            current += sentence
        if current:
            chunks.append(current)
        yield chunks


class TranslationService:
    def __init__(self, data_dir=None):
        self.data_dir = data_dir
        self.chrome = None
        self.local = None
        self.cache = OrderedDict()
        self.lock = Lock()
        self.closed = False

    def chrome_engine(self):
        with self.lock:
            if self.closed:
                raise RuntimeError("번역 연결이 종료되었습니다.")
            if self.chrome is None:
                self.chrome = ChromeTranslator()
            return self.chrome

    def open_chrome(self):
        self.chrome_engine().open(force=True)

    def reset_local(self):
        self.local = None
        self.cache.clear()

    def translate(self, request, memory, cancelled, progress, fresh=False):
        if cancelled.is_set():
            return {"text": "", "engine": request["engine"]}
        if not request["input"].strip():
            raise ValueError("번역할 원문이 없습니다.")
        if len(request["source"]) > MAX_TEXT:
            raise ValueError("원문은 상자당 30,000자까지 번역할 수 있습니다. 문단을 나눠 주세요.")
        if not fresh:
            identity = memory_identity(request)
            for row in reversed(memory):
                if all(row[key] == value for key, value in identity.items()):
                    progress("같은 문맥에서 검토 완료한 번역을 재사용합니다…")
                    return {"text": row["target"], "engine": "memory"}
        key = digest({k: v for k, v in request.items() if k not in ("page", "object", "generation")})
        if not fresh and key in self.cache:
            self.cache.move_to_end(key)
            return {"text": self.cache[key], "engine": request["engine"], "cached": True}
        if request["engine"] == "local":
            if self.local is None:
                progress("오프라인 번역 모델 준비 중…")
                from .translation import LocalTranslator
                self.local = LocalTranslator(data_dir=self.data_dir)
            target = self.local.translate(request["input"], cancelled)
        elif request["engine"] == "chrome":
            engine = self.chrome_engine()
            paragraphs = []
            groups = list(chrome_chunks(request["input"]))
            for parts in groups:
                translated = []
                for part in parts:
                    if cancelled.is_set():
                        return {"text": "", "engine": "chrome"}
                    identity = {k: request[k] for k in ("project", "page", "object", "generation")}
                    identity["source_hash"] = digest(part)
                    translated.append(engine.translate(part, cancelled, progress, identity))
                paragraphs.append(" ".join(translated))
            target = "\n\n".join(paragraphs)
        else:
            raise ValueError("지원하지 않는 번역 엔진입니다.")
        if cancelled.is_set():
            return {"text": "", "engine": request["engine"]}
        if not target.strip() or len(target) > MAX_TEXT * 4:
            raise ValueError("번역문이 비어 있거나 너무 깁니다. 원문을 확인해 주세요.")
        self.cache[key] = target
        self.cache.move_to_end(key)
        # At most about four million characters per editor process.
        while len(self.cache) > 256 or sum(len(value) for value in self.cache.values()) > 4_000_000:
            self.cache.popitem(last=False)
        return {"text": target, "engine": request["engine"]}

    def close(self):
        with self.lock:
            self.closed = True
            chrome = self.chrome
        if chrome is not None:
            chrome.close()
