# Furaiki 5 localization notes

이 폴더에는 풍우래기5(風雨来記5 / Furaiki 5) 로컬라이징에 필요한 코드만 정리했다.
원본 게임 파일, 번역 CSV/XLSX, 폰트 파일, 이미지 리소스, 빌드 산출물, 실행 파일은 포함하지 않았다.

## 복사한 코드 파일

- `dat_tool.py`
  - `/res/database/*.dat`의 텍스트를 단일 XLSX로 추출하고, XLSX의 `translation` 열을 다시 `.dat`에 반영한다.
  - Ghidra로 확인한 테이블별 `entry_size`, ID 오프셋, UTF-16LE 텍스트 필드 오프셋을 `SCHEMAS`에 하드코딩해 사용한다.
  - `export`, `import`, `dump`, `expand`, `merge` 명령을 제공한다.
  - `import` 시 UTF-16LE + null 종료 문자열이 필드 한도를 넘으면 출력 파일을 만들지 않고 종료한다.

- `nltex_tool.py`
  - `NMPLTEX1` 텍스처 파일을 PNG로 디코딩하고, PNG를 원본 `.nltx` 헤더를 기준으로 다시 인코딩한다.
  - 단일 파일 변환과 폴더 일괄 변환(`batch-decode`, `batch-encode`)을 지원한다.
  - 픽셀 데이터가 `YKCMP_V1` type 7(zlib)로 압축된 경우 해제/재압축한다.
  - BC1, BC3, BC7 텍스처를 처리한다. BC7은 `texture2ddecoder`, `etcpak` 의존성이 필요하다.

- `fad_tool.py`
  - `.fad` 컨테이너에서 포함된 `NMPLTEX1` 텍스처를 PNG로 추출하고, 수정된 PNG를 다시 `.fad`에 삽입한다.
  - 엔트리가 커지면 기존 위치에 덮어쓰지 않고 파일 끝에 새 데이터를 붙이고 엔트리 테이블의 size/offset을 갱신한다.

- `font_generator.py`
  - OTF(CFF) 폰트를 게임용 `fontTexture.nltx`로 만든다.
  - DSARC FL 컨테이너를 생성하고, 내부 폰트 엔트리를 `YKCMP_V1` type 7(zlib)로 압축한다.
  - 한글 글리프 advance width를 1000으로 맞추고, CFF FontBBox yMin 및 `head` yMin을 원본 게임 폰트에 맞춰 `-416`으로 패치한다.
  - DSARC FL 정보 출력, 내부 폰트 추출, 문자 목록 기반 폰트 커버리지 검증도 지원한다.

## 게임 텍스트 구조

### `/res/database/*.dat`

`dat` 파일은 헤더가 없는 고정 크기 구조체 배열이다. 게임 로더는 파일 전체를 읽고,
파일 크기를 엔트리 크기로 나누어 `std::vector<Entry>`에 그대로 복사하는 구조다.
따라서 엔트리 크기나 텍스트 필드 오프셋을 잘못 잡으면 ID, 해시, 파일명, 좌표 바이트가
UTF-16 문자열로 오독되거나 게임이 크래시할 수 있다.

텍스트 필드는 UTF-16LE + null 종료 방식이다. `max_bytes` 안에는 null 2바이트도 포함되므로
실제 최대 글자 수는 `max_bytes / 2 - 1`이다.

주요 번역 대상 필드:

