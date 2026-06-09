# 슈퍼로봇대전 64 한글화 툴 메모

## 포함 파일

- `tools/srw64_resources.py`: N64 리소스 테이블 파싱, 게임 LZ 리소스 압축 해제/재압축, `0x0005` I4 텍스처 리소스 변환, 리소스 교체와 확장 리소스 재배치를 담당합니다.
- `tools/srw64_text.py`: 글리프 스트림 텍스트 테이블 파싱, 폰트 아틀라스 기반 미리보기, 번역 CSV 추출/검증/병합, 한글 글리프 그리기, 텍스트 패치와 텍스트 풀 재배치를 담당합니다.
- `build_current_translation_rom.py`: 폰트 리소스 `1`을 확장하고, 현재 번역에 필요한 한글을 확장 슬롯에 배정한 뒤, 번역 텍스트를 적용해 고정 이름의 패치 롬을 만듭니다.
- `build_patched_rom.bat`: Windows에서 원본 롬, 병합 번역 CSV, 한글 TTF 경로를 입력받아 빌드 스크립트를 실행합니다.
- `reference/srw64_glyph_map_seed.csv`: 확인된 글리프 ID와 원문 문자 매핑표입니다. 텍스트 추출과 기존 글리프 재사용에 사용합니다.
- `reference/srw64_unknown_glyph_policy.csv`: 일반 텍스트가 아닌 플레이스홀더/UI 글리프를 번역하지 않고 보존하기 위한 정책표입니다.

## 의존성

- Python 3.12 이상 권장
- `Pillow`: 폰트 아틀라스 렌더링과 텍스처 변환에 필요

설치:

```powershell
python -m pip install -r requirements.txt
```

## 롬 형식

작업 롬은 big-endian N64 형식이어야 합니다.

```text
80 37 12 40
```

작업 프로젝트의 원본 `.n64` 백업은 byteswapped 형식(`37 80 40 12`)이었기 때문에, 도구는 정규화된 `.z64` 사본 기준으로 개발했습니다. 현재 빌드 출력 이름은 항상 다음으로 고정합니다.

```text
games\Super Robot Taisen 64 (Japan) (patched).n64
```

확장자는 로컬 빌드 규칙일 뿐이며, 현재 출력 데이터는 big-endian입니다.

## 리소스 구조

압축 리소스 인덱스 시작 ROM 오프셋:

```text
0x00a20bd0
```

각 리소스 테이블 엔트리:

```text
relative_offset, span_size
```

리소스 본문은 `0x00a20bd0 + relative_offset` 위치에서 시작하고, 32비트 압축 해제 크기 뒤에 압축 데이터가 이어집니다. 원위치 패치는 `span_size - 4` 안에 들어가야 합니다. 더 커진 리소스는 `patch_resource_to_pool()`로 롬 뒤쪽 패딩 공간에 새로 쓰고 리소스 테이블을 갱신합니다.

## 폰트 구조와 현재 사용 폰트

확인된 동적 폰트 아틀라스 리소스:

```text
resource 0: 504x504
resource 1: 504x252 원본, 한글 빌드에서 504x504로 확장
```

확인된 글리프 슬롯:

```text
0x0000-0x013a: 8x14 글리프, resource 0
0x013b-0x0596: 14x14 글리프, resource 0, atlas y offset 0x46
0x0597-0x081e: 14x14 글리프, resource 1 원본 영역
0x081f-0x0aa6: 14x14 글리프, resource 1 확장 영역
```

현재 중간 빌드의 한글 폰트 설정:

```text
font file: UmdotMono14.ttf
slot size: 14x14
font size: 14
y offset: 2
```

`UmdotMono14.ttf`는 작업 폴더에서 사용한 입력 폰트이며, 이 공유용 소스 폴더에는 포함하지 않습니다. 작은 UI용 8픽셀 계열 폰트(`MonaS8x12.ttf`)는 후보로 검토했지만, 현재 공유 빌드 경로에는 아직 통합하지 않았습니다. 지금 패치에서 메뉴 문자열이 칸을 뚫고 나오는 경우는 폰트 파일 문제가 아니라 원래 UI 폭과 문자열 길이 문제일 가능성이 높으므로, 우선 UI 번역을 짧게 줄이고 필요하면 별도 폭/렌더러 패치를 진행해야 합니다.

## 텍스트 구조

동적 렌더러는 16비트 글리프 ID를 소비합니다. 텍스트 테이블 베이스 포인터는 ROM 파일 오프셋에서 읽습니다.

