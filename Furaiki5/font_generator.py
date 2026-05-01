"""
사용법:
  python font_generator.py create <font.ttf> [output.nltx] [--name entry_name] [--charlist CharList.txt]
  python font_generator.py info <file.nltx>
  python font_generator.py extract <file.nltx> [output_dir]
  python font_generator.py validate <font.ttf> --charlist CharList_3911.txt

간편 사용:
  python font_generator.py <font.ttf> [output.nltx]
"""

import struct
import sys
import os
import argparse
import zlib
from collections import Counter


YKCMP_MAGIC = b"YKCMP_V1"


def ykcmp_decode_layer(data: bytes) -> bytes:
    """YKCMP_V1 단일 레이어 디코딩. 지원: Type 1 (RL), 2 (Slide), 3 (Huffman)"""
    if len(data) < 0x14 or data[:8] != YKCMP_MAGIC:
        raise ValueError("Not YKCMP_V1 data")

    type_val = data[8]  # 하위 바이트 = 압축 타입
    decomp_size = struct.unpack_from("<I", data, 0x10)[0]

    if type_val == 1:
        return _rl_decode(data, decomp_size)
    elif type_val == 2:
        return _slide_decode(data, decomp_size)
    elif type_val == 3:
        return _huffman_decode(data, decomp_size)
    elif type_val == 4:
        return _slide2_decode(data, decomp_size)
    elif type_val == 7:
        return zlib.decompress(data[0x14:])
    else:
        raise ValueError(f"Unsupported YKCMP type: {type_val}")


def ykcmp_decode(data: bytes) -> bytes:
    """다중 레이어 YKCMP 디코딩 (중첩 압축 처리)"""
    while len(data) >= 8 and data[:8] == YKCMP_MAGIC:
        data = ykcmp_decode_layer(data)
    return data


def _huffman_decode(data: bytes, decomp_size: int) -> bytes:
    """YKCMP Type 3: Huffman 디코딩"""
    total_bits = struct.unpack_from("<I", data, 0x0C)[0]
    flag_byte = data[9]

    # 주파수 테이블 (256 * uint32 = 1024 bytes, offset 0x14)
    freq = []
    for i in range(256):
        freq.append(struct.unpack_from("<I", data, 0x14 + i * 4)[0])

    # 허프만 트리 빌드
    root = _build_huffman_tree(freq)
    if root is None:
        return b"\x00" * decomp_size

    # 비트스트림 디코딩 (offset 0x414부터)
    bit_count = total_bits
    if flag_byte == 1:
        bit_count *= 8
    header_bits = 0x414 * 8  # 0x20A0
    stream_bits = bit_count - header_bits

    output = bytearray(decomp_size)
    out_pos = 0
    node = root
    for bit_idx in range(stream_bits):
        if out_pos >= decomp_size:
            break
        byte_off = 0x414 + (bit_idx >> 3)
        if byte_off >= len(data):
            break
        bit = (data[byte_off] >> (7 - (bit_idx & 7))) & 1
        node = node[1] if bit else node[0]
        if node is None:
            break
        # 리프 노드 (자식 둘 다 None)
        if isinstance(node, int):
            output[out_pos] = node & 0xFF
            out_pos += 1
            node = root

    return bytes(output[:out_pos] + b"\x00" * (decomp_size - out_pos))


def _build_huffman_tree(freq: list[int]):
    """주파수 테이블에서 허프만 트리 빌드. C 원본 알고리즘과 동일한 순서.
    리프=int(byte값), 내부=[child0, child1]
    child0 = second_smallest (bit 0), child1 = smallest (bit 1)"""
    # 리프 노드: [tree_data, frequency]
    nodes = []
    for byte_val in range(256):
        if freq[byte_val] > 0:
            nodes.append([byte_val, freq[byte_val]])

    if not nodes:
        return None
    if len(nodes) == 1:
        return [nodes[0][0], None]

    while len(nodes) > 1:
        # 1st pass: 가장 작은 frequency (동률시 낮은 인덱스 우선)
        min1_idx = 0
        min1_freq = nodes[0][1]
        for j in range(1, len(nodes)):
            if nodes[j][1] < min1_freq:
                min1_idx = j
                min1_freq = nodes[j][1]

        # 2nd pass: 두번째로 작은 (min1 제외)
        min2_idx = -1
        min2_freq = 0xFFFFFFFF
        for j in range(len(nodes)):
            if j != min1_idx and nodes[j][1] < min2_freq:
                min2_idx = j
                min2_freq = nodes[j][1]

        smallest = nodes[min1_idx]
        second_smallest = nodes[min2_idx]

        # C 원본: child[0]=second_smallest, child[1]=smallest
        parent = [[second_smallest[0], smallest[0]],
                  smallest[1] + second_smallest[1]]

        # min 인덱스에 parent 배치, max 인덱스 제거
        lo = min(min1_idx, min2_idx)
        hi = max(min1_idx, min2_idx)
        nodes[lo] = parent
        nodes.pop(hi)

    return nodes[0][0]


