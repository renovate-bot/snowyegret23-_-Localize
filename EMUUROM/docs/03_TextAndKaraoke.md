# 03. 텍스트 / 엔딩 가사 처리

## CSV 구조

`extract`는 Lua code에서 번역 대상 문자열을 찾아 `text.csv`로 내보낸다.

| 컬럼 | 의미 |
|------|------|
| `id` | 추출 순서 기반 ID (`t00001` 형식) |
| `module` | 문자열이 속한 Lua module |
| `line` | `code.lua` 기준 줄 번호 |
| `start` | `code.lua` 내 문자열 시작 오프셋 |
| `end` | `code.lua` 내 문자열 끝 오프셋 |
| `quote` | Lua 문자열 quote 종류 (`'`, `"`, `[[`) |
| `raw_sha256` | 원본 문자열 구간 hash |
| `src` | 원문 |
| `dst` | 번역문 |

CSV는 `csv.QUOTE_ALL`로 저장된다. import 시에는 `utf-8-sig`로 읽기 때문에 BOM이 있어도 처리 가능하다.

---

## 번역 대상 module

현재 도구의 번역 대상 module은 다음 세 곳이다.

| module | 용도 |
|--------|------|
| `data/dialogue_en` | 일반 대사/텍스트 |
| `scenes/end-grey` | 엔딩 grey 계열 텍스트 |
| `scenes/end-yellow` | 엔딩 yellow 계열 텍스트 |

`emuurom_tool.py`의 `TEXT_MODULES` 상수로 관리된다.

---

## import 안전장치

`apply-text`와 `import`는 `text.csv`의 `start`, `end`, `raw_sha256`를 사용해 원본 문자열 구간을 검증한다.

처리 순서:

1. `code.lua`를 읽는다.
2. CSV row의 `start:end` 구간을 다시 읽는다.
3. 해당 구간의 SHA-256이 `raw_sha256`과 같은지 확인한다.
4. 같으면 `dst`를 Lua 문자열로 quote 처리해 치환한다.
5. 다르면 `source mismatch`로 중단한다.

이 구조 때문에 CSV가 다른 추출본과 섞이면 자동으로 실패한다.

---

## 엔딩 가사 박자 표기

원본 엔딩 가사는 음악 박자에 맞춰 단어 단위로 흰색 highlight가 켜지는 구조이다.

원본 런타임은 다음 방식으로 박자를 계산한다.

```lua
E.txtLineStrs = TXT.songs[E.song].song:split("\n")
for i,l in ipairs(E.txtLineStrs) do
    E.txtLines[i] = l:split(" ")
end
```

즉 실제 박자 단위는 runtime 문자열의 공백 분리 결과이다.

---

## CSV의 `|` 규칙

CSV의 `src`와 `dst`에서는 번역자가 박자 경계를 직접 볼 수 있도록 `|`를 사용한다.

| CSV 표기 | runtime 변환 | 의미 |
|----------|--------------|------|
| `A|B` | `A_ B` | 박자는 나누지만 화면에는 붙여 보임 |
| `A| B` | `A B` | 박자도 나누고 화면에도 공백 표시 |
| `A |B` | `A B` | 이전 토큰 뒤의 visible space를 유지 |
| 빈 박자 | `¤` | 박자 슬롯만 소비하고 글자는 그리지 않음 |

`_ `는 원본 코드에서 사용하던 결합 박자 표기이다. `getLine`은 전체 회색 가사를 그릴 때 `:gsub("_ ","")`로 `_ `를 제거하므로 화면에는 붙어 보인다.

---

## 박자 수 검증

import 시 각 가사 줄은 원문과 같은 박자 수를 가져야 한다.

검증 기준:

```text
원문 src의 | 개수 기준 박자 수 == 번역 dst의 | 개수 기준 박자 수
```

맞지 않으면 다음 오류로 중단한다.

```text
karaoke beat count mismatch at <row_id> line <line_no>
```

이 규칙은 원본의 음악 타이밍 배열을 바꾸지 않고 번역문만 맞추기 위한 것이다.

---

## 번역 작성 원칙

박자 표기는 다음 우선순위로 잡는다.

1. 자연스러운 띄어쓰기 단위로 먼저 나눈다.
2. 원문 박자 수가 더 많으면 의미가 덜 깨지는 위치를 추가로 쪼갠다.
3. 붙여 읽는 편이 자연스러운 경우 `A|B`처럼 visible space 없는 박자를 사용한다.
4. 원문보다 박자 수가 부족하면 불필요한 공백이 아니라 문장 구조를 조정한다.

예시:

```text
강물이| 우리의| 말을| 전하게하라!
```

위 표기는 4박자이고 화면에는 다음처럼 보인다.

```text
강물이 우리의 말을 전하게하라!
```

---

## 줄바꿈 패치

원본 `newlines(s,w_pix,linecount)`는 한글 폭을 고려하지 못한다. `patch-unicode`는 이 함수를 교체한다.

교체된 함수는 다음을 처리한다.

| 처리 | 설명 |
|------|------|
| UTF-8 문자 단위 순회 | byte 길이로 한글이 잘리지 않게 함 |
| 한글 문자 폭 | `krwidth` 또는 기본 8픽셀 기준 |
| `{...}` special token | 버튼/스프라이트/숫자 토큰을 폭 계산에 반영 |
| `[s]` 제어 코드 | 작은 글자 모드 유지 |
| 단어 초과 | 한 줄 폭보다 긴 단어는 문자 단위로 분리 |

