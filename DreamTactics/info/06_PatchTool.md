# 06. apply_patch 툴 문서

## 개요

`apply_patch/df_kr_patch_tool.py` - Dream Tactics 한글화 패치 도구 (오픈소스).

Google Sheets에서 번역 테이블을 가져와, 게임의 압축된 로케일 JSON을 압축 해제하여 텍스트를 한국어로 교체하고 재압축한다. 폰트도 동일 방식으로 교체한다.

---

## 파일 구성

```
apply_patch/
├── df_kr_patch_tool.py     # 메인 패치 도구
├── settings.json            # 설정 (구글 시트 ID, 대상 해시값 등)
├── Mulmaru.ttf              # 한글 폰트 (TTF)
└── data/                    # 게임의 data 폴더 (실행 시 이 위치에 게임 data 복사)
```

---

## settings.json 구조

```json
{
    "UPD_GID": "1OAo2zjdupl35wfB-iHLcXSVq8lsTcNxNhqdrLMg9N5s",  // 업데이트 스프레드시트 ID
    "UPD_SID": "1479116500",                                      // 업데이트 시트 GID

    "GSS_UI_SID": "1OAo2zjdupl35wfB-iHLcXSVq8lsTcNxNhqdrLMg9N5s", // UI 스프레드시트 ID
    "GSS_UI_GID": "1546620254",                                    // UI 시트 GID
    "GSS_UI_LOCALEID": "LocaleId",                                 // 컬럼명: LocaleId
    "GSS_UI_EN": "EN",                                             // 컬럼명: 영어
    "GSS_UI_JA": "JA",                                             // 컬럼명: 일본어
    "GSS_UI_CN": "CN",                                             // 컬럼명: 중국어
    "GSS_UI_KO": "KO",                                             // 컬럼명: 한국어
    "GSS_UI_SUB": "EN_gemini",                                     // 대체 컬럼 (예: AI 번역본)

    "GSS_TEXT_SID": "1OAo2zjdupl35wfB-iHLcXSVq8lsTcNxNhqdrLMg9N5s",// TEXT 스프레드시트 ID
    "GSS_TEXT_GID": "1541627842",                                  // TEXT 시트 GID
    "GSS_TEXT_HASH": "hash",                                       // 컬럼명: hash
    "GSS_TEXT_EN": "EN",
    "GSS_TEXT_JA": "JA",
    "GSS_TEXT_CN": "CN",
    "GSS_TEXT_KO": "KO",
    "GSS_TEXT_SUB": "EN_gemini",

    "GSS_EXC_SID": "1OAo2zjdupl35wfB-iHLcXSVq8lsTcNxNhqdrLMg9N5s", // 예외 테이블 스프레드시트 ID
    "GSS_EXC_GID": "2108749516",                                    // 예외 테이블 시트 GID

    "UI_EN":   "515357558",      // data/ 파일명 (English UI)
    "UI_JA":   "2946173491",     // data/ 파일명 (Japanese UI)
    "UI_CN":   "3584817163",     // data/ 파일명 (Chinese UI)
    "TEXT_EN": "4073104832",     // data/ 파일명 (English 본문)
    "TEXT_JA": "92749245",       // data/ 파일명 (Japanese 본문)
    "TEXT_CN": "2847597141",     // data/ 파일명 (Chinese 본문)

    "FONT_PIXEL_JA":  "1508373377",   // 픽셀 폰트 (JA 슬롯)
    "FONT_PIXEL_CN":  "2256482679",   // 픽셀 폰트 (CN 슬롯)
    "FONT_NORMAL_CN": "2973124184"    // 일반 폰트 (CN 슬롯)
}
```

---

## 동작 흐름

1. **설정 로드** (`settings.json`)
2. **Google Sheets CSV 다운로드**
   - UI 번역 테이블
   - TEXT 번역 테이블
   - EXC (예외/강제 덮어쓰기) 테이블
3. **UI 로케일 패치** (`patch_ui`)
   - `data/{UI_CN}`, `data/{UI_JA}` 각각에 대해
     - LZHAM 압축 해제 → JSON 파싱
     - `LocaleId`별로 스프레드시트 매칭 → `Text` 교체
     - JSON 재직렬화 → LZHAM 재압축 → 원본 덮어쓰기
4. **TEXT 본문 패치** (`patch_text`)
   - `data/{TEXT_CN}`, `data/{TEXT_JA}` 각각에 대해
     - LZHAM 압축 해제 → JSON 파싱
     - `hash`별로 스프레드시트 매칭 → `lines` 교체
     - JSON 재직렬화 → LZHAM 재압축 → 원본 덮어쓰기