def _slide2_decode(data: bytes, decomp_size: int) -> bytes:
    """YKCMP Type 4: Sliding Window v2 (상대 백레퍼런스)"""
    comp_size = struct.unpack_from("<I", data, 0x0C)[0]
    output = bytearray(decomp_size)
    src = 0x14
    dst = 0
    end = 0x14 + comp_size

    while src < end and dst < decomp_size:
        flag = data[src]
        src += 1

        if flag & 0x80:  # 백레퍼런스
            if not (flag & 0x40):
                # Short: 1바이트, length 1-4, offset 0-15
                length = ((flag >> 4) & 3) + 1
                back = (flag & 0x0F) + 1
            elif not (flag & 0x20):
                # Medium: 2바이트, length 2-33
                b2 = data[src]
                src += 1
                length = (flag & 0x1F) + 2
                back = b2 + 1
            else:
                # Long: 3바이트, length 3-514
                b2 = data[src]
                b3 = data[src + 1]
                src += 2
                length = ((b2 >> 4) | ((flag & 0x1F) << 4)) + 3
                back = ((b2 & 0x0F) << 8 | b3) + 1

            ref = dst - back
            for i in range(length):
                if dst >= decomp_size:
                    break
                output[dst] = output[ref + i] if ref + i >= 0 else 0
                dst += 1
        elif flag != 0:
            # 리터럴: flag 바이트 복사
            count = flag
            for i in range(count):
                if src >= len(data) or dst >= decomp_size:
                    break
                output[dst] = data[src]
                src += 1
                dst += 1

    return bytes(output)


def _rl_decode(data: bytes, decomp_size: int) -> bytes:
    """YKCMP Type 1: Run-Length 디코딩"""
    comp_size = struct.unpack_from("<I", data, 0x0C)[0]
    output = bytearray(decomp_size)
    src = 0x14
    dst = 0
    end = 0x14 + comp_size

    while src < end and dst < decomp_size:
        flag = data[src]
        src += 1
        if flag & 0x80:  # raw bytes
            count = flag & 0x7F
            for _ in range(count):
                if src >= len(data) or dst >= decomp_size:
                    break
                output[dst] = data[src]
                src += 1
                dst += 1
        else:  # run of same byte
            count = flag
            if count == 0:
                continue
            val = data[src]
            src += 1
            for _ in range(count):
                if dst >= decomp_size:
                    break
                output[dst] = val
                dst += 1

    return bytes(output)


def _slide_decode(data: bytes, decomp_size: int) -> bytes:
    """YKCMP Type 2: Sliding Window (LZ77) 디코딩"""
    comp_size = struct.unpack_from("<I", data, 0x0C)[0]
    output = bytearray(decomp_size)
    window = bytearray(0x1000)
    win_pos = 0
    src = 0x14
    dst = 0
    end = 0x14 + comp_size

    # 윈도우 초기화 (원본과 동일한 패턴)
    for i in range(0x1000):
        v = (i - 8) >> 4
        if v < 0:
            v = 0
        if v > 255:
            v = 255
        window[i] = v

    while src < end and dst < decomp_size:
        flag = data[src]
        src += 1

        if flag & 0x80:  # 참조 (백레퍼런스)
            if flag & 0x40:
                b2 = data[src]
                src += 1
                if flag & 0x20:
                    b3 = data[src]
                    src += 1
                    length = ((flag & 0x1F) << 4 | (b2 >> 4)) + 3
                    offset = (b2 & 0x0F) << 8 | b3
                else:
                    length = (flag & 0x1F) + 2
                    offset = b2 + 0xF00
            else:
                length = ((flag >> 4) & 3) + 1
                offset = (flag & 0x0F) + 0xFF0

            for _ in range(length):
                if dst >= decomp_size:
                    break
                b = window[offset & 0xFFF]
                output[dst] = b
                dst += 1
                window[win_pos] = b
                win_pos = (win_pos + 1) & 0xFFF
                offset += 1
        elif flag != 0:  # 리터럴
            for _ in range(flag):
                if src >= len(data) or dst >= decomp_size:
                    break
                b = data[src]
                src += 1
                output[dst] = b
                dst += 1
                window[win_pos] = b
                win_pos = (win_pos + 1) & 0xFFF

    return bytes(output)


