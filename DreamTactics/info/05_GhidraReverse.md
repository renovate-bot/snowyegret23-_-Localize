# 05. Ghidra 리버스 엔지니어링 결과

## 1. 주요 함수 주소 총정리

### 에셋/파일 시스템
| 함수 | 주소 | 역할 |
|------|------|------|
| `AssetLoader_LoadByHash` | `0x1402a2150` | 해시 → 경로 변환 + 로딩 |
| `FileSystem_OpenFile` | `0x1402b6880` | 파일 열기 래퍼 |
| `FileSystem_fopen` | `0x14027bef0` | 실제 fopen |
| `AssetIndex_LoadFromFile` | `0x1402a1ea0` | **data/0 파싱** ★ |
| `AssetIndex_Lookup` | `0x1402a20b0` | 에셋 인덱스 조회 |
| `Asset_Load` | `0x14027fcc0` | 에셋 로드 메인 |
| `AssetCache_GetOrCreate` | `0x140266580` | 캐시 관리 |
| `AssetFactory_Create` | `0x1402a1870` | **타입별 Factory** ★ |
| `Asset_GetHash` | `0x14028b400` | 해시값 읽기 (오프셋 +0x1c) |
| `Asset_ParseWithHash` | `0x1402a0a00` | 에셋 파싱 (assetHash 사용) |

### 타입별 로더 (FUN_1402a1870에서 호출)
| Type | 함수 | 주소 | 객체 크기 |
|------|------|------|----------|
| 0 (Audio) | `OggAsset_Constructor` | `0x14028dea0` | 0x30 |
| 1 | `Type1Asset_Constructor` | `0x1402a4a00` | 0x30 |
| 2 (JSON) ★ | `JSONAsset_Constructor` | `0x14029a950` | 0x30 |
| 3 | `Type3Asset_Constructor` | `0x1402b1dd0` | 0xB8 |
| 4 | `Type4Asset_Constructor` | `0x1402e1190` | 0x30 |
| 5 | `Type5Asset_Constructor` | `0x1402de7e0` | 0x30 |
| 6 | `Type6Asset_Constructor` | `0x1402b1c50` | 0x30 |
| 7 (Atlas) | `AtlasAsset_Constructor` | `0x14029c220` | 0x30 |
| 8 | `Type8Asset_Constructor` | `0x140280410` | 0x30 |
| 10 (Texture) | `TextureAsset_Constructor` | `0x140296960` | 0x30 |
| 11 | `Type11Asset_Constructor` | `0x14028b570` | 0x60 |
| 12 (Font?) | `FontAsset_Constructor` | `0x14029fab0` | 0x30 |
| 13 | `Type13Asset_Constructor` | `0x14028dd70` | 0x30 |
| 14 (Sprite) | `SpriteAsset_Constructor` | `0x14029c5d0` | 0x30 |

### 로컬라이제이션
| 함수 | 주소 | 역할 |
|------|------|------|
| `Language_LoadAssets` | `0x1401d02c0` | 언어별 에셋 로딩 ★ |
| `Locale_ParseIds` | `0x1401a5780` | 로케일 ID 파싱 |
| `Locale_Load` | `0x140247850` | 로케일 로더 |

### JSON/LZHAM 압축
| 함수 | 주소 | 역할 |
|------|------|------|
| `JSONFile_Load` | `0x1402dea50` | JSON 파일 로드 (압축 해제 + 파싱) |
| `Decompressor_Init` | `0x1402e3a10` | 압축 해제기 초기화 |
| `Decompressor_GetOutputSize` | `0x1402b5d20` | uncompressed size 읽기 |
| `Decompressor_Decompress` | `0x1402e3c40` | 스트리밍 압축 해제 |
| `Decompressor_Cleanup` | `0x1402e3b60` | 정리 |
| `JSON_Parse` | `0x14028f610` | JSON 파싱 |
| LZHAM `lzham_decompress_init` | `0x14035acc0` | 디코더 초기화 |
| LZHAM `lzham_decompress_reinit` | `0x14035af70` | 디코더 재초기화 |
| LZHAM `lzham_decompress` (thunk) | `0x14035abb0` | 압축 해제 엔트리 |
| LZHAM decompress core | `0x1403537e0` | 실제 압축 해제 코어 |