5. **폰트 교체**
   - `Mulmaru.ttf` → LZHAM 압축 → `data/{FONT_NORMAL_CN}` 덮어쓰기
   - `data/{FONT_PIXEL_CN}` 복사 → `data/{FONT_PIXEL_JA}` 덮어쓰기 (동일 폰트)

---

## 텍스트 우선순위 (Fallback)

UI / TEXT 각각 아래 순서로 매칭:

1. **EXC** (Exception) 테이블의 해당 언어 컬럼 값이 비어있지 않으면 → 사용
2. **메인** 테이블의 **KO** 컬럼이 비어있지 않으면 → 사용
3. **메인** 테이블의 **SUB** 컬럼 (예: `EN_gemini`)이 비어있지 않으면 → 사용
4. **EN** 원본 데이터 → 사용
5. 그 외 → 원본 유지

### 근거 코드
```python
def get_patched_ui(locale_id, csv_ui_dict, csv_exc_dict, en_dict, lang):
    if locale_id in csv_exc_dict and csv_exc_dict[locale_id][lang].strip():
        return csv_exc_dict[locale_id][lang]
    if locale_id in csv_ui_dict:
        if csv_ui_dict[locale_id]["KO"].strip():
            return csv_ui_dict[locale_id]["KO"]
        if csv_ui_dict[locale_id]["SUB"].strip() and GSS_UI_SUB.strip():
            return csv_ui_dict[locale_id]["SUB"]
    if locale_id in en_dict:
        return en_dict[locale_id]
    return None
```

---

## Google Sheets CSV 다운로드 URL

```
https://docs.google.com/spreadsheets/d/{SID}/export?format=csv&gid={GID}
```

해당 스프레드시트는 공개 보기 권한이어야 한다.

---

## 폰트 교체 메커니즘

### 일반 폰트 (`FONT_NORMAL_CN`)
```python
def pack_font(font_path, output_path):
    with open(font_path, "rb") as f:
        font_data = f.read()
    payload = struct.pack("<I", len(font_data)) + font_data
    compressed = lzham.compress(payload, filters={"dict_size_log2": DICT_SIZE_LOG2})
    with open(output_path, "wb") as f:
        f.write(compressed)
```

### 픽셀 폰트 (`FONT_PIXEL_JA`, `FONT_PIXEL_CN`)
- CN 슬롯의 파일을 JA 슬롯으로 복사 (동일 폰트 사용)

### 형식
폰트 파일도 로케일 JSON과 동일 포맷:
```
LZHAM 압축 스트림
↓
[4바이트 size][TTF 원본 바이너리]
```

---

## 실행 방법

### 사전 준비
- Python 3.12 이상
- pip로 설치:
  ```
  pip install pylzham
  ```
- 게임의 `data/` 폴더를 `apply_patch/data/`에 복사
- `Mulmaru.ttf` 등 한글 폰트 파일 준비

### 실행
```
cd apply_patch
python df_kr_patch_tool.py
```

### 단일 실행 파일로 빌드 (Nuitka)
```
py -3.12 -m nuitka --standalone df_kr_patch_tool.py
```

---

## 한글화 적용 후 게임 실행

1. `apply_patch/data/` 에서 수정된 파일들을 게임의 `data/` 폴더로 복사 (또는 `-i` 옵션으로 in-place 실행)
2. 게임의 `options.json` (AppData Roaming)에서:
   ```json
   {
       "gameSettings": {
           "language": 2,           // 2=chinese (한글 덮어쓴 슬롯)
           "usePixelFont": true      // 픽셀 폰트 사용시
       }
   }
   ```
3. 게임 실행

---

## 주의 사항

### 원본 백업
패치 전에 아래 파일들을 반드시 백업:
- `data/515357558` (English UI)
- `data/2946173491` (Japanese UI)
- `data/3584817163` (Chinese UI)
- `data/4073104832` (English TEXT)
- `data/92749245` (Japanese TEXT)
- `data/2847597141` (Chinese TEXT)
- `data/1508373377` (Pixel Font JA)
- `data/2256482679` (Pixel Font CN)
- `data/2973124184` (Normal Font CN)

### 게임 업데이트 시
`data/0` 인덱스 파일이 변경되면 해시값이 달라질 수 있음 → `settings.json` 업데이트 필요.
