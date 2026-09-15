"""Standalone local-engine experiment. No document is sent to a remote service.

Downloads only public model artifacts when explicitly invoked with --download.
This experiment is separate from the editor's portable distribution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / ".engine-deps"))
MODELS = ROOT / "vendor" / "models"
PACKAGES = {
    "ja_en": "https://data.argosopentech.com/argospm/v1/translate-ja_en-1_1.argosmodel",
    "en_ko": "https://data.argosopentech.com/argospm/v1/translate-en_ko-1_1.argosmodel",
}
SAMPLES = [
    "あなたは昨夜、図書室で女王と話した。", "この情報を他の参加者に見せてはいけません。",
    "犯人はまだこの屋敷の中にいる。", "午後八時から九時まで、あなたはどこにいましたか。",
    "机の引き出しには古い鍵が一本入っていた。", "彼女が嘘をついているとは限らない。",
    "レジナはシュウに手紙を渡した。", "このカードは議論が終わるまで公開しないでください。",
    "あなたの目的は、妹の秘密を守ることだ。", "証拠がないからといって、彼が無実だとは言えない。",
    "私は誰も殺していない。信じてくれ。", "扉は内側から鍵がかかっていた。",
    "一度だけ、他の人物の持ち物を調べることができます。", "投票は全員が同時に行います。",
    "残り時間は十五分です。", "彼に会ったのは、鐘が鳴る少し前だった。",
    "あなたが探している指輪は、ここにはない。", "この能力を使った場合、カードを裏返してください。",
    "廊下には足跡があった。しかし、窓の外には雪が積もっていなかった。",
    "女王は静かに目を閉じた。誰も、その言葉の本当の意味を知らなかった。",
]


def download():
    MODELS.mkdir(parents=True, exist_ok=True)
    records = []
    for pair, url in PACKAGES.items():
        target = MODELS / pair
        package = MODELS / (pair + ".argosmodel")
        if not package.exists():
            temporary = package.with_suffix(".download")
            print(f"Downloading {pair}", flush=True)
            urllib.request.urlretrieve(url, temporary)
            temporary.replace(package)
        with zipfile.ZipFile(package) as archive:
            if sum(info.file_size for info in archive.infolist()) > 800_000_000:
                raise ValueError("Model package exceeds size budget")
            for info in archive.infolist():
                parts = PurePosixPath(info.filename).parts
                if info.is_dir() or len(parts) < 2:
                    continue
                relative = PurePosixPath(*parts[1:])
                if relative.is_absolute() or ".." in relative.parts or ":" in str(relative) or "\\" in str(relative):
                    raise ValueError("Unsafe model archive path")
                dest = target.joinpath(*relative.parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    dest.write_bytes(archive.read(info))
        records.append({"pair": pair, "url": url, "bytes": package.stat().st_size,
                        "sha256": hashlib.sha256(package.read_bytes()).hexdigest()})
    (MODELS / "downloads.json").write_text(json.dumps(records, indent=2), "utf-8")
    print(json.dumps(records, indent=2), flush=True)


class LocalPivotTranslator:
    """Adapter candidate: Japanese -> English -> Korean on CPU, int8."""
    def __init__(self):
        import ctranslate2
        import sentencepiece
        self.stages = []
        for pair in ("ja_en", "en_ko"):
            root = MODELS / pair
            tokenizer = sentencepiece.SentencePieceProcessor(model_proto=(root / "sentencepiece.model").read_bytes())
            files = {p.name: p.read_bytes() for p in (root / "model").iterdir() if p.is_file()}
            model = ctranslate2.Translator(pair, files=files, device="cpu", compute_type="int8", intra_threads=4)
            self.stages.append((tokenizer, model))

    def translate(self, text):
        for tokenizer, model in self.stages:
            tokens = tokenizer.encode(text, out_type=str)
            output = model.translate_batch([tokens], beam_size=4, max_decoding_length=384)[0]
            text = tokenizer.decode(output.hypotheses[0])
        return text


def benchmark():
    started = time.perf_counter()
    translator = LocalPivotTranslator()
    load_seconds = time.perf_counter() - started
    rows = []
    for source in SAMPLES:
        tick = time.perf_counter()
        target = translator.translate(source)
        row = {"source": source, "target": target, "seconds": round(time.perf_counter() - tick, 3)}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=True), flush=True)
    result = {"engine": "CTranslate2 int8 / Argos 1.1 ja-en + en-ko", "load_seconds": round(load_seconds, 3),
              "samples": "synthetic murder-mystery sentences; not user document text", "rows": rows}
    output = ROOT / "qa" / "engine-benchmark.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    if args.download:
        download()
    if args.benchmark:
        benchmark()
