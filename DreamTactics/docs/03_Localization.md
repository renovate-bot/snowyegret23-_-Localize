# 03. 로컬라이제이션 시스템

## 1. 지원 언어 목록

| 인덱스 | 언어 코드 | 문자열 VMA | 파일 오프셋 |
|--------|-----------|------------|-------------|
| 0 | `english` | `0x1405c1050` | `0x5c0450` |
| 1 | `japanese` | `0x1405c1058` | `0x5c0458` |
| 2 | `chinese` | `0x1405c1068` | `0x5c0468` |
| ? | `korean` | **없음** | - |

### 메모리 레이아웃
```
0x1405c1050: 65 6e 67 6c 69 73 68 00  "english\0"
0x1405c1058: 6a 61 70 61 6e 65 73 65  "japanese"
0x1405c1060: 00 00 00 00 00 00 00 00  "\0" + padding
0x1405c1068: 63 68 69 6e 65 73 65 00  "chinese\0"
```

---

## 2. 언어 테이블 구조

- **시작 주소**: `0x1407e0498`
- **끝 주소**: `0x1407e04c8`
- **전체 크기**: 48바이트 (0x30)
- **엔트리당 크기**: 16바이트
- **총 언어 수**: 3개

### Hex Dump
```
1407e0498: 00 00 00 00 00 00 00 00  50 10 5c 40 01 00 00 00
1407e04a8: 01 00 00 00 00 00 00 00  58 10 5c 40 01 00 00 00
1407e04b8: 02 00 00 00 00 00 00 00  68 10 5c 40 01 00 00 00
```

### 엔트리 구조 (16바이트)
```c
struct LanguageEntry {
    uint32_t index;      // +0x00: 언어 인덱스 (0, 1, 2)
    uint32_t padding;    // +0x04: 패딩
    char*    name_ptr;   // +0x08: 언어 이름 문자열 포인터
};
```

### 구조
```
오프셋 0x00 (0x1407e0498): [index=0, pad=0, ptr→"english"]
오프셋 0x10 (0x1407e04a8): [index=1, pad=0, ptr→"japanese"]
오프셋 0x20 (0x1407e04b8): [index=2, pad=0, ptr→"chinese"]
```

---

## 3. 언어 설정 저장 (options.json)

```json
{
    "gameSettings": {
        "language": 0,        // 0=english, 1=japanese, 2=chinese
        "usePixelFont": true
    }
}
```

---

## 4. 텍스트 ID 시스템

게임 텍스트는 LocaleId 기반으로 관리됨:

| 필드명 | VMA | 용도 |
|--------|-----|------|
| `titleLocaleId` | `0x1405bf288` | 제목용 로케일 ID |
| `textLocaleId` | `0x1405bf298` | 본문용 로케일 ID |
| `LocaleId` | `0x1405bf28d` | 일반 로케일 ID |

### 로케일 파싱 함수: FUN_1401a5780

**주소**: `0x1401a5780`
**역할**: JSON 파싱하여 titleLocaleId/textLocaleId 추출

```c
void FUN_1401a5780(longlong param_1, longlong* param_2)
{
    // vtable 호출로 JSON/데이터 파싱
    (**(code**)(*param_2 + 0x120))(param_2, "titleLocaleId", param_1 + 4);
    (**(code**)(*param_2 + 0x120))(param_2, "textLocaleId", param_1 + 8);
}
```

---

## 5. 언어별 리소스 경로 패턴

### 튜토리얼 이미지 (언어별)
```
tutorials/%s/actmenu.texture      // %s = english/japanese/chinese
tutorials/%s/wait.texture
tutorials/%s/help.texture
tutorials/%s/equip.texture
tutorials/%s/equipmenu.texture
tutorials/%s/deck1.texture
tutorials/%s/deck2.texture
tutorials/%s/trade1.texture
tutorials/%s/damagetypes.texture
tutorials/%s/defres.texture
tutorials/%s/levelup.texture
tutorials/%s/saving.texture
```

### 로케일 파일
```
locale/%s.json    // %s = english/japanese/chinese
```

### 공용 (언어 무관)
```
tutorials/all/controls.texture
tutorials/all/attack.texture
tutorials/all/formation.texture
tutorials/all/hand.texture
tutorials/all/mana.texture
```

---

