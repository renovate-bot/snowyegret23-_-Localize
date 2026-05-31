# 02. 데이터 파일 포맷

## 1. 해시 알고리즘 (Case-Insensitive DJB2)

에셋 경로(문자열) → `data/` 폴더의 해시 파일명 변환.

### 알고리즘
- **초기값**: `0x1505` (5381)
- **승수**: `0x21` (33)
- **특징**: 대소문자 무시 (A-Z → a-z 변환)
- **룩업 테이블**: `0x1407e35c0` (256바이트, 0x41-0x5A → 0x61-0x7A 매핑)

### Python 구현
```python
def dream_hash(s: str) -> int:
    """Dream Tactics 에셋 경로 해시 계산"""
    hash_val = 0x1505
    for c in s:
        byte = ord(c)
        if 0x41 <= byte <= 0x5A:  # A-Z → a-z
            byte = byte + 0x20
        hash_val = ((hash_val * 0x21) + byte) & 0xFFFFFFFF
    return 0 if hash_val == 0x1505 else hash_val
```

### 검증된 해시 매핑
| 에셋 경로 | 해시값 | 파일 크기 |
|-----------|--------|-----------|
| `tutorials/all/controls.texture` | 1335634838 | 8.41 KB |
| `tutorials/english/actmenu.texture` | 3881935904 | 7.04 KB |
| `locale/english.json` | **515357558** | 32 KB |
| `locale/japanese.json` | **2946173491** | 35 KB |
| `locale/chinese.json` | **3584817163** | 34 KB |

---

## 2. 데이터 파일 시스템 개요

### 구조
```
data/
├── 0                    # 에셋 인덱스 (★)
├── 123456789            # 해시값 파일들
├── 2847193056
└── ... (총 약 2,710개)
```

### 통계
- **총 파일 수**: 2,710개
- **총 용량**: 170.45 MB
- **파일명 형식**: unsigned int (10진수 해시값)
- **접근 패턴**: `sprintf(path, "data/%u", hash)`

### 파일 크기 분포
| 크기 범위 | 추정 용도 |
|-----------|-----------|
| 5+ MB | 폰트 파일 (TTF/OTF) |
| 1-5 MB | 대형 텍스처, 스프라이트시트 |
| 100KB-1MB | 일반 텍스처, 오디오 |
| 10-100KB | 소형 텍스처, 데이터 파일 |
| <10KB | 설정, 스크립트, 텍스트 데이터 |

### 가장 큰 파일 TOP 10 (폰트 후보)
| 해시 | 크기 | 추정 |
|------|------|------|
| 2973124184 | 5.37 MB | **폰트 (Pretendard 라이선스와 함께 사용?)** |
| 3539440304 | 5.06 MB | **폰트 (Noto?)** |
| 3289686418 | 4.57 MB | 폰트 또는 대형 텍스처 |
| 1610796509 | 4.49 MB | 폰트 또는 대형 텍스처 |
| 2725568895 | 4.44 MB | 폰트 또는 대형 텍스처 |
| 2380936049 | 4.24 MB | 대형 텍스처 |
| 4053433150 | 4.19 MB | 대형 텍스처 |
| 1470249670 | 4.14 MB | 대형 텍스처 |
| 1011414592 | 4.10 MB | 대형 텍스처 |
| 4025299062 | 4.09 MB | 대형 텍스처 |

---

## 3. data/0 인덱스 파일 구조 (완전 해독)

### 기본 정보
| 항목 | 값 |
|------|-----|
| **파일 경로** | `data/0` |
| **파일 크기** | 32,500 바이트 |
| **역할** | 에셋 인덱스 테이블 |
| **엔트리 수** | 2,708개 |

### 바이너리 구조
```
┌─────────────────────────────────────────────────────────┐
│ 오프셋 0x00: uint32 entry_count (2708)                  │
├─────────────────────────────────────────────────────────┤
│ 오프셋 0x04: Entry[0]  (12 bytes)                       │
│ 오프셋 0x10: Entry[1]  (12 bytes)                       │
│ 오프셋 0x1C: Entry[2]  (12 bytes)                       │
│ ...                                                     │
│ 오프셋 0x7EF0: Entry[2707] (12 bytes)                   │
└─────────────────────────────────────────────────────────┘

총 크기: 4 + (2708 × 12) = 32,500 bytes ✓
```

### 엔트리 구조 (12 바이트)
```c
struct AssetIndexEntry {
    uint32_t file_hash;    // +0x00: data/ 폴더의 실제 파일명 (해시값)
    uint32_t asset_type;   // +0x04: 에셋 타입 ID (0~14)
    uint32_t path_hash;    // +0x08: 에셋 경로 해시
};
```

### 파싱 Python 코드
```python
import struct

def parse_index_file(filepath):
    """data/0 인덱스 파일 파싱"""
    with open(filepath, 'rb') as f:
        data = f.read()

    entry_count = struct.unpack('<I', data[0:4])[0]
    entries = []

    for i in range(entry_count):
        offset = 4 + (i * 12)
        file_hash, asset_type, path_hash = struct.unpack('<III', data[offset:offset+12])
        entries.append({
            'index': i,
            'file_hash': file_hash,
            'asset_type': asset_type,
            'path_hash': path_hash,
            'data_path': f'data/{file_hash}'
        })

    return entry_count, entries
```