### 유틸리티
| 함수 | 주소 | 역할 |
|------|------|------|
| `sprintf_wrapper` | `0x14001a7a0` | sprintf 래퍼 |
| `log2_wrapper` | `0x14054b058` | log2 함수 |
| `Stream_ReadUInt32` | `0x1402b5d20` | uint32 읽기 |
| `Stream_ReadUInt32_2` | `0x1402b5bb0` | uint32 읽기 (다른 버전) |

---

## 2. 주요 데이터/문자열 주소

### 에셋 시스템
| 항목 | 주소 | 크기 | 설명 |
|------|------|------|------|
| `"data/%u"` 포맷 | `0x140644a18` | 8B | 해시→경로 변환용 |
| `"data/0"` | `0x140644a10` | 7B | 인덱스 파일 경로 |
| `"assetHash"` | `0x1406449d8` | 10B | JSON 파싱 키 |
| 해시 룩업 테이블 | `0x1407e35c0` | 256B | 대소문자 변환 |
| 전역 에셋 인덱스 포인터 | `0x1408b4888` | 8B | 해시 테이블 |
| 에셋 인덱스 버킷 수 | `0x1408b4890` | 4B | |
| 인덱스 뮤텍스 | `0x1408b48b0` | - | 스레드 동기화 |
| 에셋 캐시 포인터 | `0x1408b46c8` | 8B | 캐시 해시 테이블 |
| 캐시 버킷 수 | `0x1408b46d0` | 4B | |
| 캐시 뮤텍스 | `0x1408b46b8` | - | |

### 로컬라이제이션
| 항목 | 주소 | 설명 |
|------|------|------|
| `"english"` | `0x1405c1050` | 언어 코드 |
| `"japanese"` | `0x1405c1058` | 언어 코드 |
| `"chinese"` | `0x1405c1068` | 언어 코드 |
| `"titleLocaleId"` | `0x1405bf288` | 로케일 JSON 키 |
| `"textLocaleId"` | `0x1405bf298` | 로케일 JSON 키 |
| `"LocaleId"` | `0x1405bf28d` | 일반 로케일 ID |
| 언어 테이블 시작 | `0x1407e0498` | 3개 언어 엔트리 |
| 언어 테이블 끝 | `0x1407e04c8` | 루프 종료 조건 |
| 플레이스홀더 패턴 | `0x1405c05f4` | "%s" 등 |

### JSON / LZHAM
| 항목 | 주소 | 설명 |
|------|------|------|
| JSONAsset vtable | `0x1406447f8` | Type 2 vtable |
| Decompressor vtable | `0x140645d60` | |
| Dictionary size (float) | `0x140645d70` | `0x48800000` = 262144.0 |
| `"Failed to save JSONAsset"` | `0x140644820` | 에러 메시지 |
| LZHAM 경로 문자열 | `0x140661d90` | `D:\spectra\avarice\external\lzham\...` |
| `"lzham_malloc: size too big"` | `0x140661dc8` | 에러 |
| `"lzham_malloc: out of memory"` | `0x140661de8` | 에러 |
| `"lzham::vector operator=..."` | `0x140661fc8` | 에러 |

---

## 3. 주요 함수 디컴파일 결과 (Pseudo Code)

### FUN_1402a2150 - 해시→파일경로 변환

**주소**: `0x1402a2150`

**원본**:
```c
void FUN_1402a2150(uint param_1, longlong param_2, undefined8 param_3, undefined8 param_4)
{
    undefined1 auStack_78[32];
    char local_58[64];
    ulonglong local_18;

    local_18 = DAT_1407f37e8 ^ (ulonglong)auStack_78;
    FUN_14001a7a0(local_58, "data/%u", (ulonglong)param_1, param_4);
    FUN_1402b6880(param_2, local_58);
    __security_check_cookie(local_18 ^ (ulonglong)auStack_78);
    return;
}
```

