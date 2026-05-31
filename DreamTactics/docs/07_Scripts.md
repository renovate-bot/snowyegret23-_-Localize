# 07. 유틸리티 Python 스크립트

분석/한글화에 사용할 수 있는 Python 스크립트 모음.

---

## 1. 해시 계산기

```python
def dream_hash(s: str) -> int:
    """Dream Tactics 에셋 경로 해시 계산 (Case-Insensitive DJB2)."""
    hash_val = 0x1505
    for c in s:
        byte = ord(c)
        if 0x41 <= byte <= 0x5A:  # A-Z → a-z
            byte = byte + 0x20
        hash_val = ((hash_val * 0x21) + byte) & 0xFFFFFFFF
    return 0 if hash_val == 0x1505 else hash_val


# 테스트
if __name__ == "__main__":
    print(dream_hash("tutorials/all/controls.texture"))    # 1335634838
    print(dream_hash("tutorials/english/actmenu.texture")) # 3881935904
    print(dream_hash("locale/english.json"))               # 515357558
    print(dream_hash("locale/japanese.json"))              # 2946173491
    print(dream_hash("locale/chinese.json"))               # 3584817163
```

---

## 2. data/0 인덱스 파일 덤프

```python
import struct
import json


def parse_index_file(filepath: str):
    """data/0 인덱스 파일 파싱."""
    with open(filepath, "rb") as f:
        data = f.read()

    entry_count = struct.unpack("<I", data[0:4])[0]
    entries = []

    for i in range(entry_count):
        offset = 4 + (i * 12)
        file_hash, asset_type, path_hash = struct.unpack(
            "<III", data[offset : offset + 12]
        )
        entries.append({
            "index": i,
            "file_hash": file_hash,
            "asset_type": asset_type,
            "path_hash": path_hash,
            "data_path": f"data/{file_hash}",
        })

    return entry_count, entries


def dump_full_index(index_path: str, output_path: str):
    """data/0 인덱스 파일을 JSON으로 덤프."""
    count, entries = parse_index_file(index_path)

    by_type = {}
    for e in entries:
        at = str(e["asset_type"])
        by_type.setdefault(at, []).append(e["file_hash"])

    result = {
        "entry_count": count,
        "entries": entries,
        "by_type": by_type,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return result


if __name__ == "__main__":
    dump_full_index("./data/0", "./asset_index.json")
```

---

## 3. LZHAM 압축/해제

```python
import struct
from lzham import LZHAMDecompressor, compress

DICT_SIZE_LOG2 = 18


def unpack_memory(file_path: str) -> bytes:
    """data/<hash> 파일을 압축 해제하여 JSON UTF-8 바이트를 반환."""
    with open(file_path, "rb") as f:
        data = f.read()

    dec = LZHAMDecompressor(filters={"dict_size_log2": DICT_SIZE_LOG2})
    result = dec.decompress(data, 1_000_000)  # 충분히 큰 크기

    json_size = struct.unpack("<I", result[:4])[0]
    return result[4 : 4 + json_size]


def pack_memory(json_data: bytes) -> bytes:
    """JSON UTF-8 바이트를 LZHAM 포맷으로 재압축."""
    payload = struct.pack("<I", len(json_data)) + json_data
    return compress(payload, filters={"dict_size_log2": DICT_SIZE_LOG2})
```

---

## 4. 로케일 파일 덤프 (JSON으로)

```python
import os
import struct
from lzham import LZHAMDecompressor


def dump_locale_files(data_folder: str, output_folder: str):
    """로케일 파일들을 압축 해제하여 JSON으로 저장."""
    locale_files = {
        "english": 515357558,
        "japanese": 2946173491,
        "chinese": 3584817163,
    }

    os.makedirs(output_folder, exist_ok=True)

    for lang, hash_val in locale_files.items():
        src = os.path.join(data_folder, str(hash_val))
        dst = os.path.join(output_folder, f"locale_{lang}.json")

        if not os.path.exists(src):
            print(f"{lang}: source missing")
            continue

        with open(src, "rb") as f:
            data = f.read()

        dec = LZHAMDecompressor(filters={"dict_size_log2": 18})
        result = dec.decompress(data, 1_000_000)

        json_size = struct.unpack("<I", result[:4])[0]
        json_data = result[4 : 4 + json_size]

        with open(dst, "wb") as f:
            f.write(json_data)

        print(f"{lang}: {json_size} bytes → {dst}")


if __name__ == "__main__":
    dump_locale_files(r"C:\GOG Games\Dream Tactics\data", "./locale_dump")
```

---

## 5. Type별 파일 분석

```python
import os
import struct


def analyze_type(data_folder: str, index_entries: list, type_id: int):
    """특정 Type의 파일들을 크기/헤더별로 분석."""
    files = [e for e in index_entries if e["asset_type"] == type_id]

    print(f"Type {type_id}: {len(files)}개 파일")
    print("-" * 60)

    sizes = []
    headers = {}

    for entry in files:
        filepath = os.path.join(data_folder, str(entry["file_hash"]))
        if not os.path.exists(filepath):
            continue
        size = os.path.getsize(filepath)
        sizes.append(size)

        with open(filepath, "rb") as f:
            header = f.read(4)
        h_hex = header.hex()
        headers[h_hex] = headers.get(h_hex, 0) + 1

    if sizes:
        print(f"크기 범위: {min(sizes)} ~ {max(sizes)} bytes")
        print(f"평균 크기: {sum(sizes) / len(sizes):.0f} bytes")
        print("헤더 분포:")
        for h, cnt in sorted(headers.items(), key=lambda x: -x[1])[:5]:
            print(f"  {h}: {cnt}개")
```

