# EMUUROM 한글화 프로젝트 - 리버스 엔지니어링 문서

> **프로젝트**: EMUUROM 한글화 도구
> **분석 도구**: Ghidra 11.x + GhidrAssist MCP, Python 3.12
> **주요 파일**: `emuurom_tool.py`
> **기준 원본**: `emuurom_backup.exe`

---

## 문서 인덱스

| 파일 | 내용 |
|------|------|
| [01_GameInfo.md](01_GameInfo.md) | 게임 기본 정보, 작업 경로, PE/Ghidra 기본 정보 |
| [02_TICCartFormat.md](02_TICCartFormat.md) | `TIC.CART` overlay, zlib cart, TIC-80 chunk 구조 |
| [03_TextAndKaraoke.md](03_TextAndKaraoke.md) | `text.csv` 구조, Lua 문자열 import, 엔딩 가사 박자 규칙 |
| [04_UnicodeFontPatch.md](04_UnicodeFontPatch.md) | 한글 glyph 생성, 줄바꿈/커서/렌더링 패치 |
| [05_GhidraReverse.md](05_GhidraReverse.md) | Ghidra로 확인한 네이티브 렌더링 함수와 palette 문제 원인 |
| [06_ToolWorkflow.md](06_ToolWorkflow.md) | 현재 툴 사용법, 기본값, test mode, 재빌드 절차 |

---

## 핵심 요약

### 게임/런타임 구조
- **실행 파일**: `emuurom.exe`
- **원본 백업 파일**: `emuurom_backup.exe`
- **런타임**: TIC-80 기반 Windows x86-64 PE
- **게임 코드**: exe 뒤쪽 `TIC.CART` overlay에 zlib 압축 cart로 포함
- **주요 수정 대상**: TIC cart 내부 Lua code chunk

### 현재 한글화 전략
1. `emuurom_backup.exe`에서 TIC cart를 추출한다.
2. Lua code chunk에서 번역 대상 문자열을 `text.csv`로 내보낸다.
3. `text.csv`의 `dst`를 한국어로 채운다.
4. CSV를 Lua에 되돌리고, 한글 bitmap glyph 렌더러를 삽입한다.
5. 수정된 cart를 원본 exe overlay 위치에 다시 붙여 `emuurom.exe`를 만든다.

### 중요한 구현 결론
- 원본 `print`와 `rect`는 네이티브 색 처리 경로가 다르다.
- `rect`는 TIC-80 palette remap 테이블을 거치므로 엔딩 전환 shader 중 한글 glyph 색이 깨졌다.
- 현재 한글 glyph는 `rect` 대신 `poke4(py*240+px,color)`로 직접 framebuffer nibble을 써서 원본 `print`와 같은 방향으로 맞춘다.
- 엔딩 가사는 원본 런타임의 `l:split(" ")` 박자 구조를 유지한다.
- CSV의 `|`는 번역자가 박자 경계를 볼 수 있게 한 편집용 표기이고, import 시 원본 런타임 문자열로 변환된다.

---

## 현재 권장 작업 흐름

게임 루트 폴더에서 작업한다.

```powershell
cd "C:\Program Files (x86)\Steam\steamapps\common\EMUUROM"
python emuurom_tool.py extract
```

`text.csv`를 번역한 뒤:

```powershell
python emuurom_tool.py import
```

엔딩 테스트용 빌드:

```powershell
python emuurom_tool.py import --test-mode
```

기본 입력/출력은 다음과 같다.

| 항목 | 기본값 |
|------|--------|
| 원본 exe | `emuurom_backup.exe` |
| 추출 폴더 | `extract` |
| 번역 CSV | `text.csv` |
| 한글 폰트 | `Galmuri7.ttf` |
| 출력 exe | `emuurom.exe` |
| 출력 cart | `extract/emuurom_patched.cart.bin` |