**정리**:
```c
void AssetLoader_LoadByHash(uint hash, void* output_struct)
{
    char path_buffer[64];
    sprintf(path_buffer, "data/%u", hash);
    FileSystem_OpenFile(output_struct, path_buffer);
}
```

---

### FUN_1402b6880 - 파일 열기 래퍼

**주소**: `0x1402b6880`

```c
void FileSystem_OpenFile(void* file_struct, char* path)
{
    FileSystem_fopen(file_struct + 0x10, path, "rb");
}
```

---

### FUN_1402a1ea0 - data/0 인덱스 파싱 ★

**주소**: `0x1402a1ea0`

**정리된 의사코드**:
```c
bool AssetIndex_LoadFromFile(AssetIndexManager* manager)
{
    FileHandle file;

    // 1. data/0 파일 열기
    if (!FileSystem_OpenFile(&file, "data/0")) return false;

    // 2. 엔트리 개수 읽기 (첫 4바이트)
    uint entry_count = FileSystem_ReadUInt32(&file);

    // 3. 전체 엔트리 데이터 할당 (12바이트 × 개수)
    char* entry_data = malloc(entry_count * 12);
    FileSystem_Read(&file, entry_data, entry_count * 12);

    // 4. 각 엔트리를 해시 테이블에 등록
    for (uint i = 0; i < entry_count; i++) {
        uint file_hash  = ReadUInt32(entry_data + i*12 + 0);
        uint asset_type = ReadUInt32(entry_data + i*12 + 4);
        uint path_hash  = ReadUInt32(entry_data + i*12 + 8);

        uint bucket = file_hash % manager->bucket_count;
        if (HashTable_Find(manager, file_hash)) continue;

        AssetEntry* entry = Pool_Alloc(manager->pool, 0x18);
        entry->file_hash = file_hash;
        entry->asset_type = asset_type;
        entry->path_hash = path_hash;
        HashTable_Insert(manager, bucket, entry);
    }

    free(entry_data);
    return true;
}
```

---

### FUN_1402a20b0 - 에셋 조회

**주소**: `0x1402a20b0`

```c
bool AssetIndex_Lookup(uint file_hash, AssetInfo* out_info)
{
    Mutex_Lock(&g_AssetIndexMutex);

    uint bucket = file_hash % g_AssetIndex.bucket_count;
    AssetEntry* entry = g_AssetIndex.buckets[bucket];

    while (entry != NULL) {
        if (entry->file_hash == file_hash) {
            if (out_info != NULL) {
                out_info->file_hash = entry->file_hash;
                out_info->asset_type = entry->asset_type;
                out_info->path_hash = entry->path_hash;
            }
            Mutex_Unlock(&g_AssetIndexMutex);
            return true;
        }
        entry = entry->next;
    }

    Mutex_Unlock(&g_AssetIndexMutex);
    return false;
}
```

---

### FUN_1402a1870 - 에셋 타입별 Factory ★

**주소**: `0x1402a1870`