```text
0x05ab60
```

확인된 table 0 base:

```text
0x01a34980
```

각 텍스트 테이블 엔트리 디스크립터:

```text
relative_offset, byte_size
```

엔트리 본문은 8바이트 헤더 뒤에 16비트 글리프 ID 스트림이 옵니다. 주요 제어값:

```text
0xffff: terminator
0xfffe: line break/control
0xfffd: run stop 또는 문맥별 terminator
0x0000: space
```

원래 슬롯보다 길어진 엔트리는 `tools/srw64_text.py`가 패딩 텍스트 풀에 새로 쓰고 디스크립터를 재지정할 수 있습니다. 현재 빌드의 풀 위치:

```text
resource pool: 0x01d90000-0x01db0000
text pool:     0x01db0000
```

## 권장 작업순서

1. 원본 롬을 big-endian 형식으로 정규화합니다. 첫 4바이트가 `80 37 12 40`인지 확인합니다.
2. `python -m pip install -r requirements.txt`로 의존성을 설치합니다.
3. `reference\srw64_glyph_map_seed.csv`를 사용해 전체 텍스트를 추출합니다.
4. 번역 전에 빠진 일본어와 미확인 글리프를 먼저 채웁니다. `classify-translation` 결과와 `reference\srw64_unknown_glyph_policy.csv`를 대조하고, 필요하면 폰트 이미지/미리보기/일본어 대사 코퍼스를 보고 `srw64_glyph_map_seed.csv`를 갱신합니다.
5. 글리프가 문자로 확정되지 않은 행, `token_src` 같은 플레이스홀더 행, UI 장식 글리프는 성급히 번역하지 말고 보존 정책부터 정합니다.
6. `empty_dst` 기준으로 번역 배치를 만듭니다.
7. 각 배치를 번역합니다. 키와 행 순서는 보존하고, 제어코드와 플레이스홀더는 그대로 유지합니다. 긴 기체명/인명은 `--allow-text-expansion` 기준으로 검증합니다.
8. 배치마다 `validate-translation-batch`로 검증합니다.
9. 검증된 배치를 `merge-translation-batches`로 병합합니다.
10. 병합 CSV를 다시 `classify-translation --allow-text-expansion`으로 검사합니다. 미확인 글리프, 비정상 길이, 보존 실패가 남아 있으면 빌드 전에 수정합니다.
11. `build_current_translation_rom.py` 또는 `build_patched_rom.bat`로 패치 롬을 빌드합니다.
12. 에뮬레이터에서 `games\Super Robot Taisen 64 (Japan) (patched).n64`를 열어 대사, 메뉴, 기체명, 줄바꿈, UI 넘침을 확인합니다.
13. UI 넘침은 먼저 번역을 줄여 해결하고, 줄여도 안 되는 영역은 렌더러 폭 패치나 8픽셀 계열 UI 폰트 통합을 별도 작업으로 진행합니다.

## 주요 명령

전체 텍스트 추출:

```powershell
python tools\srw64_text.py export-translation-all "Super Robot Taisen 64 (Japan).z64" translations_seed.csv --glyph-map reference\srw64_glyph_map_seed.csv
```

패치 가능성 분류:

```powershell
python tools\srw64_text.py classify-translation translations_seed.csv translation_patchability.csv --unknown-glyph-policy reference\srw64_unknown_glyph_policy.csv --allow-text-expansion
```

번역 배치 검증:

```powershell
python tools\srw64_text.py validate-translation-batch batch_source.csv batch_ko.csv --allow-text-expansion
```

번역 배치 병합:

```powershell
python tools\srw64_text.py merge-translation-batches translations_seed.csv translations\batches translations_seed.batches_all.csv
```

패치 롬 빌드:

```powershell
python build_current_translation_rom.py "Super Robot Taisen 64 (Japan).z64" translations_seed.batches_all.csv UmdotMono14.ttf
```

BAT 실행:

```powershell
.\build_patched_rom.bat
```

## 현재 확인된 중간 빌드 사실

작업 프로젝트의 중간 빌드는 번역 배치 56개와 번역 적용 행 4,480개를 사용했습니다.

대표 확장 이름 행:

```text
t00_04528 大作 -> 다이사쿠
t00_04553 忍   -> 시노부
t00_04587 デビッド -> 데이비드
```

대표 확인값:

```text
resource 1 expanded size: 504x504
translated rows: 4480
new Korean/symbol characters: 628
tests: 68 passed, 1 skipped
```
