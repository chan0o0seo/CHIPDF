"""Download official M2M100 weights, convert to int8, and run the same 20 samples."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / ".convert-deps"), str(ROOT / ".deps")]
import json
import os
import shutil
import time
import urllib.request

os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["HF_HOME"] = str(ROOT / "vendor" / "hf-cache")

def main():
    from huggingface_hub import snapshot_download
    from ctranslate2.converters import TransformersConverter
    import sentencepiece
    # The Windows SentencePiece wheel cannot open non-ASCII paths directly.
    original_loader = sentencepiece.SentencePieceProcessor.LoadFromFile
    def load(self, filename):
        if not str(filename).isascii():
            return self.LoadFromSerializedProto(Path(filename).read_bytes())
        return original_loader(self, filename)
    sentencepiece.SentencePieceProcessor.LoadFromFile = load
    out = ROOT / "vendor" / "m2m100-int8"
    if not (out / "model.bin").exists():
        model = "facebook/m2m100_418M"
        revision = "55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636"
        print("Downloading official M2M100 revision " + revision, flush=True)
        source = snapshot_download(model, revision=revision, local_dir=ROOT / "vendor" / "m2m100-source",
                                   allow_patterns=["*.json", "pytorch_model.bin", "sentencepiece.bpe.model", "README.md", "LICENSE*"])
        print("Converting to CPU int8", flush=True)
        TransformersConverter(source).convert(str(out), quantization="int8", force=True)
        shutil.copy2(Path(source) / "sentencepiece.bpe.model", out / "sentencepiece.bpe.model")
        (out / "origin.json").write_text(json.dumps({"model": model, "revision": revision, "quantization": "int8"}), "utf-8")
    import ctranslate2
    tokenizer = sentencepiece.SentencePieceProcessor(model_proto=(out / "sentencepiece.bpe.model").read_bytes())
    files = {p.name: p.read_bytes() for p in out.iterdir() if p.name in ("model.bin", "config.json", "shared_vocabulary.json")}
    start = time.perf_counter()
    translator = ctranslate2.Translator("m2m100", files=files, device="cpu", compute_type="int8", intra_threads=4)
    load_seconds = time.perf_counter() - start
    rows = []
    from engine_probe import SAMPLES
    (ROOT / "qa").mkdir(exist_ok=True)
    for sentence in SAMPLES:
        start = time.perf_counter()
        source = ["__ja__"] + tokenizer.encode(sentence, out_type=str) + ["</s>"]
        result = translator.translate_batch([source], target_prefix=[["__ko__"]], beam_size=4, max_decoding_length=384)[0]
        target = tokenizer.decode([t for t in result.hypotheses[0] if t not in ("__ko__", "</s>", "<s>", "<pad>")])
        result_row = {"source": sentence, "target": target, "seconds": round(time.perf_counter() - start, 3)}
        rows.append(result_row)
        print(json.dumps(result_row, ensure_ascii=True), flush=True)
    (ROOT / "qa" / "m2m-benchmark.json").write_text(json.dumps({"load_seconds": load_seconds, "rows": rows}, ensure_ascii=False, indent=2), "utf-8")

if __name__ == "__main__":
    main()