| 파일 | 엔트리 크기 | ID 오프셋 | 텍스트 필드 |
| --- | ---: | ---: | --- |
| `StringTableParam.dat` | `0x108` | `+0x04` | `+0x08`, 256 bytes, UI/대사 문자열 |
| `BgmTable.dat` | `0x30` | `+0x00` | `+0x04`, 32 bytes, 곡 제목 |
| `CharacterTable.dat` | `0x2C` | `+0x00` | `+0x0C`, 16 bytes, 이름 / `+0x1C`, 8 bytes, 별칭 |
| `ScriptNameTable_*.dat` | `0x54` | `+0x00` | `+0x14`, 64 bytes, 씬 제목 |
| `SpotTableParam.dat` | `0x48` | `+0x00` | `+0x10`, 32 bytes, 스팟 이름 |
| `TouringTableParam.dat` | `0xA4` | `+0x00` | `+0x22`, 54 bytes, 도로명 / `+0x62`, 14 bytes, 도시명 |
| `GourmetSpotTableParam.dat` | `0x88` | `+0x00` | `+0x08`, 36 bytes, 음식점 이름 |
| `ArticleTableParam.dat` | `0x68` | `+0x00` | `+0x08`, 32 bytes, 기사 제목 |
| `HeroineArticleTableParam.dat` | `0x38` | `+0x00` | `+0x08`, 32 bytes, 히로인 기사 제목 |
| `TrendTable.dat` | `0x48` | `+0x00` | `+0x04`, 60 bytes, 트렌드 키워드 |
| `ContestEntryTableParam.dat` | `0x40` | `+0x00` | `+0x04`, 32 bytes, 출판사 / `+0x24`, 16 bytes, 저자 |

`TouringTableParam`은 일부 엔트리에서 런타임 치환을 한다. 로더 `FUN_1400a1670`은
`+0x22`의 UTF-16 문자열이 `"-1.0\0"` 센티넬이면 `StringTableParam`에서
`string_id == 0x2a`인 문자열을 찾아 해당 위치에 복사한다.

### `/res/script/*.csv`

스크립트 CSV는 UTF-16 텍스트로 다룬다. 번역 시 셀 수, 콤마 위치, 마지막 빈 셀,
줄바꿈, 전각/반각, 게임 토큰을 보존해야 한다. 이 폴더에는 CSV 자동 번역 스크립트는 포함하지 않았다.

## 폰트 구조

`fontTexture.nltx`는 이름과 달리 일반 NLTEX 이미지가 아니라 DSARC FL 컨테이너다.

DSARC FL 헤더:

| 오프셋 | 크기 | 의미 |
| ---: | ---: | --- |
| `0x00` | 8 | magic `"DSARC FL"` |
| `0x08` | 4 | entry count, little endian |
| `0x0C` | 4 | reserved |

엔트리 테이블은 `0x10`부터 시작하며, 엔트리 하나는 `0x80` bytes다.

| 엔트리 내부 오프셋 | 크기 | 의미 |
| ---: | ---: | --- |
| `0x00` | 116 | null 종료 ASCII 이름 |
| `0x74` | 4 | data size |
| `0x78` | 8 | file absolute data offset |

원본 `fontTexture.nltx`에는 `fot-seuratpron-m.ks4` 엔트리 1개가 들어 있으며,
내부 데이터는 FreeType이 읽는 폰트 파일이다. 원본은 `YKCMP_V1` type 3(Huffman) 압축으로 확인되었다.
`font_generator.py`는 새 폰트를 `fot-seuratpron-m.ks4` 엔트리로 넣고 `YKCMP_V1` type 7(zlib)로 압축한다.

폰트 로딩 흐름:

1. `Furaiki5_steam.exe`의 `FUN_140141d40`에서 폰트 초기화가 시작된다.
2. `fontTexture.nltx` DSARC FL 아카이브를 연다.
3. 아카이브 안의 폰트 엔트리를 읽는다.
4. `YKCMP_V1`이면 `CCompress`로 디코딩한다.
5. 디코딩된 폰트를 메모리 파일로 열고 FreeType 기반 폰트 객체를 초기화한다.
6. 글리프는 요청 시 텍스처 페이지에 렌더링되어 캐시된다.

게임의 폰트 텍스처 캐시는 2048x2048 A8 텍스처를 사용하며, 셀 크기는 64x128이다.
텍스처 하나당 32x16, 즉 512 글리프를 담는다.

## 이미지/리소스 구조

### `NMPLTEX1` / `.nltx`

일반 이미지 `.nltx`는 `NMPLTEX1` magic을 가진 텍스처 파일이다. 헤더 크기는 `0x80` bytes이며,
`nltex_tool.py`가 사용하는 주요 필드는 다음과 같다.