---

## 4. 에셋 타입 분류 (asset_type 필드)

| Type ID | 개수 | 확인된 포맷 | 객체 크기 | 로더 함수 |
|---------|------|-------------|-----------|-----------|
| **0** | 482 | **Ogg Vorbis** (오디오) | 0x30 | `FUN_14028dea0` |
| **1** | 8 | 미확인 | 0x30 | `FUN_1402a4a00` |
| **2** | 174 | **JSON 에셋** ★ (로케일) | 0x30 | `FUN_14029a950` |
| **3** | 3 | 미확인 (큰 구조체) | 0xB8 | `FUN_1402b1dd0` |
| **4** | ? | 미확인 | 0x30 | `FUN_1402e1190` |
| **5** | 11 | 미확인 | 0x30 | `FUN_1402de7e0` |
| **6** | ? | 미확인 | 0x30 | `FUN_1402b1c50` |
| **7** | 188 | Atlas data | 0x30 | `FUN_14029c220` |
| **8** | 18 | Named data (CaveFog 등) | 0x30 | `FUN_140280410` |
| **10** | 904 | **Texture** (.texture) | 0x30 | `FUN_140296960` |
| **11 (0xB)** | 381 | 미확인 | 0x60 | `FUN_14028b570` |
| **12 (0xC)** | 132 | 폰트 (TTF 대용량) | 0x30 | `FUN_14029fab0` |
| **13 (0xD)** | 1 | 데이터 | 0x30 | `FUN_14028dd70` |
| **14 (0xE)** | 406 | Spritesheet | 0x30 | `FUN_14029c5d0` |

### Type별 파일 헤더 분석

| Type | 예시 파일 | 크기 | 헤더 (hex) | ASCII |
|------|-----------|------|------------|-------|
| 0 | 443505550 | 134KB | `8b0e02004f676753...` | `....OggS....` |
| 1 | 2620661067 | 6.5KB | `48bc3dc6c88c600a...` | `H.=...` |
| 2 | 3522210234 | 1.1KB | `4842a90e8221c007...` | `HB...!` |
| 7 | 2183017615 | 744B | `48428c584b706007...` | `HB.XKp` (atlas 포함) |
| 8 | 1025523235 | 3.3KB | `4ed5457e80a00021...` | `N.E~...!` (CaveFog 포함) |
| 10 | 3990459399 | 977B | `48be5bb000002009...` | `H.[...` |

**참고**: 대부분 파일이 `0x48` ('H')로 시작 → LZHAM 압축 헤더 or 커스텀 직렬화

### 검증된 매핑
| 에셋 경로 | file_hash | asset_type | path_hash |
|-----------|-----------|------------|-----------|
| `tutorials/all/controls.texture` | 1335634838 | 10 | 1835737995 |
| `tutorials/english/actmenu.texture` | 3881935904 | 10 | 2859562502 |
| `locale/english.json` | 515357558 | 2 | ? |
| `locale/japanese.json` | 2946173491 | 2 | ? |
| `locale/chinese.json` | 3584817163 | 2 | ? |

---

## 5. 에셋 로딩 함수 체인

```
에셋 요청 (해시 또는 경로)
    ↓
FUN_1401d02c0 (언어 해석, 해시 계산)
    ↓
FUN_1402a20b0 (인덱스 조회 - data/0에서)
    ↓
FUN_14027fcc0 (에셋 로드 메인)
    ↓
FUN_140266580 (캐시 조회/생성)
    ↓
FUN_1402a1870 (타입별 Factory)
    ↓
FUN_1402a2150 (해시 → 경로 변환)
    ↓
FUN_1402b6880 (파일 열기 래퍼)
    ↓
FUN_14027bef0 (실제 fopen)
    ↓
FUN_1402dea50 (JSON 로드: 압축 해제 + 파싱)
```

---

## 6. 파일 포맷 분석 결과

### Type 0 - Ogg Vorbis (오디오)
- **매직 넘버**: `OggS` (0x4F676753)
- 표준 Ogg Vorbis 포맷
- 별도 래퍼 없음

### Type 2 - JSON (로케일, 설정 등)
- **압축**: LZHAM (`dict_size_log2 = 18`)
- **페이로드**: `[uint32 size][JSON UTF-8]`
- 자세한 내용: [04_Compression.md](04_Compression.md)

### Type 10 - Texture
- **헤더**: `0x48...` 로 시작
- 커스텀 포맷 (LZHAM 압축 가능성)
- 추가 분석 필요

### 기타 Type
- 대부분 `0x48` (ASCII 'H')로 시작 → 대부분 LZHAM 압축
- 일부 파일에서 에셋 이름 문자열 발견 ("CaveFog", "atlas" 등)
- zlib/LZMA 아님 (표준 해제 실패)
