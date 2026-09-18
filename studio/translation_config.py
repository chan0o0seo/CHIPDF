"""Pinned model identity shared by preparation, packaging, and translation."""

MODEL_ID = "facebook/m2m100_1.2B"
MODEL_REVISION = "7b36184180524c1a1bbfa37f120a608046250b98"
MODEL_DIRECTORY = "m2m100-1.2b-int8"
MODEL_NAME = "M2M100 1.2B · 문단 번역"
MODEL_FILES = ("model.bin", "config.json", "shared_vocabulary.json", "sentencepiece.bpe.model")
MAX_SOURCE_TOKENS = 800
MAX_TARGET_TOKENS = 1000
