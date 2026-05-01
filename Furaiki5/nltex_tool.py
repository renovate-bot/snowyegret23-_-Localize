"""
풍우래기5 NLTEX 이미지 변환 도구

NLTEX (.nltx 이미지) ↔ PNG 변환

사용법:
  python nltex_tool.py decode <input.nltx> [output.png]
  python nltex_tool.py encode <input.png> <reference.nltx> [output.nltx]
  python nltex_tool.py info <input.nltx>
"""

import struct
import sys
import os
import zlib
import argparse
import fnmatch
from concurrent.futures import ThreadPoolExecutor, as_completed

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    from PIL import Image
except ImportError:
    print("[오류] Pillow 라이브러리가 필요합니다: pip install Pillow")
    sys.exit(1)

try:
    import texture2ddecoder
except ImportError:
    texture2ddecoder = None

try:
    import etcpak
except ImportError:
    etcpak = None


NLTEX_MAGIC = b"NMPLTEX1"
NLTEX_HDR_SIZE = 0x80
YKCMP_MAGIC = b"YKCMP_V1"


def parse_nltex_header(data: bytes) -> dict:
    if data[:8] != NLTEX_MAGIC:
        raise ValueError(f"Not NLTEX: {data[:8]!r}")
    return {
        "format": struct.unpack_from("<I", data, 0x10)[0],
        "flags": struct.unpack_from("<I", data, 0x14)[0],
        "width": struct.unpack_from("<H", data, 0x18)[0],
        "height": struct.unpack_from("<H", data, 0x1C)[0],
        "depth": struct.unpack_from("<H", data, 0x20)[0],
        "palette": struct.unpack_from("<H", data, 0x22)[0],
        "compress_flag": data[0x26],
        "pixel_size": struct.unpack_from("<I", data, 0x2C)[0],
        "comp_size": struct.unpack_from("<I", data, 0x30)[0],
        "data_offset": struct.unpack_from("<I", data, 0x34)[0],
        "raw_header": data[:NLTEX_HDR_SIZE],
    }


def decompress_nltex_pixels(data: bytes, hdr: dict) -> bytes:
    """NLTEX에서 픽셀 데이터 추출 (YKCMP 디코딩 포함)"""
    offset = hdr["data_offset"]
    if hdr["compress_flag"] != 0 and data[offset:offset + 8] == YKCMP_MAGIC:
        ykcmp = data[offset:]
        ykcmp_type = ykcmp[8]
        if ykcmp_type == 7:
            # Type 7 = zlib
            return zlib.decompress(ykcmp[0x14:])
        else:
            raise ValueError(f"Unsupported YKCMP type: {ykcmp_type}")
    else:
        return data[offset:offset + hdr["pixel_size"]]


def compress_nltex_pixels(pixels: bytes) -> bytes:
    """픽셀 데이터를 YKCMP Type 7 (zlib)로 압축"""
    compressed = zlib.compress(pixels, 9)
    # YKCMP 헤더
    comp_total = 0x14 + len(compressed)
    header = bytearray(0x14)
    header[0:8] = YKCMP_MAGIC
    struct.pack_into("<I", header, 0x08, 7)           # type 7
    struct.pack_into("<I", header, 0x0C, comp_total)   # total compressed size (incl header)
    struct.pack_into("<I", header, 0x10, len(pixels))  # decompressed size
    return bytes(header) + compressed


# ========== BC1/DXT1, BC3/DXT5 코덱 ==========

