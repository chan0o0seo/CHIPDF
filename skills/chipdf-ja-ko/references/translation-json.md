# 번역 JSON

UTF-8 JSON을 사용한다. `sources.json`은 문맥과 이미지 경로를 포함하는 참고 자료다. `translations.json`은 적용용이며 다음 형식이다.

```json
{
  "schema": "chipdf-ja-ko/1",
  "project_id": "prepare가 만든 프로젝트 식별자",
  "entries": [
    {
      "id": "원문 상자 식별자",
      "source_sha256": "sources.json의 원문 SHA256",
      "target": "자연스러운 한국어 번역문\n다음 문단",
      "layout": {
        "rect": [100, 200, 400, 180],
        "font_size": 18,
        "font_family": "맑은 고딕",
        "align": "left",
        "writing_mode": "horizontal"
      }
    }
  ]
}
```

`layout`은 생략 가능하다. `rect`는 페이지 PNG 기준 픽셀 좌표 `[x, y, width, height]`이며 너비·높이는 각각 24 이상이어야 한다. 이는 번역 상자의 좌표이며 원문 지우기 영역은 바뀌지 않는다. `align`은 `left`, `center`, `right`, `writing_mode`는 `horizontal`, `vertical-rl`이다. 글꼴은 해당 PC에 설치된 한국어 지원 글꼴을 사용한다. 자동 맞춤을 끄고 지정한 글자 크기를 유지하려면 apply에 `--no-fit`을 사용한다.

`align: "center"`는 상자 내부의 가로 정렬이다. 디자인 영역의 중앙이나 세로 중앙을 자동으로 맞추지는 않는다. `font_size`가 원문과 같아도 실제 글자 높이는 다를 수 있다. [layout-matching.md](layout-matching.md)에 따라 미리보기에서 크기·상자 위치·실제 획 중심을 보정한다. `vertical_align`, `offset_x`, `offset_y`, `tracking` 등 지원하지 않는 필드를 추가하지 말고 지원되는 `rect`·크기·정렬 또는 편집기를 사용한다.

적용할 항목만 `entries`에 넣는다. 빈 target은 거절된다. 중복/존재하지 않는 ID, 다른 프로젝트, 바뀐 원문 해시도 거절된다. 부분 적용 후에는 출력 `.twproj`를 다음 apply 입력으로 사용한다. 원문을 고치지 않았다면 기존 ID와 해시는 유지된다. 수정할 항목은 다음 JSON에 다시 넣을 수 있다.

OCR 오독을 이미지로 확인한 경우 항목에 `corrected_source`를 추가할 수 있다. `source_sha256`는 수정 전 원문의 해시를 유지한다. 적용 후 원문 출처는 manual, 원문 확인 상태는 true가 된다. 수정 요청은 `.translations.json` 동반 파일에 남고 이전 OCR 문자열은 원본 작업과 원본 `sources.json`에 보관된다. 이후 수정은 출력 `.sources/sources.json`의 새 해시를 사용한다. `reviewed`는 자동으로 true가 되지 않는다.

`report.json`의 `blocking_count`는 자동 검출된 출력 문제 수다. 번역체·고유명사·누락·겹침의 완전한 검사는 제공하지 않는다. `translation_check`와 `low_confidence`는 원문 대조 안내이며 자동 출력을 막지는 않는다.
