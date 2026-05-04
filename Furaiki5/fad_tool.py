"""
풍우래기5 FAD 텍스처 추출/리패킹 도구

사용법:
  python fad_tool.py export <input.fad> <output_dir>    — 텍스처를 PNG로 추출
  python fad_tool.py import <original.fad> <png_dir> <output.fad>  — PNG를 FAD에 리패킹
  python fad_tool.py info <input.fad>                   — FAD 정보 출력
"""

import struct
import sys
import os
import zlib
import argparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    from PIL import Image
    import texture2ddecoder
    import etcpak
except ImportError as e:
    print(f"[오류] 필요한 라이브러리: pip install Pillow texture2ddecoder etcpak")
    print(f"  {e}")
    sys.exit(1)


YKCMP_MAGIC = b"YKCMP_V1"
NLTEX_MAGIC = b"NMPLTEX1"


def parse_fad(data: bytes) -> dict:
    named_count = struct.unpack_from('<I', data, 8)[0]
    res_count = struct.unpack_from('<I', data, 0xC)[0]
    total = named_count + res_count

    entries = []
    for i in range(total):
        pos = 0x50 + i * 0x20
        if pos + 0x20 > len(data):
            break
        name = data[pos:pos + 8].rstrip(b'\x00').decode('ascii', errors='replace').strip()
        size = struct.unpack_from('<I', data, pos + 8)[0]
        flags = struct.unpack_from('<H', data, pos + 12)[0]
        offset = struct.unpack_from('<I', data, pos + 16)[0]
        entries.append({
            'index': i, 'name': name, 'size': size,
            'flags': flags, 'offset': offset, 'table_pos': pos
        })

    return {
        'named_count': named_count,
        'res_count': res_count,
        'entries': entries,
    }


def decode_bc7(data, w, h):
    decoded = texture2ddecoder.decode_bc7(data, w, h)
    result = bytearray(decoded)
    for i in range(0, len(result), 4):
        result[i], result[i + 2] = result[i + 2], result[i]
    return bytes(result)


def export_fad(fad_path: str, output_dir: str):
    data = open(fad_path, 'rb').read()
    info = parse_fad(data)
    os.makedirs(output_dir, exist_ok=True)

    tex_count = 0
    scene_count = 0

    for e in info['entries']:
        if e['size'] == 0 or e['offset'] + e['size'] > len(data):
            continue

        entry_data = data[e['offset']:e['offset'] + e['size']]
        idx = e['index']

        # NLTEX 텍스처 찾기
        nltex_off = entry_data.find(NLTEX_MAGIC)
        if nltex_off >= 0:
            try:
                nltex = entry_data[nltex_off:]
                w = struct.unpack_from('<H', nltex, 0x18)[0]
                h = struct.unpack_from('<H', nltex, 0x1C)[0]
                compress_flag = nltex[0x26]
                pixel_size = struct.unpack_from('<I', nltex, 0x2C)[0]
                data_offset = struct.unpack_from('<I', nltex, 0x34)[0]

                if compress_flag and nltex[data_offset:data_offset + 8] == YKCMP_MAGIC:
                    ykcmp = nltex[data_offset:]
                    if ykcmp[8] == 7:
                        pixels = zlib.decompress(ykcmp[0x14:])
                    else:
                        continue
                else:
                    pixels = nltex[data_offset:data_offset + pixel_size]

                # BC7 디코딩
                rgba = decode_bc7(pixels, w, h)
                img = Image.frombytes("RGBA", (w, h), rgba)
                out_name = f"{idx:03d}_{e['name']}.png" if e['name'] else f"{idx:03d}_tex.png"
                img.save(os.path.join(output_dir, out_name))
                tex_count += 1
            except Exception as ex:
                print(f"  [실패] entry[{idx}]: {ex}")
        elif e['name']:
            # Named entry (씬 데이터) → 바이너리로 저장
            out_name = f"{idx:03d}_{e['name']}.bin"
            open(os.path.join(output_dir, out_name), 'wb').write(entry_data)
            scene_count += 1

    print(f"완료: 텍스처 {tex_count}개 PNG, 씬 {scene_count}개 BIN")