# ========== YKCMP_V1 인코더 ==========


def ykcmp_encode(data: bytes) -> bytes:
    """YKCMP_V1 Type 7 (zlib) 압축 인코더."""
    compressed = zlib.compress(data, 9)
    comp_total = 0x14 + len(compressed)
    header = bytearray(0x14)
    header[0:8] = YKCMP_MAGIC
    struct.pack_into("<I", header, 0x08, 7)           # type = 7
    struct.pack_into("<I", header, 0x0C, comp_total)   # total size (header + data)
    struct.pack_into("<I", header, 0x10, len(data))    # decompressed size
    return bytes(header) + compressed


def _slide2_encode(data: bytes) -> bytes:
    """Type 4 slideDec2 인코더: hash chain 기반 빠른 LZ 압축"""
    out = bytearray()
    pos = 0
    data_len = len(data)

    # 해시 체인: 3바이트 해시 → 위치 리스트
    HASH_SIZE = 1 << 16
    head = [-1] * HASH_SIZE  # hash → most recent position
    prev = [0] * data_len     # chain: prev[pos] → previous pos with same hash

    def _hash3(p):
        if p + 2 >= data_len:
            return 0
        return ((data[p] << 8) ^ (data[p + 1] << 4) ^ data[p + 2]) & (HASH_SIZE - 1)

    lit_start = 0  # 리터럴 버퍼 시작

    def _flush_literals():
        nonlocal lit_start
        while lit_start < pos:
            count = min(pos - lit_start, 127)
            out.append(count)
            out.extend(data[lit_start:lit_start + count])
            lit_start += count

    while pos < data_len:
        best_len = 0
        best_back = 0

        if pos + 2 < data_len:
            h = _hash3(pos)
            chain_pos = head[h]
            max_match = min(data_len - pos, 514)
            chain_limit = 64  # 체인 탐색 제한

            while chain_pos >= 0 and chain_limit > 0:
                back = pos - chain_pos
                if back > 4096:
                    break
                # 매치 길이 측정
                ml = 0
                while ml < max_match and data[pos + ml] == data[chain_pos + ml]:
                    ml += 1
                if ml > best_len:
                    best_len = ml
                    best_back = back
                    if ml >= max_match:
                        break
                chain_pos = prev[chain_pos] if chain_pos > 0 else -1
                chain_limit -= 1

        emit_ref = False
        if best_len >= 3:
            _flush_literals()
            back_val = best_back - 1
            if best_len >= 3 and best_back <= 4096:
                # Long: 3 bytes
                length_val = min(best_len, 514) - 3
                best_len = length_val + 3
                b1 = 0xE0 | ((length_val >> 4) & 0x1F)
                b2 = ((length_val & 0x0F) << 4) | ((back_val >> 8) & 0x0F)
                b3 = back_val & 0xFF
                out.extend([b1, b2, b3])
                emit_ref = True
            elif best_len >= 2 and best_back <= 256:
                # Medium: 2 bytes
                length_val = min(best_len, 33) - 2
                best_len = length_val + 2
                b1 = 0xC0 | (length_val & 0x1F)
                b2 = back_val & 0xFF
                out.extend([b1, b2])
                emit_ref = True

        if emit_ref:
            # 해시 체인 업데이트 (매치된 영역)
            for i in range(best_len):
                if pos + i + 2 < data_len:
                    h2 = _hash3(pos + i)
                    prev[pos + i] = head[h2]
                    head[h2] = pos + i
            pos += best_len
            lit_start = pos
        else:
            # 리터럴로 넘기기
            if pos + 2 < data_len:
                h = _hash3(pos)
                prev[pos] = head[h]
                head[h] = pos
            pos += 1

    _flush_literals()
    return bytes(out)