| 오프셋 | 의미 |
| ---: | --- |
| `0x10` | format |
| `0x14` | flags |
| `0x18` | width |
| `0x1C` | height |
| `0x26` | compress flag |
| `0x2C` | decompressed pixel size |
| `0x30` | compressed size |
| `0x34` | pixel data offset |

픽셀 데이터는 raw 또는 `YKCMP_V1` type 7(zlib) 압축일 수 있다.
실제 블록 포맷은 데이터 크기와 플래그를 기준으로 BC1, BC3, BC7 중 하나로 판별한다.

### `.fad`

`fad_tool.py` 기준의 `.fad` 구조:

- `+0x08`: named entry count
- `+0x0C`: resource entry count
- `+0x50`: 엔트리 테이블 시작
- 엔트리 하나는 `0x20` bytes
- 엔트리 내부:
  - `+0x00`: 8 bytes ASCII name
  - `+0x08`: size
  - `+0x0C`: flags
  - `+0x10`: offset

FAD 내부 엔트리 데이터에서 `NMPLTEX1` magic을 찾아 텍스처로 처리한다.
현재 도구는 FAD 안의 텍스처를 BC7로 디코딩/인코딩한다.

`res/fairy/ui.fad`에서 확인된 타이틀 화면 관련 엔트리:

| 엔트리 | 추출 파일명 | 크기 | 내용 |
| ---: | --- | --- | --- |
| 44 | `044_tex.png` | 1920x1080 | 타이틀 화면 배경 사진 |
| 48 | `048_tex.png` | 2048x2048 | 타이틀 로고, 기본 메인메뉴 atlas, 권리표기 버튼 |
| 49 | `049_tex.png` | 2048x1024 | 권리표기/라이선스 화면 텍스트 |
| 50-54 | `050_tex.png` - `054_tex.png` | 2048x2048 | 타이틀 로고/메뉴 변형 atlas. 권리표기 버튼 아이콘 또는 메뉴 구성이 조금씩 다름 |

메인메뉴의 `はじめから`, `つづきから`, `オプション`, `おまけ`, `ゲームを終了` 등은
DAT/CSV 문자열이 아니라 위 PNG atlas에 래스터라이즈되어 있다. 따라서 메인메뉴 한글화는
`StringTableParam.dat` 수정만으로는 적용되지 않고, `ui.fad`의 48, 50-54번 텍스처를 수정해야 한다.

## 추출/수정/재삽입 workflow

### DAT 텍스트

1. 원본 `/res/database` 폴더를 작업용으로 복사한다.
2. 텍스트 추출:

   ```bash
   python dat_tool.py export database_copy dat_export.xlsx
   ```

3. XLSX의 `translation` 열에 번역을 입력한다.
4. 기존 번역 XLSX를 새 스키마 XLSX에 옮겨야 하면:

   ```bash
   python dat_tool.py merge old.xlsx dat_export.xlsx
   ```

5. 재삽입:

   ```bash
   python dat_tool.py import dat_export.xlsx database_copy out_database
   ```

6. `out_database`의 `.dat` 파일을 게임의 `/res/database`에 반영한다.

### UI 텍스처 / 일반 NLTEX

단일 파일:

```bash
python nltex_tool.py decode input.nltx output.png
python nltex_tool.py encode edited.png input.nltx output.nltx
```

폴더 일괄 처리:

```bash
python nltex_tool.py batch-decode original_nltx_dir png_dir
python nltex_tool.py batch-encode edited_png_dir original_nltx_dir out_nltx_dir
```

### FAD 텍스처

```bash
python fad_tool.py export ui.fad fad_png
python fad_tool.py import ui.fad fad_png ui_new.fad
```

특정 텍스처만 재삽입하려면 수정한 PNG만 별도 폴더에 넣어 `import`를 실행한다.
예를 들어 메인메뉴만 수정할 때는 `048_tex.png`, `050_tex.png` - `054_tex.png`만 넣은 폴더를 사용하면
다른 UI 텍스처를 다시 인코딩하지 않는다.

