# 01. 게임 기본 정보

## 게임 기본

| 항목 | 내용 |
|------|------|
| **게임명** | EMUUROM |
| **실행 파일** | `emuurom.exe` |
| **원본 백업 파일** | `emuurom_backup.exe` |
| **아키텍처** | x86-64 |
| **파일 포맷** | PE (Portable Executable) |
| **런타임** | TIC-80 기반 Windows 빌드 |
| **그래픽/입력 기반** | SDL/OpenGL 문자열 및 TIC-80 API 문자열 확인 |
| **수정 대상** | exe overlay의 zlib 압축 TIC cart |

---

## 작업 경로

### 저장소 경로

```text
C:/Users/USER/Documents/GitHub/Localize/EMUUROM/
├── emuurom_tool.py
└── docs/
```

### 게임 설치 경로

```text
C:/Program Files (x86)/Steam/steamapps/common/EMUUROM/
├── emuurom_backup.exe     # 원본 기준 파일
├── emuurom.exe            # 패치 결과 파일
├── emuurom_tool.py        # 게임 루트에서 실행하는 도구
├── Galmuri7.ttf           # 한글 glyph 생성용 폰트
├── text.csv               # 번역 CSV
└── extract/               # 추출/중간 산출물
```

---

## Ghidra 기준 PE 정보

대상 프로그램은 `emuurom_backup.exe`이다.

| 항목 | 값 |
|------|-----|
| **Image Base** | `0x140000000` |
| **Min Address** | `0x140000000` |
| **Max Address** | `0xff0000184f` |
| **함수 수** | 6,611개 |
| **Language ID** | `x86:LE:64:default` |

### PE 섹션

| 섹션 | VMA | 크기 | 속성 |
|------|-----|------|------|
| `Headers` | `0x140000000` | `0x400` | R |
| `.text` | `0x140001000` | `0x25fe00` | RX |
| `.rdata` | `0x140261000` | `0xa5600` | R |
| `.data` | `0x140307000` | `0x7f440` | RW |
| `.pdata` | `0x140387000` | `0x1d600` | R |
| `.fptable` | `0x1403a5000` | `0x200` | RW |
| `.rsrc` | `0x1403a6000` | `0x8400` | R |
| `.reloc` | `0x1403af000` | `0x2600` | R |
| `tdb` | `0xff00000000` | `0x1850` | RW |

---

## 확인된 TIC-80 문자열

Ghidra string search에서 다음 문자열이 확인된다.

| 주소 | 문자열 |
|------|--------|
| `0x140262f00` | `TIC-80` |
| `0x140263350` | `TIC-80 startup options:` |
| `0x140264250` | `TIC-80 tiny computer` |
| `0x140264cc8` | `TIC-80 OPTIONS` |
| `0x140264cd8` | `QUIT TIC-80` |

이 문자열들은 실행 파일이 일반 게임 엔진이 아니라 TIC-80 기반 런타임을 포함한다는 근거이다.

---

## 원본 보존 규칙

- `emuurom_backup.exe`는 항상 원본 기준으로 둔다.
- `extract/manifest.json`에는 추출 당시 `app_size`, overlay 위치, hash, chunk 목록이 저장된다.
- build 시 입력 exe의 overlay 위치가 추출 당시 `app_size`와 맞지 않으면 중단한다.