# ========== DSARC FL 상수 ==========
DSARC_MAGIC = b"DSARC FL"
ENTRY_SIZE = 0x80           # 128 bytes per entry
ENTRY_NAME_SIZE = 0x74      # 116 bytes for name field
DATA_ALIGNMENT = 0x200      # 데이터 섹션 정렬 (512 bytes)
HEADER_SIZE = 0x10          # 16 bytes header


def align_to(value: int, alignment: int) -> int:
    """값을 지정된 정렬 경계로 올림"""
    return (value + alignment - 1) & ~(alignment - 1)


def build_dsarc(entries: list[tuple[str, bytes]]) -> bytes:
    """
    DSARC FL 아카이브를 생성합니다.

    Args:
        entries: [(name, data), ...] 형태의 엔트리 리스트

    Returns:
        완성된 DSARC FL 아카이브 바이트열
    """
    entry_count = len(entries)

    # 엔트리 테이블 끝 위치 계산
    entry_table_end = HEADER_SIZE + entry_count * ENTRY_SIZE

    # 데이터 시작 오프셋 (정렬)
    data_start = align_to(entry_table_end, DATA_ALIGNMENT)

    # 각 엔트리의 데이터 오프셋 계산
    offsets = []
    current_offset = data_start
    for _, data in entries:
        offsets.append(current_offset)
        current_offset = align_to(current_offset + len(data), DATA_ALIGNMENT)

    total_size = current_offset

    # 아카이브 빌드
    buf = bytearray(total_size)

    # 헤더
    struct.pack_into("<8sII", buf, 0, DSARC_MAGIC, entry_count, 0)

    # 엔트리 테이블
    for i, (name, data) in enumerate(entries):
        entry_offset = HEADER_SIZE + i * ENTRY_SIZE

        # 이름 (소문자로, null-terminated, 116 bytes)
        name_bytes = name.lower().encode("ascii")[:ENTRY_NAME_SIZE - 1]
        buf[entry_offset:entry_offset + len(name_bytes)] = name_bytes

        # 크기 (uint32) + 오프셋 (uint64)
        struct.pack_into("<IQ", buf, entry_offset + ENTRY_NAME_SIZE,
                         len(data), offsets[i])

    # 데이터 섹션
    for i, (_, data) in enumerate(entries):
        buf[offsets[i]:offsets[i] + len(data)] = data

    return bytes(buf)


def parse_dsarc(data: bytes) -> list[tuple[str, int, int]]:
    """
    DSARC FL 아카이브를 파싱하여 엔트리 정보를 반환합니다.

    Returns:
        [(name, size, offset), ...] 리스트
    """
    magic = data[0:8]
    if magic != DSARC_MAGIC:
        raise ValueError(f"Invalid magic: {magic!r}, expected {DSARC_MAGIC!r}")

    count = struct.unpack_from("<I", data, 8)[0]
    entries = []

    for i in range(count):
        entry_off = HEADER_SIZE + i * ENTRY_SIZE
        name_raw = data[entry_off:entry_off + ENTRY_NAME_SIZE]
        name = name_raw.split(b"\x00")[0].decode("ascii", errors="replace")
        size, offset = struct.unpack_from("<IQ", data, entry_off + ENTRY_NAME_SIZE)
        entries.append((name, size, offset))

    return entries


def extract_dsarc(data: bytes, output_dir: str, decompress: bool = True):
    """DSARC FL 아카이브에서 모든 엔트리를 추출합니다."""
    entries = parse_dsarc(data)
    os.makedirs(output_dir, exist_ok=True)

    for name, size, offset in entries:
        entry_data = data[offset:offset + size]

        # YKCMP 자동 디코딩
        was_compressed = False
        if decompress and len(entry_data) >= 8 and entry_data[:8] == YKCMP_MAGIC:
            print(f"  YKCMP 디코딩 중: {name}...")
            entry_data = ykcmp_decode(entry_data)
            was_compressed = True

        # 실제 포맷에 맞는 확장자 결정
        ext = _detect_font_ext(entry_data)
        if ext:
            base = os.path.splitext(name)[0]
            out_name = f"{base}{ext}"
        else:
            out_name = name

        out_path = os.path.join(output_dir, out_name)
        with open(out_path, "wb") as f:
            f.write(entry_data)

        comp_info = " (YKCMP 디코딩됨)" if was_compressed else ""
        print(f"  추출: {out_name} ({len(entry_data):,} bytes){comp_info}")

    return entries