### 폰트

1. 후보 OTF 폰트의 커버리지를 확인한다.

   ```bash
   python font_generator.py validate font.otf --charlist CharList_3911.txt
   ```

2. 게임용 폰트 아카이브를 만든다.

   ```bash
   python font_generator.py create font.otf fontTexture.nltx --name fot-seuratpron-m.ks4
   ```

3. 생성된 `fontTexture.nltx`를 게임 리소스 위치에 반영한다.

## EXE / binary patch 관련

현재 복사한 코드 안에는 EXE를 자동 패치하는 스크립트가 없다.

확인된 선택지는 `StringTableParam.dat`의 엔트리 크기 확장이다. 기본 엔트리 크기는 `0x108`이고,
`dat_tool.py expand`는 데이터 파일만 더 큰 엔트리 크기로 재배치한다.
이 파일을 게임에서 사용하려면 `Furaiki5_steam.exe`의 `StringTableParam` 전용 `0x108` 상수도 같은 값으로 바꿔야 한다.

분석된 패치 대상:

- `FUN_1400a2d30`: `StringTableParam` 로더 내부의 `div 0x108` / `mul 0x108`
- `FUN_1400a1670`: `TouringTableParam` 로더 안에서 `StringTableParam`을 참조하는 루프
- `FUN_1400a0c90`: 메인 로더 후반의 `IMUL ..., 0x108` 비교
- 접근자 함수:
  - `FUN_14009c030`
  - `FUN_14009c2a0`
  - `FUN_14009c860`
  - `FUN_14009ede0`
  - `FUN_14009f410`
  - `FUN_1400a0a90`
  - `FUN_1400de5a0`
  - `FUN_1401b302b`

`StringTableParam`의 in-memory 기준 위치는 `param_1 + 0x124db20`로 분석되었고,
바이트 패턴 `20 db 24 01`로 관련 참조를 찾을 수 있다.
단, `0x108`은 게임 전체에서 다른 구조체 크기로도 많이 쓰이므로 `StringTableParam` 참조 주변의 상수만 수정해야 한다.
확인된 PE 섹션명과 파일 오프셋은 정리된 자료 안에 없어서 기록하지 않았다.

권장 방식은 먼저 기본 한도 안에서 번역을 줄이는 것이다. 실제 프로젝트 대부분은
`StringTableParam`의 127자 제한을 유지하는 방식으로 충분하다.

## 중요한 구현 이유와 시행착오

- 예전 자동 스캔 방식은 고정 구조체 내부의 ID, 해시, ASCII 파일명, float 좌표까지 UTF-16로 오독했다.
  그래서 `dat_tool.py`는 자동 추측을 제거하고, Ghidra로 확인한 스키마만 사용한다.
- `dat_tool.py import`는 조용히 문자열을 자르지 않는다. 한도 초과를 발견하면 실패시켜 XLSX에서 번역을 줄이도록 한다.
- 폰트는 TTF보다 OTF(CFF)를 전제로 처리한다. 코드에는 TTF 사용 시 advance width 문제가 발생한다고 되어 있어,
  `font_generator.py`는 입력 폰트가 `OTTO` magic이 아니면 종료한다.
- 한글 폰트는 advance width 1000, yMin `-416` 패치를 적용해야 원본 폰트와 수직 위치가 맞는다.
- FAD 재삽입은 새 텍스처가 기존 엔트리보다 커질 수 있으므로, 크기가 늘어난 경우 파일 끝에 붙이고 테이블 offset을 갱신한다.

## Python 의존성

필요 기능에 따라 다음 패키지가 필요하다.

```bash
pip install openpyxl Pillow texture2ddecoder etcpak fonttools
```

`dat_tool.py`만 사용할 때는 `openpyxl`이 필요하다.
`font_generator.py`의 폰트 패치/검증에는 `fonttools`가 필요하다.
`nltex_tool.py`와 `fad_tool.py`의 이미지 변환에는 `Pillow`, `texture2ddecoder`, `etcpak`이 필요하다.
