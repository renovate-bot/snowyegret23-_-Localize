# Dream Tactics 한글화 프로젝트 - 리버스 엔지니어링 문서

> **프로젝트**: Dream Tactics (Spectra Entertainment) 한글화
> **분석 도구**: Ghidra 11.x + GhidraMCP
> **최종 상태**: LZHAM 압축 해제/재압축 성공, 로케일 파일 한글화 완료
> **공개**: 오픈소스

---

## 문서 인덱스

| 파일 | 내용 |
|------|------|
| [01_GameInfo.md](01_GameInfo.md) | 게임 기본 정보, 경로, PE 파일 분석 |
| [02_DataFormat.md](02_DataFormat.md) | 해시 알고리즘, data/0 인덱스, 에셋 타입 |
| [03_Localization.md](03_Localization.md) | 언어 테이블, 로케일 파일, 텍스트 ID 시스템 |
| [04_Compression.md](04_Compression.md) | LZHAM 압축 분석, 파일 포맷, 압축/해제 |
| [05_GhidraReverse.md](05_GhidraReverse.md) | 주요 함수/데이터 주소, 디컴파일 결과 |
| [06_PatchTool.md](06_PatchTool.md) | apply_patch 도구 사용법/구조 |
| [07_Scripts.md](07_Scripts.md) | Python 유틸리티 스크립트 모음 |

---

## 핵심 요약

### 게임 기본
- **실행 파일**: `Dream.exe` (PE x86-64, OpenGL 3.1+, 자체 엔진)
- **에셋 구조**: `data/%u` 해시 기반 파일명 (2,710개)
- **언어**: english(0), japanese(1), chinese(2) — korean 미지원 → 기존 언어 덮어쓰기

### 핵심 발견
1. **해시 알고리즘**: Case-Insensitive DJB2 (초기값 `0x1505`, 승수 `0x21`)
2. **`data/0`**: 에셋 인덱스 파일 (2,708 엔트리 × 12바이트)
3. **Type 2 JSON**: 로케일 파일 (`locale/*.json`)
4. **LZHAM 압축**: `dict_size_log2 = 18` (기본 파라미터)
5. **압축 해제 포맷**: `[uint32 json_size][JSON UTF-8]`

### 한글화 대상 파일 (data/ 폴더)
| 파일 | 해시 | 원본 |
|------|------|------|
| UI EN | `515357558` | `locale/english.json` |
| UI JA | `2946173491` | `locale/japanese.json` |
| UI CN | `3584817163` | `locale/chinese.json` |
| TEXT EN | `4073104832` | 본문 영어 |
| TEXT JA | `92749245` | 본문 일본어 |
| TEXT CN | `2847597141` | 본문 중국어 |
| FONT PIXEL JA | `1508373377` | 픽셀 폰트 일본어 |
| FONT PIXEL CN | `2256482679` | 픽셀 폰트 중국어 |
| FONT NORMAL CN | `2973124184` | 일반 폰트 중국어 |

### 한글화 전략
- 중국어(`chinese`) / 일본어(`japanese`) 로케일을 한국어로 덮어쓰기
- 폰트는 Mulmaru TTF로 교체 (한글 지원)
- 게임 `options.json`의 `language: 1` 또는 `2` 선택
