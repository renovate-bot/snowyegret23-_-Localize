# 04. LZHAM 압축 분석

## 1. 알고리즘 식별: LZHAM

초기에는 LZMA로 추정했으나, 코드 문자열 및 함수 구조 분석을 통해 **LZHAM**(LZ + Huffman + ANS, Richard Geldreich 개발) 으로 확정.

### 증거
1. **바이너리 내 경로 문자열**:
   ```
   D:\spectra\avarice\external\lzham\src\...
   ```
   - 주소: `0x140661d90`, `0x140661f90`
2. **에러 문자열**:
   ```
   "lzham::vector operator=: Out of memory!"
   "lzham_malloc: size too big"
   "lzham_malloc: out of memory"
   ```
3. **코드 구조**: `FUN_14035acc0`의 초기화 로직이 LZHAM SDK의 `lzham_decompress_init`와 일치

---

## 2. 파일 헤더 구조 (분석 결과)

영어와 중국어 파일 비교:

```
Chinese (data/3584817163):
40 00 05 EB 02 A5 F0 20 05 B7 B2 24 C6 F6 34 36
16 C6 54 96 42 23 90 08 2D 0D CD 8C 8E 4B C8 0D ...

English (data/515357558):
40 00 05 EB 0D 16 10 20 05 B7 B2 24 C6 F6 34 36
16 C6 54 96 42 23 90 08 2C ED AD 6C 6E 2B C8 0D ...
```

| Offset | Hex (Chinese) | Hex (English) | 분석 |
|:---:|---|---|---|
| **0x00~0x03** | `40 00 05 EB` | `40 00 05 EB` | LZHAM 스트림 시작 (첫 2바이트는 ZLIB-스타일 헤더) |
| **0x04~0x07** | `02 A5 F0 20` | `0D 16 10 20` | 가변 데이터 |
| **0x08~0x17** | `05 B7 ... 36` | `05 B7 ... 36` | 파일 간 공통 부분 (LZHAM 내부 상태) |
| **0x18~** | `2D 0D ...` | `2C ED ...` | 파일별 고유 압축 데이터 |

### 핵심 결론
- 파일 전체가 LZHAM 스트림 (offset 0부터)
- 압축 해제된 페이로드 = `[uint32 JSON 크기][JSON UTF-8]`
- Seed Bytes 미사용 (LZHAM 파라미터에 0 전달)

---

## 3. 핵심 LZHAM 파라미터

### 분석 경로: FUN_1402e3a10 (디컴프레서 초기화)

```c
fVar4 = DAT_140645d70;        // 0x48800000 = 262144.0 (float)
local_38[0] = 0x28;           // struct_size = 40 bytes
local_38[1] = 0;
fVar4 = (float)FUN_14054b058(fVar4);   // log2(262144.0) = 18.0
local_38[1] = (int)fVar4;     // dict_size_log2 = 18
// local_38[2~9] = 0 으로 초기화됨
puVar1 = thunk_FUN_14035acc0(local_38);  // LZHAM 디코더 생성
```

### 파라미터 구조체 (`lzham_decompress_params`)
```c
struct lzham_decompress_params {
    uint32_t m_struct_size;           // [0] = 0x28
    uint32_t m_dict_size_log2;        // [1] = 18 (확정)
    uint32_t m_decompress_flags;      // [2] = 0
    uint32_t m_num_seed_bytes;        // [3] = 0  (Seed bytes 미사용)
    uint32_t m_table_update_rate;     // [4] = 0  (기본값)
    const uint8_t *m_pSeed_bytes;     // [6] = NULL
    // ...
};
```

### 확정된 설정값
| 파라미터 | 값 | 설명 |
|----------|-----|------|
| `dict_size_log2` | **18** | 256KB dictionary |
| `decompress_flags` | 0 | 표준 버퍼 모드 |
| `num_seed_bytes` | 0 | Seed bytes 미사용 |
| `table_update_rate` | 0 | LZHAM 내부 기본값 |
| `pSeed_bytes` | NULL | Seed bytes 포인터 미사용 |

**참고**: 과거 분석에서 `m_table_max_update_interval = 36`으로 추정했으나, 실제 코드는 파라미터에 0을 전달 → LZHAM 내부 기본값 사용 (수정됨)

---

## 4. 압축 해제 플로우

### FUN_1402dea50 - JSONFile_Load

**주소**: `0x1402dea50`
**역할**: 압축된 JSON 파일 로드 및 파싱

```c
bool FUN_1402dea50(undefined8 param_1, undefined8* param_2, ...)
{
    undefined8 local_68[12];

    FUN_1402e3a10(local_68, param_1, ...);       // 1. 디컴프레서 초기화
    uint uVar2 = FUN_1402b5d20(local_68);        // 2. uncompressed size 읽기
    char* pcVar3 = (char*)operator_new(uVar2);   // 3. 버퍼 할당
    FUN_1402e3c40(local_68, pcVar3, uVar2);      // 4. 압축 해제
    FUN_14028f610(param_2, pcVar3, uVar2);       // 5. JSON 파싱
    // 6. 정리
    FUN_1402e3b60(local_68, pcVar3, uVar2);
    return param_2[10] == 0;
}
```

### FUN_1402e3c40 - 스트리밍 압축 해제

내부적으로 `thunk_FUN_14035abb0` → `FUN_1403537e0` 호출 (실제 LZHAM 압축 해제 코어).

### FUN_1402b5d20 - Uncompressed Size 읽기