## 6. 로케일 파일 (★핵심)

### 발견된 로케일 파일

| 에셋 경로 | 해시값 (파일명) | 파일 크기 | 압축 해제 후 |
|-----------|-----------------|-----------|--------------|
| `locale/english.json` | **515357558** | 32,615 bytes | 156,113 bytes |
| `locale/japanese.json` | **2946173491** | 35,475 bytes | ~160,000 bytes |
| `locale/chinese.json` | **3584817163** | 34,598 bytes | 155,434 bytes |

### 파일 구조 (압축됨)
파일 자체는 LZHAM 압축 → 자세한 내용은 [04_Compression.md](04_Compression.md)

### 압축 해제 후 구조
```
[4바이트: uint32 JSON 크기 (little-endian)] [JSON UTF-8 데이터]
```

### JSON 포맷 (UI 로케일)
```json
[
    {"LocaleId": "Biomes_AshguardName", "Text": "EMPIRE OF ASHGUARD"},
    {"LocaleId": "Biomes_CavesName", "Text": "CRYSTAL CAVES"},
    {"LocaleId": "Biomes_CoralName", "Text": "CORAL OASIS"},
    {"LocaleId": "Biomes_CoreName", "Text": "CORE"},
    ...
]
```

### JSON 포맷 (본문 텍스트)
```json
[
    {"hash": 12345678, "lines": ["첫 번째 줄", "두 번째 줄"]},
    ...
]
```

---

## 7. 언어별 에셋 로딩 함수

### FUN_1401d02c0 - Language_LoadAssets ★

**주소**: `0x1401d02c0`
**역할**: 언어 테이블을 순회하며 각 언어별 에셋 로드

```c
// 정리된 Pseudo Code
void Language_LoadAssets(AssetArray* output, LanguageAssetManager* manager, char* path_pattern)
{
    char path_buffer[128];
    char resolved_path[128];

    strcpy(path_buffer, path_pattern);  // 예: "locale/%s.json"

    // 언어 테이블 순회
    LanguageEntry* lang = &g_LanguageTable[0];  // 0x1407e0498
    LanguageEntry* lang_end = &g_LanguageTable[3];  // 0x1407e04c8

    while (lang < lang_end) {
        char* lang_name = lang->name;  // "english", "japanese", "chinese"

        // 경로 생성
        if (strstr(path_buffer, "%s") != NULL) {
            sprintf(resolved_path, path_buffer, lang_name);
            // "locale/%s.json" → "locale/english.json"
        } else {
            strcpy(resolved_path, path_buffer);
        }

        // 해시 계산 (DJB2)
        uint hash = dream_hash(resolved_path);

        // 에셋 조회 및 로드
        AssetInfo info;
        if (AssetIndex_Lookup(hash, &info)) {
            AssetHandle handle;
            Asset_Load(manager, &handle, hash);
            output->items[lang->index] = handle;
        }

        lang++;  // 다음 언어
    }
}
```

---

## 8. 한글화 전략

### 방식: 기존 언어 덮어쓰기

**선택 가능 옵션**:
- 중국어(`locale/chinese.json`, data/3584817163)를 한국어로 덮어쓰기
- 일본어(`locale/japanese.json`, data/2946173491)를 한국어로 덮어쓰기
- **추천**: 두 언어 모두 덮어쓰기 → 사용자가 options.json에서 선택 가능

### 단계
1. LZHAM 압축 해제 (chinese/japanese.json)
2. JSON 파싱 → `LocaleId` 키별로 한글 매핑
3. Google Sheets 등에서 한글 번역본 작성
4. 원본 JSON의 `Text` 값을 한글로 교체
5. `[uint32 크기][JSON]` 페이로드로 재구성
6. LZHAM 재압축
7. `data/<hash>` 파일로 저장
8. 게임 `options.json`에서 `language: 1` (일본어) 또는 `2` (중국어) 선택

### 폰트 교체
- 기존 중국어/일본어 폰트 슬롯 (해시)을 한글 폰트 TTF로 교체
- `FONT_PIXEL_JA` = `1508373377`
- `FONT_PIXEL_CN` = `2256482679`
- `FONT_NORMAL_CN` = `2973124184`
- `options.json`의 `usePixelFont` 설정에 따라 픽셀/일반 폰트 분기