def _detect_font_ext(data: bytes) -> str | None:
    """데이터의 실제 포맷을 감지하여 확장자 반환"""
    if len(data) < 4:
        return None
    magic = data[:4]
    if magic == b"\x00\x01\x00\x00":
        return ".ttf"
    elif magic == b"OTTO":
        return ".otf"
    elif magic == b"ttcf":
        return ".ttc"
    elif magic == b"wOFF":
        return ".woff"
    return None


def patch_font_for_game(font_data: bytearray) -> bytearray:
    """
    풍우래기5 게임에 맞게 OTF(CFF) 폰트를 패치합니다.
    1. 한글 advance width → 1000 (전각)
    2. CFF FontBBox yMin → -416 (원본 게임 폰트와 동일한 수직 오프셋 52)
    3. head yMin → -416
    """
    from fontTools.ttLib import TTFont
    from io import BytesIO
    import struct as _struct

    f = TTFont(BytesIO(font_data))

    # 1. 한글 advance 1000으로 통일
    hmtx = f['hmtx']
    cmap = f.getBestCmap()
    changed = 0
    for cp in list(range(0xAC00, 0xD7A4)) + list(range(0x3131, 0x318F)):
        gid = cmap.get(cp)
        if gid:
            w, lsb = hmtx[gid]
            if w != 1000:
                hmtx[gid] = (1000, lsb)
                changed += 1
    print(f"  한글 advance → 1000: {changed}개 수정")

    # fontTools로 저장 (hmtx 반영)
    buf = BytesIO()
    f.save(buf)
    f.close()
    font_data = bytearray(buf.getvalue())

    # 2. CFF FontBBox yMin 바이너리 패치 (-416)
    # CFF 테이블 찾기
    num_tables = _struct.unpack_from('>H', font_data, 4)[0]
    cff_off = 0
    head_off = 0
    for i in range(num_tables):
        off = 12 + i * 16
        tag = bytes(font_data[off:off + 4])
        toff = _struct.unpack_from('>I', font_data, off + 8)[0]
        if tag == b'CFF ':
            cff_off = toff
        elif tag == b'head':
            head_off = toff

    if cff_off:
        # CFF 헤더 파싱 → TopDict 위치
        hdr_size = font_data[cff_off + 2]
        # Name INDEX
        pos = cff_off + hdr_size
        name_count = _struct.unpack_from('>H', font_data, pos)[0]
        if name_count > 0:
            name_off_size = font_data[pos + 2]
            last_off_pos = pos + 3 + name_count * name_off_size
            last_off = int.from_bytes(font_data[last_off_pos:last_off_pos + name_off_size], 'big')
            name_end = pos + 3 + (name_count + 1) * name_off_size + last_off - 1
        else:
            name_end = pos + 2
        # TopDict INDEX
        td_pos = name_end
        td_count = _struct.unpack_from('>H', font_data, td_pos)[0]
        td_off_size = font_data[td_pos + 2]
        td_off1 = int.from_bytes(font_data[td_pos + 3:td_pos + 3 + td_off_size], 'big')
        td_data_base = td_pos + 3 + (td_count + 1) * td_off_size
        td_start = td_data_base + td_off1 - 1

        # TopDict에서 FontBBox yMin (FE xx = -1000~-1131 범위) 찾기
        # FontBBox: op 5. 패턴: xMin yMin xMax yMax 05
        # yMin을 -(b0-251)*256 - b1 - 108 인코딩에서 찾아 패치
        td = font_data[td_start:]
        # op 5 (FontBBox) 찾기
        for i in range(min(200, len(td))):
            if td[i] == 0x05 and i > 8:
                # 바로 앞 4개 CFF 정수를 역파싱
                # 간단하게: FE xx 패턴 (yMin ≈ -1045) 찾기
                for j in range(i - 1, max(i - 20, 0), -1):
                    b0 = td[j]
                    if 251 <= b0 <= 254 and j + 1 < i:
                        b1 = td[j + 1]
                        val = -(b0 - 251) * 256 - b1 - 108
                        if -1100 < val < -900:  # yMin 범위
                            abs_off = td_start + j
                            # -416 인코딩: b0=252(FC) b1=52(34)
                            font_data[abs_off] = 0xFC
                            font_data[abs_off + 1] = 0x34
                            print(f"  CFF FontBBox yMin: {val} → -416 (offset 0x{abs_off:X})")
                            break
                break

    # 3. head yMin 패치
    if head_off:
        old = _struct.unpack_from('>h', font_data, head_off + 38)[0]
        _struct.pack_into('>h', font_data, head_off + 38, -416)
        print(f"  head yMin: {old} → -416")

    return font_data


