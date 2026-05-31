# 06. emuurom_tool.py 사용법

## 기본 원칙

현재 툴은 게임 루트 폴더에서 실행하는 것을 기준으로 한다.

```powershell
cd "C:\Program Files (x86)\Steam\steamapps\common\EMUUROM"
```

기본 파일명:

| 항목 | 기본값 |
|------|--------|
| 원본 exe | `emuurom_backup.exe` |
| 추출 폴더 | `extract` |
| 번역 CSV | `text.csv` |
| 한글 폰트 | `Galmuri7.ttf` |
| 출력 exe | `emuurom.exe` |
| 출력 cart | `extract/emuurom_patched.cart.bin` |

---

## 1. 정보 확인

```powershell
python emuurom_tool.py info emuurom_backup.exe
```

출력 내용:

| 필드 | 의미 |
|------|------|
| `overlay_offset` | `TIC.CART` overlay 시작 위치 |
| `app_size` | exe 본문 크기 |
| `cart_size` | zlib 압축 cart 크기 |
| `uncompressed_cart_size` | 압축 해제 cart 크기 |
| `code_size` | Lua code 크기 |
| `full_code_size` | code chunk bank 크기 |
| `chunk_count` | cart chunk 수 |
| `code_chunks` | code chunk bank/size 정보 |

---

## 2. 추출

기본 실행:

```powershell
python emuurom_tool.py extract
```

동일한 명시형:

```powershell
python emuurom_tool.py extract --original-exe emuurom_backup.exe --extract-dir extract --text-csv text.csv
```

생성물:

```text
extract/
├── emuurom.cart.bin
├── code.lua
├── manifest.json
└── images/

text.csv
```

`text.csv`는 게임 루트에 생성된다. 사용자는 이 파일의 `dst` 컬럼을 번역한다.

---

## 3. 텍스트만 Lua에 적용

```powershell
python emuurom_tool.py apply-text
```

생성물:

```text
extract/code_patched.lua
```

이 단계는 아직 한글 glyph block을 삽입하지 않는다.

---

## 4. 한글 폰트 패치

```powershell
python emuurom_tool.py patch-unicode
```

명시형:

```powershell
python emuurom_tool.py patch-unicode extract Galmuri7.ttf --source-size 8 --draw-size 8 --threshold 80
```

생성물:

```text
extract/code_unicode.lua
```

이 단계에서 적용되는 것:

| 패치 | 내용 |
|------|------|
| glyph block | `Galmuri7.ttf`에서 필요한 문자만 추출 |
| `utf8printf` | 한글 glyph 분기 추가 |
| `newlines` | 한글 폭 기준 줄바꿈 |
| `endred2` karaoke | 한글 폭 기준 정렬/진행 폭 계산 |
| PC cursor | 터미널 커서 위치 보정 |

---

## 5. exe 빌드

```powershell
python emuurom_tool.py build
```

명시형:

```powershell
python emuurom_tool.py build --original-exe emuurom_backup.exe --extract-dir extract --output-exe emuurom.exe --cart extract\emuurom_patched.cart.bin --import-images
```

build는 다음 우선순위로 Lua 코드를 선택한다.

1. `extract/code_unicode.lua`
2. `extract/code_patched.lua`
3. `extract/code.lua`

그 뒤 cart를 재구성하고 zlib level 9로 압축해 `TIC.CART` overlay에 다시 붙인다.

---

## 6. 전체 import

가장 많이 쓰는 명령:

```powershell
python emuurom_tool.py import
```

동작 순서:

1. `apply-text`
2. `patch-unicode`
3. `build`

기본적으로 이미지 변경분도 import한다. 이미지 import를 끄려면:

```powershell
python emuurom_tool.py import --no-import-images
```

빌드 없이 중간 Lua만 만들려면:

```powershell
python emuurom_tool.py import --no-build
```

---

## 7. test mode

엔딩/보스 테스트용:

```powershell
python emuurom_tool.py import --test-mode
```

적용 내용:

| 위치 | 변경 |
|------|------|
| final boss update | 보스 phase를 빠르게 끝 상태로 보냄 |
| title load branch | Continue/load 시 `endred2`로 바로 진입 |

현재 test mode의 엔딩 진입 대상은 `endred2`이다.

일반 배포용으로 되돌릴 때는 `--test-mode` 없이 다시 빌드한다.

```powershell
python emuurom_tool.py import
```

---

## 8. .patchc / .patchd 섹션 추가

선택 기능:

```powershell
python emuurom_tool.py add-sections emuurom.exe emuurom_sections.exe
```

기본 섹션 크기:

| 섹션 | 기본 크기 |
|------|-----------|
| `.patchc` | `0x4000` |
| `.patchd` | `0x4000` |

현재 일반 한글화 흐름에는 필수 단계가 아니다.

---

## 오류 대응

### `valid TIC.CART overlay was not found`

입력 exe가 EMUUROM TIC cart overlay를 가진 파일이 아니거나, overlay가 손상된 경우이다.

확인:

```powershell
python emuurom_tool.py info emuurom_backup.exe
```

### `source mismatch`

`text.csv`가 현재 `extract/code.lua`와 맞지 않는다.

해결:

1. 기존 `extract`와 오래된 `text.csv`를 치운다.
2. `python emuurom_tool.py extract`로 새로 추출한다.
3. 이전 번역을 새 CSV에 구조적으로 옮긴다.

### `karaoke beat count mismatch`

엔딩 가사 번역문의 박자 수가 원문과 다르다.

해결:

- `src`의 `|` 개수와 `dst`의 `|` 개수를 줄별로 맞춘다.
- 화면에 띄울 공백이 필요하면 `| ` 또는 ` |`를 사용한다.
- 붙여 보일 박자 분리는 `A|B`를 사용한다.

### 한글 색이 전환 중 이상하게 보임

현재 버전에서는 `rect` 대신 `poke4` 직접 출력으로 수정되어야 한다.

검증:

```powershell
rg "function krrawrect|poke4\\(py\\*240\\+px|rect\\(x\\+xx\\*scale" extract\code_unicode.lua
```

정상 조건:

```text
function krrawrect           있어야 함
poke4(py*240+px,color)       있어야 함
rect(x+xx*scale...)          없어야 함
```