```c
// 압축 해제 스트림에서 4바이트 읽음 (엔디안 스왑 조건부)
(**(code**)*param_1)(param_1, &local_res8, 4);  // vtable[0]: 압축 해제
if (*(char*)(param_1 + 1) != '\0') {
    // 엔디안 스왑 (기본은 '0' → 스왑 안 함)
}
return local_res8;
```

**결론**: `param_1 + 1 = 0`이므로 엔디안 스왑 없이 little-endian uint32로 읽음.

---

## 5. 파일 포맷 (최종 확정)

```
+-------------------------------------------------------+
| LZHAM 압축 스트림 (offset 0부터 파일 끝까지)            |
| Parameters: dict_size_log2=18, 기본값                  |
+-------------------------------------------------------+
                          ↓ 압축 해제
+-------------------------------------------------------+
| [4바이트: uint32 JSON 크기 (little-endian)]            |
| [JSON UTF-8 데이터 (크기 = 위 uint32)]                 |
+-------------------------------------------------------+
```

### 검증 결과

**영어 파일 (`data/515357558`)**:
- 압축된 크기: 32,615 bytes
- JSON 크기 (헤더에서): 156,113 bytes
- 시작: `[{"LocaleId":"Biomes_AshguardName","Text":"EMPIRE OF ASHGUARD"},...`

**중국어 파일 (`data/3584817163`)**:
- 압축된 크기: 34,598 bytes
- JSON 크기 (헤더에서): 155,434 bytes
- 시작: `[{"LocaleId":"Biomes_AshguardName","Text":"阿什加德帝国"},...`

---

## 6. Python 구현 (pylzham)

### 압축 해제
```python
import struct
from lzham import LZHAMDecompressor

DICT_SIZE_LOG2 = 18

def unpack_memory(file_path: str) -> bytes:
    """data/<hash> 파일을 읽어 JSON UTF-8 바이트를 반환"""
    with open(file_path, "rb") as f:
        data = f.read()

    dec = LZHAMDecompressor(filters={"dict_size_log2": DICT_SIZE_LOG2})
    result = dec.decompress(data, 1000000)  # 충분히 큰 크기 지정

    json_size = struct.unpack("<I", result[:4])[0]
    json_data = result[4 : 4 + json_size]
    return json_data

# 사용 예시
json_bytes = unpack_memory("./data/515357558")
import json
ui_list = json.loads(json_bytes)
print(ui_list[0])  # {'LocaleId': 'Biomes_AshguardName', 'Text': 'EMPIRE OF ASHGUARD'}
```

### 재압축
```python
from lzham import compress

def pack_memory(json_data: bytes) -> bytes:
    """JSON UTF-8 바이트를 LZHAM 압축 포맷으로 반환"""
    payload = struct.pack("<I", len(json_data)) + json_data
    compressed = compress(payload, filters={"dict_size_log2": DICT_SIZE_LOG2})
    return compressed

# 사용 예시
import json
patched_json = json.dumps(ui_list, ensure_ascii=False).encode("utf-8")
compressed = pack_memory(patched_json)
with open("./data/515357558", "wb") as f:
    f.write(compressed)
```

---

## 7. 압축 해제 시도 내역 (Chronology)

### Phase 1: 표준 라이브러리 시도 (실패)
- Python `lzma`, `zlib`, `lz4` 모두 실패
- 원인: LZHAM 포맷 비호환

### Phase 2: C++ LZHAM SDK 표준 (실패)
- `lzham_codec`을 `-d18` 옵션으로 빌드 실행
- 결과: `LZHAM_DECOMP_STATUS_FAILED`
- 잘못된 가설: 게임이 비표준 Update Rate 사용

### Phase 3: C++ LZHAM 커스텀 Hack (부분 성공)
- `lzham_lzdecomp.cpp` 수정해서 파라미터 강제 주입
- `[SUCCESS]` 메시지는 나왔으나 출력 0 bytes
- 원인: Adler32 체크섬 실패 → 출력 버퍼 리셋

### Phase 4: pylzham 사용 (성공!) ✅
- `dict_size_log2=18`만 설정
- 나머지 파라미터 기본값
- 첫 시도에 성공

---

## 8. 주요 LZHAM 관련 함수 주소

| 함수 | 주소 | 역할 |
|------|------|------|
| `JSONFile_Load` | `0x1402dea50` | JSON 파일 로드 (메인) |
| `Decompressor_Init` | `0x1402e3a10` | 디컴프레서 초기화 |
| `Decompressor_GetOutputSize` | `0x1402b5d20` | uncompressed size 읽기 |
| `Decompressor_Decompress` | `0x1402e3c40` | 스트리밍 압축 해제 |
| `Decompressor_Cleanup` | `0x1402e3b60` | 정리 |
| `JSON_Parse` | `0x14028f610` | JSON 파싱 |
| LZHAM decoder init | `0x14035acc0` | `lzham_decompress_init` 등가 |
| LZHAM reinit | `0x14035af70` | `lzham_decompress_reinit` 등가 |
| LZHAM decompress | `0x14035abb0` | `lzham_decompress` 등가 |
| LZHAM decompress core | `0x1403537e0` | 실제 압축 해제 코어 |

### 주요 데이터 주소
| 항목 | 주소 | 값 |
|------|------|------|
| Dictionary size (float) | `0x140645d70` | `0x48800000` = 262144.0 |
| Decompressor vtable | `0x140645d60` | vtable[0] = FUN_1402e3c40 |
| JSONAsset vtable | `0x1406447f8` | JSON 에셋 vtable |
| `"Failed to save JSONAsset"` | `0x140644820` | 에러 메시지 |