def create_font_archive(font_path: str, output_path: str, entry_name: str = None,
                        compress: bool = True):
    """
    OTF(CFF) 폰트 파일로부터 fontTexture.nltx를 생성합니다.
    자동으로 게임 메트릭 패치 + YKCMP 압축을 적용합니다.

    Args:
        font_path: 입력 폰트 파일 경로 (.otf, CFF 아웃라인 필수)
        output_path: 출력 nltx 파일 경로
        entry_name: DSARC 엔트리 이름 (기본: fot-seuratpron-m.ks4)
        compress: YKCMP 압축 (기본 True, 필수)
    """
    with open(font_path, "rb") as f:
        font_data = bytearray(f.read())

    if font_data[:4] != b"OTTO":
        print("[오류] CFF(OTF) 폰트만 지원합니다. TTF는 게임에서 advance width 버그 발생.")
        sys.exit(1)

    if entry_name is None:
        entry_name = "fot-seuratpron-m.ks4"

    # 게임 메트릭 패치
    print("게임 메트릭 패치 중...")
    font_data = patch_font_for_game(font_data)

    # YKCMP zlib 압축 (필수)
    print(f"YKCMP 압축 중... ({len(font_data):,} bytes)")
    compressed = ykcmp_encode(bytes(font_data))
    print(f"압축 완료: {len(compressed):,} bytes")

    # DSARC 아카이브 생성
    archive = build_dsarc([(entry_name, compressed)])

    with open(output_path, "wb") as f:
        f.write(archive)

    print(f"생성 완료: {output_path}")
    print(f"  엔트리: {entry_name}")
    print(f"  아카이브 크기: {len(archive):,} bytes")