```c
undefined8* AssetFactory_Create(uint* asset_info)
{
    switch(asset_info[1]) {  // asset_type
    case 0:  obj = operator_new(0x30); return FUN_14028dea0(obj, asset_info);  // Ogg Audio
    case 1:  obj = operator_new(0x30); return FUN_1402a4a00(obj, asset_info);
    case 2:  obj = operator_new(0x30); return FUN_14029a950(obj, asset_info);  // JSON
    case 3:  obj = operator_new(0xB8); return FUN_1402b1dd0(obj, asset_info);
    case 4:  obj = operator_new(0x30); return FUN_1402e1190(obj, asset_info);
    case 5:  obj = operator_new(0x30); return FUN_1402de7e0(obj, asset_info);
    case 6:  obj = operator_new(0x30); return FUN_1402b1c50(obj, asset_info);
    case 7:  obj = operator_new(0x30); return FUN_14029c220(obj, asset_info);  // Atlas
    case 8:  obj = operator_new(0x30); return FUN_140280410(obj, asset_info);
    case 10: obj = operator_new(0x30); return FUN_140296960(obj, asset_info);  // Texture
    case 11: obj = operator_new(0x60); return FUN_14028b570(obj, asset_info);
    case 12: obj = operator_new(0x30); return FUN_14029fab0(obj, asset_info);  // Font?
    case 13: obj = operator_new(0x30); return FUN_14028dd70(obj, asset_info);
    case 14: obj = operator_new(0x30); return FUN_14029c5d0(obj, asset_info);  // Sprite
    }
    return NULL;
}
```

---

### FUN_14029a950 - JSONAsset 생성자 (Type 2)

**주소**: `0x14029a950`

```c
undefined8* JSONAsset_Constructor(undefined8* this, undefined4* asset_info)
{
    FUN_14028b320(this, asset_info);      // 부모 생성자
    *this = &PTR_FUN_1406447f8;           // JSONAsset vtable 설정
    return this;
}
```

### JSONAsset vtable (`0x1406447f8`)
```
1406447f8: 80 a9 29 40 01 00 00 00  → FUN_14029a980 (메서드 1)
140644800: a0 b6 29 40 01 00 00 00  → FUN_14029b6a0 (메서드 2 - 로더)
140644808: 70 b7 29 40 01 00 00 00  → FUN_14029b770 (메서드 3)
140644810: 50 b4 28 40 01 00 00 00  → FUN_14028b450 (메서드 4)
140644818: b0 c1 29 40 01 00 00 00  → FUN_14029c1b0 (메서드 5)
140644820: "Failed to save JSONAsset"      ← 에러 메시지
```

---

### FUN_14029b6a0 - JSONAsset Load (메서드 2)

**주소**: `0x14029b6a0`

```c
void FUN_14029b6a0(longlong param_1, undefined8 param_2, ...)
{
    // JSON 파서 객체(0x60) 할당 및 초기화
    puVar1 = operator_new(0x60);
    puVar1[9] = 0x400;  // buffer size

    if (puVar1[2] == 0) {
        puVar2 = operator_new(0x28);  // 내부 구조체
        puVar2[1] = 0x10000;
        puVar1[2] = puVar2;
        puVar1[3] = puVar2;
    }

    *(undefined8**)(param_1 + 0x28) = puVar1;
    FUN_1402dea50(param_2, puVar1, ...);  // ★ 압축 해제 + JSON 파싱
}
```

---

### FUN_1402dea50 - JSON 파일 로드 ★

**주소**: `0x1402dea50`

```c
bool JSONFile_Load(FileHandle* file, JSONDocument* out_doc)
{
    Decompressor decompressor;

    Decompressor_Init(&decompressor, file);                         // 0x1402e3a10
    uint decompressed_size = Decompressor_GetOutputSize(&decompressor); // 0x1402b5d20
    char* buffer = malloc(decompressed_size);
    Decompressor_Decompress(&decompressor, buffer, decompressed_size);  // 0x1402e3c40
    JSON_Parse(out_doc, buffer, decompressed_size);                 // 0x14028f610
    Decompressor_Cleanup(&decompressor);                            // 0x1402e3b60
    return out_doc->error == 0;
}
```

---

### FUN_1402e3a10 - Decompressor 초기화 ★ (LZHAM 파라미터)

**주소**: `0x1402e3a10`