def _bc_block_count(width: int, height: int) -> int:
    return ((width + 3) // 4) * ((height + 3) // 4)


def _bc_base_size(width: int, height: int, bytes_per_block: int) -> int:
    return _bc_block_count(width, height) * bytes_per_block


def decode_bc1(data: bytes, width: int, height: int) -> bytes:
    """BC1/DXT1 → RGBA"""
    bw = (width + 3) // 4
    bh = (height + 3) // 4
    rgba = bytearray(width * height * 4)
    block_idx = 0

    for by in range(bh):
        for bx in range(bw):
            off = block_idx * 8
            if off + 8 > len(data):
                break

            colors = _decode_bc1_block(data[off:off + 8])
            for py in range(4):
                for px in range(4):
                    x = bx * 4 + px
                    y = by * 4 + py
                    if x < width and y < height:
                        src = py * 4 + px
                        dst = (y * width + x) * 4
                        r, g, b, a = colors[src]
                        rgba[dst] = r
                        rgba[dst + 1] = g
                        rgba[dst + 2] = b
                        rgba[dst + 3] = a

            block_idx += 1

    return bytes(rgba)


def _decode_bc1_block(data: bytes) -> list[tuple[int, int, int, int]]:
    c0 = struct.unpack_from("<H", data, 0)[0]
    c1 = struct.unpack_from("<H", data, 2)[0]
    indices = struct.unpack_from("<I", data, 4)[0]

    def rgb565(c):
        r = ((c >> 11) & 0x1F) * 255 // 31
        g = ((c >> 5) & 0x3F) * 255 // 63
        b = (c & 0x1F) * 255 // 31
        return (r, g, b)

    r0, g0, b0 = rgb565(c0)
    r1, g1, b1 = rgb565(c1)

    if c0 > c1:
        lut = [(r0, g0, b0, 255), (r1, g1, b1, 255),
               ((2 * r0 + r1 + 1) // 3, (2 * g0 + g1 + 1) // 3, (2 * b0 + b1 + 1) // 3, 255),
               ((r0 + 2 * r1 + 1) // 3, (g0 + 2 * g1 + 1) // 3, (b0 + 2 * b1 + 1) // 3, 255)]
    else:
        lut = [(r0, g0, b0, 255), (r1, g1, b1, 255),
               ((r0 + r1 + 1) // 2, (g0 + g1 + 1) // 2, (b0 + b1 + 1) // 2, 255),
               (0, 0, 0, 0)]

    colors = [None] * 16
    for i in range(16):
        colors[i] = lut[(indices >> (i * 2)) & 3]
    return colors


def decode_bc3(data: bytes, width: int, height: int) -> bytes:
    """BC3/DXT5 → RGBA"""
    bw = (width + 3) // 4
    bh = (height + 3) // 4
    rgba = bytearray(width * height * 4)
    block_idx = 0

    for by in range(bh):
        for bx in range(bw):
            off = block_idx * 16
            if off + 16 > len(data):
                break

            # Alpha block (8 bytes)
            alpha = _decode_alpha_block(data[off:off + 8])
            # Color block (8 bytes)
            colors = _decode_color_block(data[off + 8:off + 16])

            for py in range(4):
                for px in range(4):
                    x = bx * 4 + px
                    y = by * 4 + py
                    if x < width and y < height:
                        i = py * 4 + px
                        dst = (y * width + x) * 4
                        r, g, b = colors[i]
                        a = alpha[i]
                        rgba[dst] = r
                        rgba[dst + 1] = g
                        rgba[dst + 2] = b
                        rgba[dst + 3] = a

            block_idx += 1

    return bytes(rgba)


def _decode_alpha_block(data: bytes) -> list[int]:
    a0 = data[0]
    a1 = data[1]
    # 48-bit index table (6 bytes, 16 * 3-bit indices)
    bits = int.from_bytes(data[2:8], "little")
    alphas = [0] * 16

    if a0 > a1:
        lut = [a0, a1,
               (6 * a0 + 1 * a1 + 3) // 7,
               (5 * a0 + 2 * a1 + 3) // 7,
               (4 * a0 + 3 * a1 + 3) // 7,
               (3 * a0 + 4 * a1 + 3) // 7,
               (2 * a0 + 5 * a1 + 3) // 7,
               (1 * a0 + 6 * a1 + 3) // 7]
    else:
        lut = [a0, a1,
               (4 * a0 + 1 * a1 + 2) // 5,
               (3 * a0 + 2 * a1 + 2) // 5,
               (2 * a0 + 3 * a1 + 2) // 5,
               (1 * a0 + 4 * a1 + 2) // 5,
               0, 255]

    for i in range(16):
        alphas[i] = lut[(bits >> (i * 3)) & 7]
    return alphas


def _decode_color_block(data: bytes) -> list[tuple[int, int, int]]:
    c0 = struct.unpack_from("<H", data, 0)[0]
    c1 = struct.unpack_from("<H", data, 2)[0]
    indices = struct.unpack_from("<I", data, 4)[0]

    def rgb565(c):
        r = ((c >> 11) & 0x1F) * 255 // 31
        g = ((c >> 5) & 0x3F) * 255 // 63
        b = (c & 0x1F) * 255 // 31
        return (r, g, b)

    r0, g0, b0 = rgb565(c0)
    r1, g1, b1 = rgb565(c1)

    lut = [(r0, g0, b0), (r1, g1, b1),
           ((2 * r0 + r1 + 1) // 3, (2 * g0 + g1 + 1) // 3, (2 * b0 + b1 + 1) // 3),
           ((r0 + 2 * r1 + 1) // 3, (g0 + 2 * g1 + 1) // 3, (b0 + 2 * b1 + 1) // 3)]

    colors = [None] * 16
    for i in range(16):
        colors[i] = lut[(indices >> (i * 2)) & 3]
    return colors


def encode_bc3(rgba: bytes, width: int, height: int) -> bytes:
    """RGBA → BC3/DXT5"""
    bw = (width + 3) // 4
    bh = (height + 3) // 4
    out = bytearray(bw * bh * 16)

    for by in range(bh):
        for bx in range(bw):
            block_pixels = []
            block_alpha = []
            for py in range(4):
                for px in range(4):
                    x = min(bx * 4 + px, width - 1)
                    y = min(by * 4 + py, height - 1)
                    src = (y * width + x) * 4
                    r, g, b, a = rgba[src], rgba[src + 1], rgba[src + 2], rgba[src + 3]
                    block_pixels.append((r, g, b))
                    block_alpha.append(a)

            off = (by * bw + bx) * 16
            out[off:off + 8] = _encode_alpha_block(block_alpha)
            out[off + 8:off + 16] = _encode_color_block(block_pixels)

    return bytes(out)


def encode_bc1(rgba: bytes, width: int, height: int) -> bytes:
    """RGBA → BC1/DXT1"""
    bw = (width + 3) // 4
    bh = (height + 3) // 4
    out = bytearray(bw * bh * 8)

    for by in range(bh):
        for bx in range(bw):
            block_pixels = []
            for py in range(4):
                for px in range(4):
                    x = min(bx * 4 + px, width - 1)
                    y = min(by * 4 + py, height - 1)
                    src = (y * width + x) * 4
                    block_pixels.append((rgba[src], rgba[src + 1], rgba[src + 2]))

            off = (by * bw + bx) * 8
            out[off:off + 8] = _encode_color_block(block_pixels)

    return bytes(out)


def _encode_alpha_block(alphas: list[int]) -> bytes:
    a0 = max(alphas)
    a1 = min(alphas)
    if a0 == a1:
        a0 = min(a0 + 1, 255) if a0 < 255 else 255
        a1 = max(a1 - 1, 0) if a1 > 0 else 0

    if a0 > a1:
        lut = [a0, a1,
               (6 * a0 + 1 * a1 + 3) // 7,
               (5 * a0 + 2 * a1 + 3) // 7,
               (4 * a0 + 3 * a1 + 3) // 7,
               (3 * a0 + 4 * a1 + 3) // 7,
               (2 * a0 + 5 * a1 + 3) // 7,
               (1 * a0 + 6 * a1 + 3) // 7]
    else:
        lut = [a0, a1,
               (4 * a0 + 1 * a1 + 2) // 5,
               (3 * a0 + 2 * a1 + 2) // 5,
               (2 * a0 + 3 * a1 + 2) // 5,
               (1 * a0 + 4 * a1 + 2) // 5,
               0, 255]

    bits = 0
    for i in range(16):
        best_idx = 0
        best_dist = abs(alphas[i] - lut[0])
        for j in range(1, len(lut)):
            d = abs(alphas[i] - lut[j])
            if d < best_dist:
                best_dist = d
                best_idx = j
        bits |= best_idx << (i * 3)

    result = bytearray(8)
    result[0] = a0
    result[1] = a1
    result[2:8] = bits.to_bytes(6, "little")
    return bytes(result)


def _encode_color_block(pixels: list[tuple[int, int, int]]) -> bytes:
    # min/max 엔드포인트 선택
    min_r = min_g = min_b = 255
    max_r = max_g = max_b = 0
    for r, g, b in pixels:
        min_r = min(min_r, r); min_g = min(min_g, g); min_b = min(min_b, b)
        max_r = max(max_r, r); max_g = max(max_g, g); max_b = max(max_b, b)

    def to565(r, g, b):
        return ((r * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5 | ((b * 31 + 127) // 255)

    c0 = to565(max_r, max_g, max_b)
    c1 = to565(min_r, min_g, min_b)
    if c0 == c1:
        c0 = min(c0 + 1, 0xFFFF)

    if c0 < c1:
        c0, c1 = c1, c0

    def from565(c):
        r = ((c >> 11) & 0x1F) * 255 // 31
        g = ((c >> 5) & 0x3F) * 255 // 63
        b = (c & 0x1F) * 255 // 31
        return (r, g, b)

    r0, g0, b0 = from565(c0)
    r1, g1, b1 = from565(c1)
    lut = [(r0, g0, b0), (r1, g1, b1),
           ((2*r0+r1+1)//3, (2*g0+g1+1)//3, (2*b0+b1+1)//3),
           ((r0+2*r1+1)//3, (g0+2*g1+1)//3, (b0+2*b1+1)//3)]

    indices = 0
    for i, (r, g, b) in enumerate(pixels):
        best = 0
        best_d = (r-lut[0][0])**2 + (g-lut[0][1])**2 + (b-lut[0][2])**2
        for j in range(1, 4):
            d = (r-lut[j][0])**2 + (g-lut[j][1])**2 + (b-lut[j][2])**2
            if d < best_d:
                best_d = d
                best = j
        indices |= best << (i * 2)

    result = bytearray(8)
    struct.pack_into("<H", result, 0, c0)
    struct.pack_into("<H", result, 2, c1)
    struct.pack_into("<I", result, 4, indices)
    return bytes(result)



def detect_bc_format(
    pixel_data: bytes,
    width: int | None = None,
    height: int | None = None,
    flags: int | None = None,
) -> str:
    """압축 데이터 크기와 첫 블록의 mode bit으로 BC1/BC3/BC7 판별"""
    if width is not None and height is not None:
        bc1_size = _bc_base_size(width, height, 8)
        bc3_size = _bc_base_size(width, height, 16)
        if flags is not None:
            if (flags & 0x400000) and len(pixel_data) < bc3_size:
                return "bc1"
            if flags & 0x800000:
                return "bc7"
        if bc1_size <= len(pixel_data) < bc3_size:
            return "bc1"

    if len(pixel_data) < 16:
        return "bc1" if len(pixel_data) >= 8 else "bc3"
    b0 = pixel_data[0]
    # BC7: 첫 바이트에서 lowest set bit이 mode
    for bit in range(8):
        if b0 & (1 << bit):
            return "bc7"
    # bit 없으면 BC7 mode 0도 아님 → BC3으로 간주
    return "bc3"


def _base_mip(pixel_data: bytes, width: int, height: int, fmt: str) -> bytes:
    bytes_per_block = 8 if fmt == "bc1" else 16
    return pixel_data[:_bc_base_size(width, height, bytes_per_block)]


def _native_decode_to_image(fmt: str, data: bytes, width: int, height: int) -> Image.Image | None:
    if texture2ddecoder is None:
        return None

    decoder = {
        "bc1": getattr(texture2ddecoder, "decode_bc1", None),
        "bc3": getattr(texture2ddecoder, "decode_bc3", None),
        "bc7": getattr(texture2ddecoder, "decode_bc7", None),
    }.get(fmt)
    if decoder is None:
        return None

    decoded = decoder(data, width, height)
    return Image.frombytes("RGBA", (width, height), decoded, "raw", "BGRA")


def decode_texture_image(pixel_data: bytes, width: int, height: int, fmt: str) -> Image.Image:
    base = _base_mip(pixel_data, width, height, fmt)
    native = _native_decode_to_image(fmt, base, width, height)
    if native is not None:
        return native

    if fmt == "bc1":
        rgba = decode_bc1(base, width, height)
    elif fmt == "bc3":
        rgba = decode_bc3(base, width, height)
    else:
        rgba = decode_bc7(base, width, height)
    return Image.frombytes("RGBA", (width, height), rgba)


def decode_bc7(data: bytes, width: int, height: int) -> bytes:
    """BC7 → RGBA (texture2ddecoder 사용)"""
    if texture2ddecoder is None:
        raise ImportError("BC7 디코딩에 texture2ddecoder가 필요합니다: pip install texture2ddecoder")
    decoded = texture2ddecoder.decode_bc7(data, width, height)
    # texture2ddecoder는 BGRA 반환 → RGBA로 변환
    result = bytearray(decoded)
    for i in range(0, len(result), 4):
        result[i], result[i + 2] = result[i + 2], result[i]  # B↔R swap
    return bytes(result)


def nltex_to_png(nltex_path: str, png_path: str, png_compress: int = 1):
    data = open(nltex_path, "rb").read()
    hdr = parse_nltex_header(data)
    w, h = hdr["width"], hdr["height"]

    pixels = decompress_nltex_pixels(data, hdr)
    fmt = detect_bc_format(pixels, w, h, hdr["flags"])
    print(f"감지된 포맷: {fmt.upper()}")

    img = decode_texture_image(pixels, w, h, fmt)
    img.save(png_path, compress_level=png_compress)
    print(f"변환 완료: {png_path} ({w}x{h})")


def encode_bc7(rgba: bytes, width: int, height: int) -> bytes:
    """RGBA → BC7 (etcpak 사용)"""
    if etcpak is None:
        raise ImportError("BC7 인코딩에 etcpak이 필요합니다: pip install etcpak")
    return etcpak.compress_bc7(rgba, width, height)


def _pad_rgba_for_blocks(rgba: bytes, width: int, height: int) -> tuple[bytes, int, int]:
    padded_w = ((width + 3) // 4) * 4
    padded_h = ((height + 3) // 4) * 4
    if padded_w == width and padded_h == height:
        return rgba, width, height

    src_stride = width * 4
    padded = bytearray(padded_w * padded_h * 4)
    for y in range(padded_h):
        src_y = min(y, height - 1)
        src_row = rgba[src_y * src_stride:(src_y + 1) * src_stride]
        dst_off = y * padded_w * 4
        padded[dst_off:dst_off + src_stride] = src_row
        edge = src_row[-4:]
        for x in range(width, padded_w):
            off = dst_off + x * 4
            padded[off:off + 4] = edge
    return bytes(padded), padded_w, padded_h


def encode_texture_level(rgba: bytes, width: int, height: int, fmt: str) -> bytes:
    if etcpak is not None:
        padded_rgba, padded_w, padded_h = _pad_rgba_for_blocks(rgba, width, height)
        if fmt == "bc1" and hasattr(etcpak, "compress_bc1"):
            return etcpak.compress_bc1(padded_rgba, padded_w, padded_h)
        if fmt == "bc3" and hasattr(etcpak, "compress_bc3"):
            return etcpak.compress_bc3(padded_rgba, padded_w, padded_h)
        if fmt == "bc7" and hasattr(etcpak, "compress_bc7"):
            return etcpak.compress_bc7(padded_rgba, padded_w, padded_h)

    if fmt == "bc1":
        return encode_bc1(rgba, width, height)
    if fmt == "bc3":
        return encode_bc3(rgba, width, height)
    return encode_bc7(rgba, width, height)


def _resize_filter():
    return getattr(getattr(Image, "Resampling", Image), "LANCZOS")


def encode_texture_like_reference(img: Image.Image, fmt: str, ref_pixel_size: int) -> bytes:
    width, height = img.size
    base_size = _bc_base_size(width, height, 8 if fmt == "bc1" else 16)
    if ref_pixel_size <= base_size:
        return encode_texture_level(img.tobytes(), width, height, fmt)

    chunks = []
    total = 0
    mip = img
    mip_w, mip_h = width, height

    while total < ref_pixel_size:
        chunk = encode_texture_level(mip.tobytes(), mip_w, mip_h, fmt)
        chunks.append(chunk)
        total += len(chunk)
        if mip_w == 1 and mip_h == 1:
            break
        mip_w = max(1, mip_w // 2)
        mip_h = max(1, mip_h // 2)
        mip = mip.resize((mip_w, mip_h), _resize_filter())

    data = b"".join(chunks)
    if len(data) > ref_pixel_size:
        return data[:ref_pixel_size]
    return data


def png_to_nltex(png_path: str, ref_nltex_path: str, out_path: str, verbose: bool = True):
    """PNG를 NLTEX로 변환. 레퍼런스 nltx의 헤더를 기반으로 생성."""
    ref_data = open(ref_nltex_path, "rb").read()
    ref_hdr = parse_nltex_header(ref_data)

    img = Image.open(png_path).convert("RGBA")
    w, h = img.size

    if w != ref_hdr["width"] or h != ref_hdr["height"]:
        print(f"[경고] 크기 불일치: PNG={w}x{h}, ref={ref_hdr['width']}x{ref_hdr['height']}")
        print(f"       레퍼런스 크기로 리사이즈합니다.")
        img = img.resize((ref_hdr["width"], ref_hdr["height"]), Image.LANCZOS)
        w, h = ref_hdr["width"], ref_hdr["height"]

    # 원본 포맷 감지
    ref_pixels = decompress_nltex_pixels(ref_data, ref_hdr)
    fmt = detect_bc_format(ref_pixels, w, h, ref_hdr["flags"])
    if verbose:
        print(f"인코딩 포맷: {fmt.upper()}")

    bc_data = encode_texture_like_reference(img, fmt, len(ref_pixels))

    compressed = compress_nltex_pixels(bc_data)

    # 레퍼런스 헤더 복사 후 크기 필드만 업데이트
    header = bytearray(ref_hdr["raw_header"])
    struct.pack_into("<I", header, 0x2C, len(bc_data))    # decompressed pixel size
    struct.pack_into("<I", header, 0x30, len(compressed))  # compressed size

    with open(out_path, "wb") as f:
        f.write(header)
        f.write(compressed)

    if verbose:
        print(f"변환 완료: {out_path} ({w}x{h}, {len(compressed):,} bytes)")


def nltex_info(path: str):
    data = open(path, "rb").read()
    hdr = parse_nltex_header(data)
    print(f"파일: {path} ({len(data):,} bytes)")
    print(f"크기: {hdr['width']}x{hdr['height']}")
    print(f"포맷: 0x{hdr['format']:X}, 플래그: 0x{hdr['flags']:X}")
    print(f"픽셀 데이터: {hdr['pixel_size']:,} bytes (디코딩 후)")
    print(f"압축: {'YKCMP' if hdr['compress_flag'] else '없음'}")
    if hdr["compress_flag"]:
        ykcmp_type = data[hdr["data_offset"] + 8] if len(data) > hdr["data_offset"] + 8 else -1
        print(f"YKCMP 타입: {ykcmp_type}")


def _normalize_excludes(excludes) -> list[str]:
    patterns = []
    for group in excludes or []:
        items = group if isinstance(group, (list, tuple)) else [group]
        for item in items:
            for pattern in str(item).replace(",", " ").split():
                pattern = pattern.strip()
                if pattern:
                    patterns.append(pattern)
    return patterns


def _is_excluded_path(file_path: str, exclude_patterns: list[str]) -> bool:
    if not exclude_patterns:
        return False

    name = os.path.basename(file_path)
    stem = os.path.splitext(name)[0]
    name_lower = name.lower()
    stem_lower = stem.lower()

    for pattern in exclude_patterns:
        pattern_lower = pattern.lower()
        if any(ch in pattern_lower for ch in "*?[]"):
            if fnmatch.fnmatchcase(name_lower, pattern_lower) or fnmatch.fnmatchcase(stem_lower, pattern_lower):
                return True
        elif name_lower.startswith(pattern_lower) or stem_lower.startswith(pattern_lower):
            return True
    return False


def _decode_one_to_png(file_path: str, output_dir: str, png_compress: int) -> tuple[str, str, str | None]:
    base = os.path.splitext(os.path.basename(file_path))[0]
    out = os.path.join(output_dir, base + ".png")
    try:
        data = open(file_path, "rb").read()
        if data[:8] != NLTEX_MAGIC:
            return ("skip", base, None)
        hdr = parse_nltex_header(data)
        pixels = decompress_nltex_pixels(data, hdr)
        fmt = detect_bc_format(pixels, hdr["width"], hdr["height"], hdr["flags"])
        img = decode_texture_image(pixels, hdr["width"], hdr["height"], fmt)
        img.save(out, compress_level=png_compress)
        return ("ok", base, None)
    except Exception as e:
        return ("fail", base, str(e))


def batch_decode(input_dir: str, output_dir: str, workers: int = 0, png_compress: int = 1, excludes=None):
    """폴더 내 모든 .nltx → PNG 일괄 변환"""
    import glob
    os.makedirs(output_dir, exist_ok=True)
    files = glob.glob(os.path.join(input_dir, "*.nltx"))
    exclude_patterns = _normalize_excludes(excludes)
    if workers <= 0:
        workers = min(16, max(1, (os.cpu_count() or 4)))
    png_compress = max(0, min(9, png_compress))

    sorted_files = sorted(files)
    excluded = sum(1 for f in sorted_files if _is_excluded_path(f, exclude_patterns))
    sorted_files = [f for f in sorted_files if not _is_excluded_path(f, exclude_patterns)]

    exclude_text = f", exclude={','.join(exclude_patterns)}" if exclude_patterns else ""
    print(f"{len(files)} files: {output_dir} (workers={workers}, png_compress={png_compress}{exclude_text})")
    if excluded:
        print(f"  제외: {excluded}, 처리 대상: {len(sorted_files)}")
    ok = fail = skip = 0

    if workers == 1:
        results = (_decode_one_to_png(f, output_dir, png_compress) for f in sorted_files)
        for done, (status, base, err) in enumerate(results, 1):
            if status == "ok":
                ok += 1
            elif status == "skip":
                skip += 1
            else:
                print(f"  [실패] {base}: {err}")
                fail += 1
            if done % 100 == 0 or done == len(sorted_files):
                print(f"  진행: {done}/{len(sorted_files)}")
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_decode_one_to_png, f, output_dir, png_compress) for f in sorted_files]
            for done, future in enumerate(as_completed(futures), 1):
                status, base, err = future.result()
                if status == "ok":
                    ok += 1
                elif status == "skip":
                    skip += 1
                else:
                    print(f"  [실패] {base}: {err}")
                    fail += 1
                if done % 100 == 0 or done == len(futures):
                    print(f"  진행: {done}/{len(futures)}")
    print(f"완료: {ok} 성공, {fail} 실패, {skip} 스킵, {excluded} 제외")


def _encode_one_to_nltex(file_path: str, ref_dir: str, output_dir: str) -> tuple[str, str, str | None]:
    base = os.path.splitext(os.path.basename(file_path))[0]
    ref = os.path.join(ref_dir, base + ".nltx")
    out = os.path.join(output_dir, base + ".nltx")
    if not os.path.exists(ref):
        return ("skip", base, None)
    try:
        png_to_nltex(file_path, ref, out, verbose=False)
        return ("ok", base, None)
    except Exception as e:
        return ("fail", base, str(e))


def batch_encode(input_dir: str, ref_dir: str, output_dir: str, workers: int = 0, excludes=None):
    """폴더 내 모든 PNG → NLTEX 일괄 변환 (동명의 .nltx를 레퍼런스로 사용)"""
    import glob
    os.makedirs(output_dir, exist_ok=True)
    files = glob.glob(os.path.join(input_dir, "*.png"))
    exclude_patterns = _normalize_excludes(excludes)
    if workers <= 0:
        workers = min(16, max(1, (os.cpu_count() or 4)))

    sorted_files = sorted(files)
    excluded = sum(1 for f in sorted_files if _is_excluded_path(f, exclude_patterns))
    sorted_files = [f for f in sorted_files if not _is_excluded_path(f, exclude_patterns)]

    exclude_text = f", exclude={','.join(exclude_patterns)}" if exclude_patterns else ""
    print(f"{len(files)}개 파일 변환 시작: {input_dir} → {output_dir} (workers={workers}{exclude_text})")
    if excluded:
        print(f"  제외: {excluded}, 처리 대상: {len(sorted_files)}")
    ok = fail = skip = 0
    if workers == 1:
        results = (_encode_one_to_nltex(f, ref_dir, output_dir) for f in sorted_files)
        for done, (status, base, err) in enumerate(results, 1):
            if status == "ok":
                ok += 1
            elif status == "skip":
                skip += 1
            else:
                print(f"  [실패] {base}: {err}")
                fail += 1
            if done % 100 == 0 or done == len(sorted_files):
                print(f"  진행: {done}/{len(sorted_files)}")
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_encode_one_to_nltex, f, ref_dir, output_dir) for f in sorted_files]
            for done, future in enumerate(as_completed(futures), 1):
                status, base, err = future.result()
                if status == "ok":
                    ok += 1
                elif status == "skip":
                    skip += 1
                else:
                    print(f"  [실패] {base}: {err}")
                    fail += 1
                if done % 100 == 0 or done == len(futures):
                    print(f"  진행: {done}/{len(futures)}")
    print(f"완료: {ok} 성공, {fail} 실패, {skip} 스킵 (레퍼런스 없음), {excluded} 제외")


def auto_convert(filepath: str):
    """드래그앤드롭: 확장자로 자동 판별하여 변환"""
    ext = os.path.splitext(filepath)[1].lower()
    base = os.path.splitext(filepath)[0]

    if ext == ".nltx":
        # NLTEX → PNG
        out = base + ".png"
        nltex_to_png(filepath, out)
    elif ext == ".png":
        # PNG → NLTEX (동명의 .nltx를 레퍼런스로 사용)
        ref = base + ".nltx"
        out = base + "_new.nltx"
        if not os.path.exists(ref):
            print(f"[오류] 레퍼런스 파일 없음: {ref}")
            print(f"       같은 이름의 .nltx 파일이 필요합니다.")
            input("Enter 키를 눌러 종료...")
            sys.exit(1)
        png_to_nltex(filepath, ref, out)
    else:
        print(f"[오류] 지원하지 않는 확장자: {ext}")
        print(f"       .nltx 또는 .png 파일을 드래그하세요.")
        input("Enter 키를 눌러 종료...")
        sys.exit(1)


def main():
    # 드래그앤드롭: 인자가 파일 경로 하나이고 서브커맨드가 아닌 경우
    if len(sys.argv) == 2 and sys.argv[1] not in ("decode", "encode", "info", "-h", "--help"):
        filepath = sys.argv[1]
        if os.path.isfile(filepath):
            try:
                auto_convert(filepath)
            except Exception as e:
                print(f"[오류] {e}")
            input("Enter 키를 눌러 종료...")
            return

    parser = argparse.ArgumentParser(description="풍우래기5 NLTEX 이미지 변환 도구")
    sub = parser.add_subparsers(dest="cmd")

    p1 = sub.add_parser("decode", help="NLTEX → PNG (단일)")
    p1.add_argument("input", help="입력 .nltx 파일")
    p1.add_argument("output", nargs="?", help="출력 .png (기본: input.png)")
    p1.add_argument("--png-compress", type=int, default=1, help="PNG 압축 레벨 0~9 (기본: 1, 낮을수록 빠름)")

    p2 = sub.add_parser("encode", help="PNG → NLTEX (단일)")
    p2.add_argument("input", help="입력 .png 파일")
    p2.add_argument("ref", help="레퍼런스 .nltx (헤더 복사용)")
    p2.add_argument("output", nargs="?", help="출력 .nltx (기본: input.nltx)")

    p3 = sub.add_parser("info", help="NLTEX 정보 출력")
    p3.add_argument("input", help=".nltx 파일")

    p4 = sub.add_parser("batch-decode", help="NLTEX → PNG 일괄 변환")
    p4.add_argument("input_dir", help="입력 폴더 (.nltx 파일들)")
    p4.add_argument("output_dir", help="출력 폴더 (.png)")
    p4.add_argument("-j", "--workers", type=int, default=0, help="동시 처리 개수 (기본: CPU 기준 자동)")
    p4.add_argument("--png-compress", type=int, default=1, help="PNG 압축 레벨 0~9 (기본: 1, 낮을수록 빠름)")
    p4.add_argument("--exclude", nargs="+", action="append", default=[], help="제외할 파일명 prefix 또는 glob 패턴. 예: --exclude S_ CG")

    p5 = sub.add_parser("batch-encode", help="PNG → NLTEX 일괄 변환")
    p5.add_argument("input_dir", help="입력 폴더 (.png 파일들)")
    p5.add_argument("ref_dir", help="레퍼런스 폴더 (원본 .nltx)")
    p5.add_argument("output_dir", help="출력 폴더 (.nltx)")
    p5.add_argument("-j", "--workers", type=int, default=0, help="동시 처리 개수 (기본: CPU 기준 자동)")
    p5.add_argument("--exclude", nargs="+", action="append", default=[], help="제외할 파일명 prefix 또는 glob 패턴. 예: --exclude S_ CG")

    args = parser.parse_args()
    if args.cmd == "decode":
        out = args.output or os.path.splitext(args.input)[0] + ".png"
        nltex_to_png(args.input, out, args.png_compress)
    elif args.cmd == "encode":
        out = args.output or os.path.splitext(args.input)[0] + ".nltx"
        png_to_nltex(args.input, args.ref, out)
    elif args.cmd == "info":
        nltex_info(args.input)
    elif args.cmd == "batch-decode":
        batch_decode(args.input_dir, args.output_dir, args.workers, args.png_compress, args.exclude)
    elif args.cmd == "batch-encode":
        batch_encode(args.input_dir, args.ref_dir, args.output_dir, args.workers, args.exclude)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
