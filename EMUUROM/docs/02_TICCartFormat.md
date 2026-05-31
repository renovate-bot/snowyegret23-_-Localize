# 02. TIC cart / overlay 포맷

## exe overlay 구조

`emuurom_tool.py`는 exe 내부에서 `TIC.CART` magic을 찾고, 이 magic이 exe 끝의 유효한 overlay인지 확인한다.

```c
struct EmuuromOverlay {
    char magic[8];        // "TIC.CART"
    uint32_t app_size;    // overlay 시작 오프셋
    uint32_t cart_size;   // zlib 압축 cart 크기
    uint8_t cart_zlib[cart_size];
};
```

검증 조건:

| 조건 | 의미 |
|------|------|
| `app_size == overlay_offset` | overlay가 exe 본문 바로 뒤에 붙어 있음 |
| `app_size + 16 + cart_size == file_size` | overlay가 파일 끝까지 정확히 이어짐 |
| `zlib.decompress(cart_zlib)` 성공 | cart payload가 zlib 압축 TIC cart임 |

관련 함수:

| 함수 | 역할 |
|------|------|
| `find_overlay` | `TIC.CART` magic과 overlay 경계 검증 |
| `extract_cart_from_exe` | overlay 추출, zlib 해제, hash 계산 |
| `build_output` | 수정 cart 재압축 후 원본 exe 앞부분에 다시 붙임 |

---

## TIC cart chunk header

cart는 여러 chunk의 연속이다. 각 chunk는 4바이트 header와 payload로 구성된다.

```c
struct TicChunkHeader {
    uint8_t type_bank;    // low 5 bits: type, high 3 bits: bank
    uint8_t size_lo;
    uint8_t size_hi;
    uint8_t temp;
};
```

`type_bank` 해석:

```text
type = type_bank & 0x1f
bank = (type_bank >> 5) & 7
size16 = size_lo | (size_hi << 8)
```

`size16 == 0`인 code chunk는 full-bank chunk로 취급한다. 도구는 `0x20000`, `0x10000` 후보를 실제 chunk 연속성과 비교해 full code bank 크기를 결정한다.

---

## 확인된 chunk type

| Type | 이름 | 용도 |
|------|------|------|
| 1 | `tiles` | 타일 sheet |
| 2 | `sprites` | 스프라이트 sheet |
| 4 | `map` | TIC map 데이터 |
| 5 | `code` | Lua 코드 |
| 12 | `palette` | palette |
| 18 | `screen` | cover/screen 이미지 |
| 20 | `lang` | 언어 metadata |

도구는 모든 chunk를 보존하고, code chunk와 선택적으로 이미지 chunk만 교체한다.

---

## Lua code chunk 처리

### 추출

`extract_code`는 모든 `type == CODE` chunk의 payload를 이어 붙이고 뒤쪽 `NUL` padding을 제거한다.

```text
CODE bank N
CODE bank N-1
...
→ code.lua
```

### 재삽입

`replace_code_chunks`는 기존 첫 code chunk 위치를 찾고, 그 앞의 non-code chunk를 유지한 뒤 새 code chunk 목록을 만든다.

`make_code_chunks`는 Lua code를 full code bank 크기에 맞춰 분할한다.

---

## 이미지 import/export

추출 시 다음 데이터는 PNG로 내보낸다.

| 대상 | 출력 |
|------|------|
| `tiles` chunk | `extract/images/tiles_b<bank>.png` |
| `sprites` chunk | `extract/images/sprites_b<bank>.png` |
| `screen` chunk | `extract/images/screen_b<bank>.png` |

build 시 `--import-images` 또는 `import` 기본 동작으로 PNG 변경분을 다시 chunk 데이터에 반영한다.

---

## manifest.json

`extract/manifest.json`에는 다음 정보가 저장된다.

| 필드 | 의미 |
|------|------|
| `overlay_offset` | `TIC.CART` 시작 위치 |
| `app_size` | exe 본문 크기 |
| `cart_size` | 압축 cart 크기 |
| `exe_sha256` | 추출 당시 exe hash |
| `cart_sha256` | 압축 해제 cart hash |
| `full_code_size` | code bank 크기 |
| `chunks` | chunk type/bank/size 목록 |

build 시 원본 exe의 overlay 위치가 manifest의 `app_size`와 다르면 중단한다.