```c
Decompressor* Decompressor_Init(Decompressor* this, FileHandle* input_stream)
{
    Stream_Init(&this->base);
    this->vtable = &Decompressor_VTable;  // 0x140645d60
    this->input_stream = input_stream;
    this->output_buffer = NULL;
    this->output_size = 0;
    this->error = false;

    // LZHAM 파라미터 구조체 (lzham_decompress_params)
    int params[10] = {0};
    params[0] = 0x28;   // struct_size = 40
    float fVar = DAT_140645d70;        // 262144.0
    params[1] = (int)log2f(fVar);      // dict_size_log2 = 18
    // params[2~9] = 0 (모두 기본값)

    this->context = lzham_decompress_init(params);  // 0x14035acc0

    this->input_buffer = malloc(0x100000);   // 1MB
    this->output_buffer = malloc(0x100000);  // 1MB

    return this;
}
```

---

### FUN_14035acc0 - LZHAM 디코더 초기화 (SDK의 lzham_decompress_init)

**주소**: `0x14035acc0`

**파라미터 검증**:
- `param_1 != NULL`
- `*param_1 == 0x28` (struct_size)
- `param_1[1] - 0xf < 0xf` (dict_size_log2가 15~29 범위)
- `param_1[4] == 0` 또는 조건부 검증

---

### FUN_1401d02c0 - 언어별 에셋 로딩 ★

**주소**: `0x1401d02c0`

```c
void Language_LoadAssets(AssetArray* output, LanguageAssetManager* manager, char* path_pattern)
{
    char path_buffer[128];
    char resolved_path[128];
    strcpy(path_buffer, path_pattern);  // 예: "locale/%s.json"

    LanguageEntry* lang = &g_LanguageTable[0];  // 0x1407e0498
    LanguageEntry* lang_end = &g_LanguageTable[3];  // 0x1407e04c8

    while (lang < lang_end) {
        char* lang_name = lang->name;  // "english", "japanese", "chinese"

        if (strstr(path_buffer, "%s") != NULL) {
            sprintf(resolved_path, path_buffer, lang_name);
        } else {
            strcpy(resolved_path, path_buffer);
        }

        // DJB2 해시 계산 (룩업 테이블 사용)
        uint hash = 0x1505;
        for (char* p = resolved_path; *p; p++) {
            byte b = g_HashLookup[(unsigned char)*p];  // 0x1407e35c0
            hash = hash * 0x21 + b;
        }

        AssetInfo info;
        if (AssetIndex_Lookup(hash, &info)) {
            AssetHandle handle;
            Asset_Load(manager, &handle, hash);
            output->items[lang->index] = handle;
        }

        lang = (LanguageEntry*)((char*)lang + 16);  // 다음 엔트리
    }
}
```

---

## 4. Ghidra 분석 환경

### 필요 도구
- Ghidra 11.x
- GhidraMCP 플러그인
- Python 3.x

### 프로젝트 설정
1. Dream.exe 임포트
2. 자동 분석 실행
3. GhidraMCP 서버 시작

### 주요 북마크
```
0x1402a1870 - AssetFactory_Create (타입별 분기)
0x1402a1ea0 - AssetIndex_LoadFromFile (인덱스 파싱)
0x1401d02c0 - Language_LoadAssets (언어별 로딩)
0x1402dea50 - JSONFile_Load (JSON 로드)
0x1402e3a10 - Decompressor_Init (LZHAM 초기화)
0x14035acc0 - lzham_decompress_init
0x1407e0498 - 언어 테이블
0x1407e35c0 - 해시 룩업 테이블
0x140645d70 - Dictionary size (262144.0)
```

### 유용한 GhidraMCP 명령어
```
GhidrAssistMCP:xrefs_to         - 특정 주소를 참조하는 곳
GhidrAssistMCP:xrefs_from       - 특정 주소에서 참조하는 곳
GhidrAssistMCP:function_xrefs   - 함수 호출 관계
GhidrAssistMCP:decompile_function - 함수 디컴파일
GhidrAssistMCP:get_hexdump      - 메모리 헥스 덤프
```

### strings 명령어로 문자열 검색
```bash
strings Dream.exe | grep -iE "locale|language|korean|text"
strings Dream.exe | grep -iE "data/|\.json|font"
strings Dream.exe | grep -iE "lzham|lzma|compress"
```
