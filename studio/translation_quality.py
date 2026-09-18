"""Conservative input preparation and project-scoped translation memory."""
from copy import deepcopy
import difflib
import hashlib
import json
import re
import unicodedata

PIPELINE_VERSION = 1
ENGINES = {"chrome": "Chrome 내장 번역", "local": "M2M100 · 오프라인"}
MAX_TEXT = 30000


def normalized(text):
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def prepare_source(text, join_lines=True):
    """Join soft wraps within a box, never separate boxes, lists or dialogues."""
    text = normalized(text)
    if not join_lines:
        return text
    lines = text.split("\n")
    output = []
    boundary = re.compile(r'^[\s]*(?:[「『【・●○■◆◇▶※]|\d+[.．、)）])')
    for line in lines:
        table_spacing = bool(re.search(r'\t| {2,}|[|｜]', line.strip()))
        line = line.strip()
        if not line:
            output.append("")
            continue
        previous = output[-1] if output else ""
        if (previous and not re.search(r'[。！？!?」』】]$', previous)
                and not boundary.match(previous) and not boundary.match(line)
                and not table_spacing and "\t" not in previous + line and not re.search(r' {2,}|[|｜]', previous + line)):
            separator = " " if re.search(r'[A-Za-z0-9]$', previous) and re.match(r'[A-Za-z0-9]', line) else ""
            output[-1] += separator + line
        else:
            output.append(line)
    return "\n".join(output).strip()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def project_policy(project):
    return digest([project.translation_engine, project.glossary, project.translation_memory])


def request_for(project, page, obj):
    # Page reading order follows geometry, not stacking order. Explicit context
    # overrides the conservative adjacent-text context, allowing intentional reuse.
    boxes = [o for o in page.objects if hasattr(o, "source_text") and o.source_text.strip()]
    vertical = obj.writing_mode == "vertical-rl"
    boxes.sort(key=lambda o: (-o.x, o.y) if vertical else (o.y, o.x))
    position = next((i for i, o in enumerate(boxes) if o.id == obj.id), -1)
    before = boxes[position - 1].source_text if position > 0 else ""
    after = boxes[position + 1].source_text if 0 <= position < len(boxes) - 1 else ""
    context = obj.translation_context.strip() or digest([normalized(before), normalized(after)])
    return {"project": project.id, "page": page.id, "object": obj.id,
            "source": obj.source_text, "source_hash": digest(obj.source_text),
            "input": prepare_source(obj.source_text, obj.join_source_lines),
            "source_language": "ja", "target_language": "ko",
            "scope": page.source_file or page.id, "speaker": obj.speaker.strip(),
            "context": context, "engine": project.translation_engine,
            "join_lines": obj.join_source_lines, "pipeline": PIPELINE_VERSION,
            "glossary": deepcopy(project.glossary)}


def memory_identity(request):
    return {"source": normalized(request["source"]), "scope": request["scope"],
            "speaker": request["speaker"], "context": request["context"]}


def remember(project, request, target):
    identity = memory_identity(request)
    project.translation_memory = [row for row in project.translation_memory
                                  if any(row.get(key) != value for key, value in identity.items())]
    project.translation_memory.append({**identity, "target": target})
    project.translation_memory = project.translation_memory[-2000:]


def memory_suggestions(request, memory):
    identity = memory_identity(request)
    if not identity["source"]:
        return []
    results = []
    for row in memory:
        source = row["source"]
        if abs(len(source) - len(identity["source"])) > max(len(source), len(identity["source"])) * .5:
            continue
        exact = source == identity["source"]
        score = 1.0 if exact else difflib.SequenceMatcher(None, identity["source"], source, autojunk=False).ratio()
        if score < .65:
            continue
        same_context = all(row[key] == identity[key] for key in ("scope", "speaker", "context"))
        results.append({**row, "score": score, "exact": exact, "same_context": same_context})
    return sorted(results, key=lambda r: (r["exact"], r["same_context"], r["score"]), reverse=True)[:8]


def quality_issues(source, target, glossary):
    if not target.strip():
        return ["번역문이 비어 있습니다."]
    issues = []
    for term in glossary:
        if term["source"] not in source:
            continue
        if term["target"] not in target:
            issues.append(f"용어 확인: {term['source']} → {term['target']}")
        for forbidden in term.get("forbidden", []):
            if forbidden in target:
                issues.append(f"피할 표기: {forbidden} → {term['target']}")
    numbers = lambda s: set(re.findall(r'\d+(?:[.:：]\d+)*', unicodedata.normalize("NFKC", s)))
    missing = numbers(source) - numbers(target)
    if missing:
        issues.append("숫자·시간 대조: " + ", ".join(sorted(missing)))
    if re.search(r'[ぁ-ゖァ-ヺ]', target):
        issues.append("번역문에 일본어가 남아 있습니다. 인명 또는 미번역인지 확인하세요.")
    if len(target) > max(120, len(source) * 4) or re.search(r'(.{3,30})\1{3,}', target):
        issues.append("번역문 길이 또는 반복 표현을 확인하세요.")
    if re.search(r'ない|なかった|ません|とは限ら|かもしれ|はず|おそらく', source):
        issues.append("부정·추측 표현은 원문과 대조해 주세요.")
    return list(dict.fromkeys(issues))[:10]


def validate_translation_data(engine, glossary, memory):
    if engine not in ENGINES:
        raise ValueError("지원하지 않는 번역 엔진입니다.")
    if not isinstance(glossary, list) or len(glossary) > 500:
        raise ValueError("용어집은 500개까지 저장할 수 있습니다.")
    seen = set()
    for row in glossary:
        if not isinstance(row, dict) or set(row) != {"source", "target", "forbidden"}:
            raise ValueError("용어집 구성이 올바르지 않습니다.")
        for key in ("source", "target"):
            if not isinstance(row[key], str) or not row[key].strip() or len(row[key]) > 200:
                raise ValueError("용어와 번역 표기는 1~200자로 입력하세요.")
        if row["source"] in seen:
            raise ValueError("같은 원문 용어가 중복되어 있습니다.")
        seen.add(row["source"])
        forbidden = row["forbidden"]
        if not isinstance(forbidden, list) or len(forbidden) > 20 or any(
                not isinstance(word, str) or not word.strip() or len(word) > 200 for word in forbidden):
            raise ValueError("피할 표기는 각 200자, 20개까지 입력하세요.")
    if not isinstance(memory, list) or len(memory) > 2000:
        raise ValueError("확정 번역은 2,000개까지 저장할 수 있습니다.")
    for row in memory:
        if not isinstance(row, dict) or set(row) != {"source", "target", "scope", "speaker", "context"}:
            raise ValueError("확정 번역 구성이 올바르지 않습니다.")
        if any(not isinstance(value, str) or len(value) > MAX_TEXT * 4 for value in row.values()):
            raise ValueError("확정 번역 내용이 너무 길거나 올바르지 않습니다.")
        if not row["source"].strip() or not row["target"].strip():
            raise ValueError("확정 번역의 원문과 번역문이 필요합니다.")