def import_fad(orig_path: str, png_dir: str, output_path: str):
    data = bytearray(open(orig_path, 'rb').read())
    info = parse_fad(bytes(data))

    patched = 0
    for e in info['entries']:
        if e['size'] == 0 or e['offset'] + e['size'] > len(data):
            continue

        entry_data = data[e['offset']:e['offset'] + e['size']]
        nltex_off = entry_data.find(NLTEX_MAGIC)
        if nltex_off < 0:
            continue

        idx = e['index']
        png_name = f"{idx:03d}_{e['name']}.png" if e['name'] else f"{idx:03d}_tex.png"
        png_path = os.path.join(png_dir, png_name)
        if not os.path.exists(png_path):
            continue

        # PNG 로드
        img = Image.open(png_path).convert("RGBA")
        nltex = entry_data[nltex_off:]
        w = struct.unpack_from('<H', nltex, 0x18)[0]
        h = struct.unpack_from('<H', nltex, 0x1C)[0]

        if img.size != (w, h):
            img = img.resize((w, h), Image.LANCZOS)

        # BC7 인코딩
        rgba = img.tobytes()
        bc7 = etcpak.compress_bc7(rgba, w, h)

        # YKCMP zlib 압축
        compressed = zlib.compress(bc7, 9)
        comp_total = 0x14 + len(compressed)
        ykcmp_header = bytearray(0x14)
        ykcmp_header[0:8] = YKCMP_MAGIC
        struct.pack_into("<I", ykcmp_header, 0x08, 7)
        struct.pack_into("<I", ykcmp_header, 0x0C, comp_total)
        struct.pack_into("<I", ykcmp_header, 0x10, len(bc7))
        new_ykcmp = bytes(ykcmp_header) + compressed

        # NLTEX 헤더 업데이트
        data_offset = struct.unpack_from('<I', nltex, 0x34)[0]
        new_nltex_header = bytearray(nltex[:data_offset])
        struct.pack_into("<I", new_nltex_header, 0x2C, len(bc7))
        struct.pack_into("<I", new_nltex_header, 0x30, len(new_ykcmp))

        # 새 엔트리 데이터
        pre_nltex = entry_data[:nltex_off]
        new_entry = pre_nltex + bytes(new_nltex_header) + new_ykcmp

        # 크기 차이 처리
        old_size = e['size']
        new_size = len(new_entry)
        size_diff = new_size - old_size

        if size_diff <= 0:
            # 같거나 작으면 제자리 패치 + 패딩
            data[e['offset']:e['offset'] + new_size] = new_entry
            if size_diff < 0:
                data[e['offset'] + new_size:e['offset'] + old_size] = b'\x00' * (-size_diff)
            struct.pack_into('<I', data, e['table_pos'] + 8, new_size)
            patched += 1
        else:
            # 크면 파일 끝에 추가
            new_offset = len(data)
            data.extend(new_entry)
            struct.pack_into('<I', data, e['table_pos'] + 8, new_size)
            struct.pack_into('<I', data, e['table_pos'] + 16, new_offset)
            patched += 1

    open(output_path, 'wb').write(data)
    print(f"완료: {patched}개 텍스처 리패킹 → {output_path}")


def info_fad(fad_path: str):
    data = open(fad_path, 'rb').read()
    info = parse_fad(data)
    print(f"파일: {fad_path} ({len(data):,} bytes)")
    print(f"Named: {info['named_count']}, Resources: {info['res_count']}")
    for e in info['entries']:
        label = e['name'] if e['name'] else '(resource)'
        nltex = ""
        if e['size'] > 0 and e['offset'] + 0x48 <= len(data):
            entry_data = data[e['offset']:e['offset'] + e['size']]
            if NLTEX_MAGIC in entry_data[:0x80]:
                nltex_off = entry_data.find(NLTEX_MAGIC)
                w = struct.unpack_from('<H', entry_data, nltex_off + 0x18)[0]
                h = struct.unpack_from('<H', entry_data, nltex_off + 0x1C)[0]
                nltex = f" [{w}x{h}]"
        print(f"  [{e['index']:2d}] {label:12s} {e['size']:>10,}B{nltex}")


def main():
    parser = argparse.ArgumentParser(description="풍우래기5 FAD 텍스처 도구")
    sub = parser.add_subparsers(dest="cmd")

    p1 = sub.add_parser("export", help="FAD → PNG 텍스처 추출")
    p1.add_argument("input", help="입력 .fad")
    p1.add_argument("output_dir", help="출력 폴더")

    p2 = sub.add_parser("import", help="PNG → FAD 리패킹")
    p2.add_argument("original", help="원본 .fad")
    p2.add_argument("png_dir", help="편집된 PNG 폴더")
    p2.add_argument("output", help="출력 .fad")

    p3 = sub.add_parser("info", help="FAD 정보")
    p3.add_argument("input", help=".fad 파일")

    args = parser.parse_args()
    if args.cmd == "export":
        export_fad(args.input, args.output_dir)
    elif args.cmd == "import":
        import_fad(args.original, args.png_dir, args.output)
    elif args.cmd == "info":
        info_fad(args.input)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