def load_charlist(charlist_path: str) -> set[str]:
    """CharList 파일에서 문자 집합을 로드합니다."""
    chars = set()
    with open(charlist_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n\r")
            # "1\t<chars>" 또는 "2\t " 형식
            if "\t" in line:
                _, content = line.split("\t", 1)
            else:
                content = line
            if content.strip() == "eof":
                break
            for ch in content:
                if ch not in ("\t", "\n", "\r"):
                    chars.add(ch)
    return chars


def validate_font_coverage(font_path: str, charlist_path: str) -> tuple[int, int, list[str]]:
    """
    폰트가 문자 목록의 모든 글리프를 포함하는지 검증합니다.
    fonttools 라이브러리가 필요합니다.

    Returns:
        (total_chars, covered_chars, missing_chars_sample)
    """
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        print("[오류] fonttools 라이브러리가 필요합니다.")
        print("       pip install fonttools")
        sys.exit(1)

    chars = load_charlist(charlist_path)
    font = TTFont(font_path)

    # cmap 테이블에서 지원 문자 추출
    cmap = font.getBestCmap()
    if cmap is None:
        print("[오류] 폰트에서 cmap 테이블을 찾을 수 없습니다.")
        sys.exit(1)

    supported = set(cmap.keys())
    missing = []
    covered = 0

    for ch in sorted(chars):
        cp = ord(ch)
        if cp in supported:
            covered += 1
        else:
            missing.append(ch)

    font.close()
    return len(chars), covered, missing


def info_dsarc(file_path: str):
    """DSARC FL 아카이브의 정보를 출력합니다."""
    with open(file_path, "rb") as f:
        data = f.read()

    entries = parse_dsarc(data)
    print(f"파일: {file_path}")
    print(f"크기: {len(data):,} bytes")
    print(f"엔트리 수: {len(entries)}")
    print()

    for i, (name, size, offset) in enumerate(entries):
        entry_magic = data[offset:offset + 8] if offset + 8 <= len(data) else b""
        compressed = "YKCMP" if entry_magic == b"YKCMP_V1" else "raw"
        print(f"  [{i}] {name}")
        print(f"      크기: {size:,} bytes, 오프셋: 0x{offset:X}, 타입: {compressed}")


def main():
    parser = argparse.ArgumentParser(
        description="풍우래기5 fontTexture.nltx 생성기 / DSARC FL 도구"
    )
    subparsers = parser.add_subparsers(dest="command", help="명령")

    # create 명령
    create_parser = subparsers.add_parser("create", help="TTF/OTF로 fontTexture.nltx 생성")
    create_parser.add_argument("font", help="입력 폰트 파일 (.ttf/.otf)")
    create_parser.add_argument("output", nargs="?", default="fontTexture.nltx",
                               help="출력 파일 (기본: fontTexture.nltx)")
    create_parser.add_argument("--name", help="DSARC 엔트리 이름 (기본: 폰트파일명.ks4)")
    create_parser.add_argument("--charlist", help="문자 목록 파일로 커버리지 검증")
    create_parser.add_argument("--compress", action="store_true",
                               help="YKCMP Type4 압축 적용 (원본과 동일 방식)")

    # info 명령
    info_parser = subparsers.add_parser("info", help="DSARC FL 아카이브 정보 출력")
    info_parser.add_argument("file", help="nltx 파일 경로")

    # extract 명령
    extract_parser = subparsers.add_parser("extract", help="DSARC FL 아카이브에서 추출")
    extract_parser.add_argument("file", help="nltx 파일 경로")
    extract_parser.add_argument("output_dir", nargs="?", default="extracted",
                                help="추출 디렉토리 (기본: extracted)")

    # validate 명령
    validate_parser = subparsers.add_parser("validate", help="폰트 문자 커버리지 검증")
    validate_parser.add_argument("font", help="폰트 파일 (.ttf/.otf)")
    validate_parser.add_argument("--charlist", required=True, help="문자 목록 파일")

    # 인자 없으면 help
    if len(sys.argv) < 2:
        parser.print_help()
        sys.exit(1)

    # 하위 명령 없이 폰트 파일을 직접 지정한 경우 (간편 사용)
    if sys.argv[1] not in ("create", "info", "extract", "validate", "-h", "--help"):
        font_path = sys.argv[1]
        output = sys.argv[2] if len(sys.argv) > 2 else "fontTexture.nltx"
        create_font_archive(font_path, output)
        return

    args = parser.parse_args()

    if args.command == "create":
        if args.charlist:
            total, covered, missing = validate_font_coverage(args.font, args.charlist)
            print(f"문자 커버리지: {covered}/{total} ({covered*100/total:.1f}%)")
            if missing:
                sample = missing[:30]
                print(f"  누락 문자 ({len(missing)}개): {''.join(sample)}{'...' if len(missing) > 30 else ''}")
                print()
        create_font_archive(args.font, args.output, args.name, args.compress)
    elif args.command == "info":
        info_dsarc(args.file)
    elif args.command == "extract":
        with open(args.file, "rb") as f:
            data = f.read()
        extract_dsarc(data, args.output_dir)
    elif args.command == "validate":
        total, covered, missing = validate_font_coverage(args.font, args.charlist)
        print(f"폰트: {args.font}")
        print(f"문자 목록: {args.charlist}")
        print(f"커버리지: {covered}/{total} ({covered*100/total:.1f}%)")
        if missing:
            print(f"\n누락 문자 ({len(missing)}개):")
            # 유니코드 블록별 그룹핑
            blocks = {}
            for ch in missing:
                cp = ord(ch)
                if cp < 0x80:
                    block = "ASCII"
                elif cp < 0x0400:
                    block = "Latin/Greek"
                elif cp < 0x0500:
                    block = "Cyrillic"
                elif cp < 0x3000:
                    block = "기호/특수문자"
                elif cp < 0x3100:
                    block = "일본어 (가나)"
                elif cp < 0x3200:
                    block = "한글 자모"
                elif cp < 0xAC00:
                    block = "한글 호환/기호"
                elif cp <= 0xD7A3:
                    block = "한글 음절"
                elif cp >= 0xFF00:
                    block = "전각 문자"
                elif cp >= 0x4E00:
                    block = "한자 (CJK)"
                else:
                    block = "기타"
                blocks.setdefault(block, []).append(ch)
            for block, chars in sorted(blocks.items()):
                sample = ''.join(chars[:50])
                extra = f" ... +{len(chars)-50}" if len(chars) > 50 else ""
                print(f"  {block} ({len(chars)}): {sample}{extra}")
        else:
            print("\n모든 문자가 폰트에 포함되어 있습니다!")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
