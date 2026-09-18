"""Prepare the pinned 1.2B translation model without running any inference."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / ".convert-deps"), str(ROOT / ".deps"), str(ROOT)]
import json
import os
import shutil
import uuid
from studio.translation_config import MODEL_DIRECTORY, MODEL_FILES, MODEL_ID, MODEL_REVISION

os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["HF_HOME"] = str(ROOT / "vendor" / "hf-cache")

def main():
    out = ROOT / "vendor" / MODEL_DIRECTORY
    origin = {"model": MODEL_ID, "revision": MODEL_REVISION, "quantization": "int8"}
    if out.exists():
        recorded = json.loads((out / "origin.json").read_text("utf-8"))
        if any(recorded.get(key) != value for key, value in origin.items()) or not all(
                (out / name).is_file() and (out / name).stat().st_size for name in MODEL_FILES):
            raise ValueError("Existing translation model is incomplete or has a different identity.")
        print("Pinned 1.2B translation model is already prepared. No inference was run.", flush=True)
        return
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
    print("Downloading " + MODEL_ID + " revision " + MODEL_REVISION, flush=True)
    source = snapshot_download(MODEL_ID, revision=MODEL_REVISION, token=False,
                               local_dir=ROOT / "vendor" / "m2m100-1.2b-source",
                               allow_patterns=["*.json", "pytorch_model.bin", "sentencepiece.bpe.model", "README.md", "LICENSE*"],
                               max_workers=2)
    staging = ROOT / ".build" / ("translation-model-" + uuid.uuid4().hex[:12])
    staging.parent.mkdir(parents=True, exist_ok=True)
    print("Converting weights to CPU int8 (no translation or benchmark)", flush=True)
    TransformersConverter(source, load_as_float16=True, low_cpu_mem_usage=True).convert(
        str(staging), quantization="int8")
    shutil.copy2(Path(source) / "sentencepiece.bpe.model", staging / "sentencepiece.bpe.model")
    shutil.copy2(Path(source) / "README.md", staging / "MODEL_CARD.md")
    shutil.copy2(ROOT / "vendor/notices/M2M100-MIT.txt", staging / "LICENSE.txt")
    (staging / "origin.json").write_text(json.dumps(origin, indent=2), "utf-8")
    if not all((staging / name).is_file() and (staging / name).stat().st_size for name in MODEL_FILES):
        raise ValueError("Model conversion did not produce all required files.")
    if not staging.resolve().is_relative_to((ROOT / ".build").resolve()) or out.resolve() != (ROOT / "vendor" / MODEL_DIRECTORY).resolve():
        raise ValueError("Model output is outside the expected project directories.")
    staging.rename(out)
    print("Prepared " + str(out) + ". No inference was run.", flush=True)

if __name__ == "__main__":
    main()