---

## 6. Type별 파일 헤더 스캔

```python
import os


def scan_type_headers(data_folder: str, index_entries: list, type_id: int, count: int = 5):
    """특정 Type의 파일 헤더 분석."""
    files = [e for e in index_entries if e["asset_type"] == type_id]
    print(f"Type {type_id}: {len(files)}개 파일")

    for entry in files[:count]:
        filepath = os.path.join(data_folder, str(entry["file_hash"]))
        if not os.path.exists(filepath):
            continue
        with open(filepath, "rb") as f:
            header = f.read(16)
        size = os.path.getsize(filepath)
        hex_str = header.hex()
        ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in header)
        print(
            f"  {entry['file_hash']:>12} | {size:>10} bytes | "
            f"{hex_str} | {ascii_str}"
        )
```

---

## 7. VMA ↔ 파일 오프셋 변환 (Dream.exe)

```python
# .rdata 섹션 기준 (대부분의 문자열이 여기 있음)

IMAGE_BASE = 0x140000000
RDATA_VMA = 0x1405b7000
RDATA_FILE_OFFSET = 0x5b6400


def file_to_vma(file_offset: int) -> int | None:
    if file_offset >= RDATA_FILE_OFFSET:
        return file_offset - RDATA_FILE_OFFSET + RDATA_VMA
    return None


def vma_to_file(vma: int) -> int | None:
    if vma >= RDATA_VMA:
        return vma - RDATA_VMA + RDATA_FILE_OFFSET
    return None
```

---

## 8. 경로 → 해시 역산 시도

```python
def try_reverse_path_hash(entries: list, candidate_paths: list):
    """path_hash를 알려진 경로명으로 역산 시도."""
    path_to_hash = {p: dream_hash(p) for p in candidate_paths}
    hash_to_path = {v: k for k, v in path_to_hash.items()}

    matched = []
    for e in entries:
        ph = e["path_hash"]
        if ph in hash_to_path:
            matched.append({
                "file_hash": e["file_hash"],
                "asset_type": e["asset_type"],
                "path_hash": ph,
                "matched_path": hash_to_path[ph],
            })
    return matched


# 사용 예시
candidates = [
    "locale/english.json",
    "locale/japanese.json",
    "locale/chinese.json",
    "tutorials/all/controls.texture",
    # ...
]
_, entries = parse_index_file("data/0")
matches = try_reverse_path_hash(entries, candidates)
for m in matches:
    print(m)
```

---

## 9. 한글화 검증

```python
import json
import struct
from lzham import LZHAMDecompressor


def verify_patched_locale(file_path: str, expected_lang: str = "KO"):
    """패치된 로케일 파일에서 한글이 포함되어 있는지 검증."""
    with open(file_path, "rb") as f:
        data = f.read()

    dec = LZHAMDecompressor(filters={"dict_size_log2": 18})
    result = dec.decompress(data, 1_000_000)
    json_size = struct.unpack("<I", result[:4])[0]
    json_data = result[4 : 4 + json_size]

    entries = json.loads(json_data)

    has_korean = False
    korean_count = 0
    for item in entries:
        text = item.get("Text", "") if isinstance(item, dict) else ""
        for c in text:
            if 0xAC00 <= ord(c) <= 0xD7A3:  # 한글 음절 범위
                has_korean = True
                korean_count += 1
                break

    print(f"{file_path}: {len(entries)} entries, 한글 포함 {korean_count}개")
    return has_korean
```

---

## 10. 전체 데이터 폴더 통계

```python
import os
import struct


def analyze_data_folder(data_folder: str):
    """data/ 폴더 전체 통계."""
    files = [f for f in os.listdir(data_folder) if f.isdigit() or f == "0"]

    total_size = 0
    size_ranges = {
        ">5MB": 0,
        "1-5MB": 0,
        "100KB-1MB": 0,
        "10-100KB": 0,
        "<10KB": 0,
    }

    for f in files:
        path = os.path.join(data_folder, f)
        size = os.path.getsize(path)
        total_size += size
        if size > 5 * 1024 * 1024:
            size_ranges[">5MB"] += 1
        elif size > 1 * 1024 * 1024:
            size_ranges["1-5MB"] += 1
        elif size > 100 * 1024:
            size_ranges["100KB-1MB"] += 1
        elif size > 10 * 1024:
            size_ranges["10-100KB"] += 1
        else:
            size_ranges["<10KB"] += 1

    print(f"총 파일 수: {len(files)}")
    print(f"총 용량: {total_size / (1024 * 1024):.2f} MB")
    print("크기 분포:")
    for k, v in size_ranges.items():
        print(f"  {k}: {v}개")
```
