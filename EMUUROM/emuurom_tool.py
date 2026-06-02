import argparse
import csv
import hashlib
import json
import math
import re
import struct
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


MAGIC = b"TIC.CART"
HEADER_SIZE = 16
CODE = 5
TILES = 1
SPRITES = 2
MAP = 4
PALETTE = 12
SCREEN = 18
CHUNK_NAMES = {
    0: "dummy",
    1: "tiles",
    2: "sprites",
    3: "cover_dep",
    4: "map",
    5: "code",
    6: "flags",
    7: "temp2",
    8: "temp3",
    9: "samples",
    10: "waveform",
    11: "temp4",
    12: "palette",
    13: "patterns_dep",
    14: "music",
    15: "patterns",
    16: "code_zip",
    17: "default",
    18: "screen",
    19: "binary",
    20: "lang",
}
FULL_CODE_CANDIDATES = (0x20000, 0x10000)
TILE_BYTES = 32
TILE_COUNT = 256
SHEET_SIZE = 128
SCREEN_W = 240
SCREEN_H = 136
SCREEN_BYTES = SCREEN_W * SCREEN_H // 2
MAP_W = 240
MAP_H = 136
PATCHC_SIZE = 0x4000
PATCHD_SIZE = 0x4000
KRFONT_SOURCE_SIZE = 8
KRFONT_DRAW_SIZE = 8
KRFONT_THRESHOLD = 80
KRFONT_EXTRA_CHARS = "?!.,:;+-/()[]'\""
KRFONT_SKAND_CHARS = "æøÆØäöÄÖʔŋ⌘ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾗﾘﾙﾚﾛﾔﾕﾖﾜｦﾝｬｭｮｯｰﾞﾟ｡､「」"
KRFONT_SKAND_START_TILE = 28
TIC80_SYSTEM_FONT_HEX = (
    "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000c0c0c000c0000000a0a0000000000000a1f0a1f0a000000"
    "1e050e140f00000011080402110000000205160916000000040200000000000008040404080000000204040402000000"
    "04150e150400000000040e0400000000000000060402000000000e000000000000000006060000001008040201000000"
    "0e1b17130e0000000c0e0c0c1e0000000f180e031f0000001f180c190e0000000c0e0b1f080000001f030f180f000000"
    "0e030f130e0000001f180c06030000000e130e130e0000000e131e100e00000006060006060000000606000604020000"
    "0804020408000000000e000e0000000002040804020000001e180c000c0000000e151d010e0000000e13131f13000000"
    "0f130f130f0000000e1303130e0000000f1313130f0000001f030f031f0000001f030f03030000001e031b131e000000"
    "13131f13130000001e0c0c0c1e0000001f18181b0e000000130b070b13000000030303031f0000001b1f1f1511000000"
    "13171f1b130000000e1313130e0000000f13130f030000000e1313130e1000000f13130f130000001e070e1c0f000000"
    "1e0c0c0c0c000000131313130e0000001313130e0400000011151f1f1b00000013130e131300000016161e0c0c000000"
    "1f0c06031f0000000c0404040c00000001020408100000000604040406000000040a110000000000000000001e000000"
    "0204000000000000001e19191e000000030f13130f000000001e07071e000000181e19191e000000000e1b070e000000"
    "1c061f0606000000000e191f180e0000030f1313130000000c000c0c0c00000018001818190e000003130f1313000000"
    "060606061c000000000b1f1515000000000f131313000000000e13130e000000000f13130f030000001e19191e180000"
    "000f130303000000001e071c0f000000061f06061c000000001313130e0000000013130e040000000011151f1b000000"
    "001b0e0e1b0000000019191e180e0000001f0c061f0000000c0406040c000000040404040400000006040c0406000000"
    "00140a0000000000"
)
TIC80_SYSTEM_FONT_BYTES = bytes.fromhex(TIC80_SYSTEM_FONT_HEX)
TEXT_MODULES = {"data/dialogue_en", "scenes/end-grey", "scenes/end-yellow"}
DEFAULT_ORIGINAL_EXE = "emuurom_backup.exe"
DEFAULT_EXTRACT_DIR = "extract"
DEFAULT_FONT = "Galmuri7.ttf"
DEFAULT_TEXT_CSV = "text.csv"
DEFAULT_OUTPUT_EXE = "emuurom.exe"
DEFAULT_OUTPUT_CART = "emuurom_patched.cart.bin"
TEXT_CSV_FIELDS = ["id", "module", "line", "start", "end", "quote", "raw_sha256", "src", "dst"]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_bytes(path):
    return Path(path).read_bytes()


def write_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def read_text(path):
    return Path(path).read_text(encoding="utf-8")


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


def is_hangul(ch):
    cp = ord(ch)
    return 0xAC00 <= cp <= 0xD7A3 or 0x3130 <= cp <= 0x318F or 0x1100 <= cp <= 0x11FF


def is_krfont_char(ch):
    return is_hangul(ch) or ch in KRFONT_EXTRA_CHARS


def is_krfont_mixed_char(ch):
    return ch not in "\r\n\t " and ch != "¤" and ord(ch) >= 0x20


def find_overlay(exe):
    hits = []
    start = 0
    while True:
        off = exe.find(MAGIC, start)
        if off < 0:
            break
        if off + HEADER_SIZE <= len(exe):
            app_size, cart_size = struct.unpack_from("<II", exe, off + 8)
            if app_size == off and app_size + HEADER_SIZE + cart_size == len(exe):
                hits.append((off, app_size, cart_size))
        start = off + 1
    if not hits:
        raise SystemExit("valid TIC.CART overlay was not found")
    return hits[-1]


def extract_cart_from_exe(exe_path):
    exe = read_bytes(exe_path)
    overlay_off, app_size, cart_size = find_overlay(exe)
    comp = exe[overlay_off + HEADER_SIZE:overlay_off + HEADER_SIZE + cart_size]
    cart = zlib.decompress(comp)
    return exe, cart, {
        "overlay_offset": overlay_off,
        "app_size": app_size,
        "cart_size": cart_size,
        "exe_sha256": sha256(exe),
        "cart_sha256": sha256(cart),
    }


def header_for(typ, bank, size, temp=0):
    if size == 0x10000 or size == 0x20000:
        size16 = 0
    else:
        if size < 0 or size > 0xFFFF:
            raise ValueError(f"chunk size cannot be encoded without full-bank padding: {size}")
        size16 = size
    return bytes([(typ & 0x1F) | ((bank & 7) << 5), size16 & 0xFF, (size16 >> 8) & 0xFF, temp & 0xFF])


def decode_header(cart, off):
    b0 = cart[off]
    return {
        "type": b0 & 0x1F,
        "bank": (b0 >> 5) & 7,
        "size16": cart[off + 1] | (cart[off + 2] << 8),
        "temp": cart[off + 3],
    }


def detect_full_code_size(cart, code_off):
    first = decode_header(cart, code_off)
    if first["type"] != CODE or first["size16"] != 0:
        return 0x10000
    for candidate in FULL_CODE_CANDIDATES:
        pos = code_off
        bank = first["bank"]
        ok = True
        while pos < len(cart):
            if pos + 4 > len(cart):
                ok = False
                break
            h = decode_header(cart, pos)
            if h["type"] != CODE or h["bank"] != bank:
                ok = False
                break
            size = candidate if h["size16"] == 0 else h["size16"]
            pos += 4 + size
            bank -= 1
            if bank < 0 and pos != len(cart):
                ok = False
                break
        if ok and pos == len(cart):
            return candidate
    return 0x10000


def parse_cart(cart):
    chunks = []
    pos = 0
    full_code_size = None
    while pos < len(cart):
        if pos + 4 > len(cart):
            raise ValueError(f"truncated chunk header at {pos:#x}")
        h = decode_header(cart, pos)
        if h["type"] == CODE and h["size16"] == 0:
            if full_code_size is None:
                full_code_size = detect_full_code_size(cart, pos)
            size = full_code_size
        else:
            size = h["size16"]
        data_off = pos + 4
        end = data_off + size
        if end > len(cart):
            raise ValueError(f"chunk overflow at {pos:#x}: {end:#x} > {len(cart):#x}")
        chunks.append({
            "index": len(chunks),
            "offset": pos,
            "type": h["type"],
            "name": CHUNK_NAMES.get(h["type"], str(h["type"])),
            "bank": h["bank"],
            "size16": h["size16"],
            "temp": h["temp"],
            "size": size,
            "header": cart[pos:pos + 4],
            "data": cart[data_off:end],
        })
        pos = end
    return chunks, full_code_size or 0x10000


def rebuild_cart(chunks):
    out = bytearray()
    for chunk in chunks:
        out.extend(chunk["header"])
        out.extend(chunk["data"])
    return bytes(out)


def extract_code(chunks):
    code_chunks = [c for c in chunks if c["type"] == CODE]
    if not code_chunks:
        raise SystemExit("code chunks were not found")
    out = bytearray()
    for chunk in code_chunks:
        out.extend(chunk["data"])
    return bytes(out).rstrip(b"\0")


def make_code_chunks(code, full_code_size):
    if not code:
        code = b"\n"
    max_bank = math.ceil(len(code) / full_code_size) - 1
    if max_bank > 7:
        raise SystemExit(f"code is too large for 8 TIC code banks: {len(code)} bytes")
    chunks = []
    pos = 0
    for bank in range(max_bank, -1, -1):
        data = code[pos:pos + full_code_size]
        pos += len(data)
        if len(data) > 0xFFFF and len(data) < full_code_size:
            data = data + b"\0" * (full_code_size - len(data))
        header = header_for(CODE, bank, len(data))
        chunks.append({
            "index": -1,
            "offset": -1,
            "type": CODE,
            "name": "code",
            "bank": bank,
            "size16": 0 if len(data) in (0x10000, 0x20000) else len(data),
            "temp": 0,
            "size": len(data),
            "header": header,
            "data": data,
        })
    return chunks


def find_chunk(chunks, typ, bank):
    for chunk in chunks:
        if chunk["type"] == typ and chunk["bank"] == bank:
            return chunk
    return None


def pad(data, size):
    return data[:size] + b"\0" * max(0, size - len(data))


def trim_chunk(data):
    return data.rstrip(b"\0")


def palette_for_bank(chunks, bank):
    chunk = find_chunk(chunks, PALETTE, bank) or find_chunk(chunks, PALETTE, 0)
    if not chunk:
        return [(0, 0, 0)] * 16
    data = pad(chunk["data"], 48)
    return [tuple(data[i:i + 3]) for i in range(0, 48, 3)]


def get_nibble(data, index):
    b = data[index // 2]
    return (b >> 4) & 0xF if index & 1 else b & 0xF


def set_nibble(data, index, value):
    bi = index // 2
    if index & 1:
        data[bi] = (data[bi] & 0x0F) | ((value & 0xF) << 4)
    else:
        data[bi] = (data[bi] & 0xF0) | (value & 0xF)


def decode_sheet(data, palette):
    data = pad(data, TILE_BYTES * TILE_COUNT)
    img = Image.new("RGBA", (SHEET_SIZE, SHEET_SIZE))
    pix = img.load()
    for tile in range(TILE_COUNT):
        tx = tile % 16
        ty = tile // 16
        base = tile * TILE_BYTES
        for y in range(8):
            for x in range(8):
                color = get_nibble(data[base:base + TILE_BYTES], y * 8 + x)
                r, g, b = palette[color]
                pix[tx * 8 + x, ty * 8 + y] = (r, g, b, 255)
    return img


def nearest_palette_index(rgb, palette):
    r, g, b = rgb[:3]
    best = 0
    best_dist = 1 << 62
    for i, (pr, pg, pb) in enumerate(palette):
        dist = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if dist < best_dist:
            best = i
            best_dist = dist
    return best


def encode_sheet(path, palette):
    img = Image.open(path).convert("RGBA")
    if img.size != (SHEET_SIZE, SHEET_SIZE):
        raise SystemExit(f"{path} must be {SHEET_SIZE}x{SHEET_SIZE}")
    pix = img.load()
    data = bytearray(TILE_BYTES * TILE_COUNT)
    for tile in range(TILE_COUNT):
        tx = tile % 16
        ty = tile // 16
        base = tile * TILE_BYTES
        for y in range(8):
            for x in range(8):
                idx = nearest_palette_index(pix[tx * 8 + x, ty * 8 + y], palette)
                set_nibble(data, base * 2 + y * 8 + x, idx)
    return bytes(data)


def decode_screen(data, palette):
    data = pad(data, SCREEN_BYTES)
    img = Image.new("RGBA", (SCREEN_W, SCREEN_H))
    pix = img.load()
    for y in range(SCREEN_H):
        for x in range(SCREEN_W):
            color = get_nibble(data, y * SCREEN_W + x)
            r, g, b = palette[color]
            pix[x, y] = (r, g, b, 255)
    return img


def encode_screen(path, palette):
    img = Image.open(path).convert("RGBA")
    if img.size != (SCREEN_W, SCREEN_H):
        raise SystemExit(f"{path} must be {SCREEN_W}x{SCREEN_H}")
    pix = img.load()
    data = bytearray(SCREEN_BYTES)
    for y in range(SCREEN_H):
        for x in range(SCREEN_W):
            idx = nearest_palette_index(pix[x, y], palette)
            set_nibble(data, y * SCREEN_W + x, idx)
    return bytes(data)


def update_chunk_data(chunk, data):
    data = trim_chunk(data)
    chunk["data"] = data
    chunk["size"] = len(data)
    chunk["size16"] = len(data)
    chunk["header"] = header_for(chunk["type"], chunk["bank"], len(data), chunk["temp"])


def export_images(chunks, out_dir):
    img_dir = out_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    for bank in range(8):
        palette = palette_for_bank(chunks, bank)
        for typ, label in ((TILES, "tiles"), (SPRITES, "sprites")):
            chunk = find_chunk(chunks, typ, bank)
            if chunk:
                decode_sheet(chunk["data"], palette).save(img_dir / f"bank{bank}_{label}.png")
        screen = find_chunk(chunks, SCREEN, bank)
        if screen:
            decode_screen(screen["data"], palette).save(img_dir / f"bank{bank}_screen.png")


def import_images(chunks, out_dir):
    img_dir = out_dir / "images"
    if not img_dir.exists():
        return []
    changed = []
    for bank in range(8):
        palette = palette_for_bank(chunks, bank)
        for typ, label in ((TILES, "tiles"), (SPRITES, "sprites")):
            path = img_dir / f"bank{bank}_{label}.png"
            chunk = find_chunk(chunks, typ, bank)
            if path.exists() and chunk:
                update_chunk_data(chunk, encode_sheet(path, palette))
                changed.append(path.name)
        path = img_dir / f"bank{bank}_screen.png"
        chunk = find_chunk(chunks, SCREEN, bank)
        if path.exists() and chunk:
            update_chunk_data(chunk, encode_screen(path, palette))
            changed.append(path.name)
    return changed


def line_for_pos(text, pos):
    return text.count("\n", 0, pos) + 1


def module_for_pos(text, pos):
    last = None
    for m in re.finditer(r'\["([^"]+)"\]\s*=\s*function\(\)', text):
        if m.start() > pos:
            break
        last = m.group(1)
    return last or "main"


def long_bracket_end(text, pos):
    if text[pos] != "[":
        return None
    j = pos + 1
    while j < len(text) and text[j] == "=":
        j += 1
    if j < len(text) and text[j] == "[":
        return "]" + "=" * (j - pos - 1) + "]", j + 1
    return None


def decode_lua_short(raw):
    out = []
    i = 0
    while i < len(raw):
        c = raw[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        i += 1
        if i >= len(raw):
            out.append("\\")
            break
        e = raw[i]
        if e == "n":
            out.append("\n")
        elif e == "r":
            out.append("\r")
        elif e == "t":
            out.append("\t")
        elif e == "z":
            i += 1
            while i < len(raw) and raw[i].isspace():
                i += 1
            continue
        elif e in "\\\"'":
            out.append(e)
        elif e.isdigit():
            j = i
            while j < len(raw) and raw[j].isdigit() and j - i < 3:
                j += 1
            out.append(chr(int(raw[i:j], 10)))
            i = j - 1
        else:
            out.append(e)
        i += 1
    return "".join(out)


def lua_quote(value, quote):
    repl = {
        "\\": "\\\\",
        "\n": "\\n",
        "\r": "\\r",
        "\t": "\\t",
        "\0": "\\0",
    }
    body = []
    for ch in value:
        if ch == quote:
            body.append("\\" + quote)
        else:
            body.append(repl.get(ch, ch))
    return quote + "".join(body) + quote


def scan_lua_strings(text):
    rows = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "-" and i + 1 < n and text[i + 1] == "-":
            lb = long_bracket_end(text, i + 2) if i + 2 < n and text[i + 2] == "[" else None
            if lb:
                end_token, body_start = lb
                end = text.find(end_token, body_start)
                i = n if end < 0 else end + len(end_token)
            else:
                end = text.find("\n", i + 2)
                i = n if end < 0 else end + 1
            continue
        if c in ("'", '"'):
            quote = c
            start = i
            i += 1
            body_start = i
            esc = False
            while i < n:
                ch = text[i]
                if esc:
                    esc = False
                    i += 1
                    continue
                if ch == "\\":
                    esc = True
                    i += 1
                    continue
                if ch == quote:
                    raw = text[body_start:i]
                    end = i + 1
                    src = decode_lua_short(raw)
                    rows.append((start, end, quote, raw, src))
                    i = end
                    break
                i += 1
            continue
        if c == "[":
            lb = long_bracket_end(text, i)
            if lb:
                end_token, body_start = lb
                end = text.find(end_token, body_start)
                if end < 0:
                    i += 1
                else:
                    raw = text[body_start:end]
                    rows.append((i, end + len(end_token), "[[", raw, raw))
                    i = end + len(end_token)
                continue
        i += 1
    return rows


def extract_lua_long_assignments(code):
    values = {}
    for m in re.finditer(r"\blocal\s+([A-Za-z_]\w*)\s*=", code):
        name = m.group(1)
        i = m.end()
        while i < len(code) and code[i].isspace():
            i += 1
        lb = long_bracket_end(code, i) if i < len(code) and code[i] == "[" else None
        if not lb:
            continue
        end_token, body_start = lb
        end = code.find(end_token, body_start)
        if end < 0:
            continue
        values[name] = code[body_start:end]
    return values


def read_lua_concat_value(code, pos, variables):
    out = []
    i = pos
    while True:
        while i < len(code) and code[i].isspace():
            i += 1
        if i >= len(code):
            break
        lb = long_bracket_end(code, i) if code[i] == "[" else None
        if lb:
            end_token, body_start = lb
            end = code.find(end_token, body_start)
            if end < 0:
                raise SystemExit("unterminated karaoke song long string")
            out.append(code[body_start:end])
            i = end + len(end_token)
        else:
            m = re.match(r"[A-Za-z_]\w*", code[i:])
            if not m:
                break
            name = m.group(0)
            if name not in variables:
                raise SystemExit(f"unknown karaoke song variable: {name}")
            out.append(variables[name])
            i += len(name)
        while i < len(code) and code[i].isspace():
            i += 1
        if code.startswith("..", i):
            i += 2
            continue
        break
    return "".join(out), i


def extract_karaoke_counts(code):
    songs_start = code.find("songs={")
    if songs_start < 0:
        return {}
    songs_end = code.find("\n\nlosescan={", songs_start)
    if songs_end < 0:
        return {}
    songs_block = code[songs_start:songs_end]
    variables = extract_lua_long_assignments(code)
    counts = {}
    for song in ("BLUE", "RED"):
        m = re.search(rf"\n\s*{song}\s*=\s*\{{", songs_block)
        if not m:
            continue
        field = re.search(r"\bsong\s*=", songs_block[m.end():])
        if not field:
            continue
        value_pos = m.end() + field.end()
        text, _ = read_lua_concat_value(songs_block, value_pos, variables)
        lines = re.findall(r"[^\n]+", text)
        counts[song] = [len(re.findall(r"[^ ]+", line)) for line in lines]
    return counts


def lua_karaoke_counts_table(counts):
    lines = ["krkara_counts={"]
    for song in sorted(counts):
        values = ",".join(str(v) for v in counts[song])
        lines.append(f"\t{song}={{{values}}},")
    lines.append("}")
    return "\n".join(lines)


def mark_karaoke_beats(text):
    lines = []
    for line in text.split("\n"):
        if line.strip():
            lines.append("|".join(line.split()))
        else:
            lines.append(line)
    return "\n".join(lines)


def karaoke_marked_count(line):
    if not line.strip():
        return None
    if "|" in line:
        return len(line.split("|"))
    return len(line.split())


def karaoke_runtime_count(line):
    if not line.strip():
        return None
    return len(re.findall(r"[^ ]+", line))


def karaoke_marked_line_to_runtime(line):
    if "|" not in line:
        return line
    parts = line.split("|")
    out = parts[0].strip(" ")
    for i, part in enumerate(parts[1:], 1):
        prev = parts[i - 1]
        visible_space = prev.endswith(" ") or part.startswith(" ")
        token = part.strip(" ")
        if token == "":
            token = "¤"
        if " " in token:
            raise ValueError(f"unmarked space inside karaoke beat: {line!r}")
        out += (" " if visible_space else "_ ") + token
    return out


def karaoke_dst_to_runtime(dst, src, row_id):
    src_lines = [line for line in src.split("\n") if line.strip()]
    target_i = 0
    out_lines = []
    for line_no, line in enumerate(dst.split("\n"), 1):
        if not line.strip():
            out_lines.append(line)
            continue
        if target_i >= len(src_lines):
            raise SystemExit(f"karaoke line count mismatch at {row_id} line {line_no}")
        src_line = src_lines[target_i]
        target = karaoke_marked_count(src_line)
        target_i += 1
        if line.strip() == "|" and target == 1:
            runtime = "¤_ "
        else:
            try:
                runtime = karaoke_marked_line_to_runtime(line)
            except ValueError as exc:
                raise SystemExit(f"{exc} at {row_id} line {line_no}") from exc
        count = karaoke_runtime_count(runtime)
        if count != target:
            raise SystemExit(
                f"karaoke beat count mismatch at {row_id} line {line_no}\n"
                f"src ({target}): {src_line}\n"
                f"dst ({count}): {line}"
            )
        out_lines.append(runtime)
    return "\n".join(out_lines)


def karaoke_string_starts(code):
    starts = set()
    for name in ("folk", "folk2"):
        m = re.search(rf"\blocal\s+{name}\s*=", code)
        if not m:
            continue
        i = m.end()
        while i < len(code) and code[i].isspace():
            i += 1
        if i < len(code) and long_bracket_end(code, i):
            starts.add(i)
    songs_start = code.find("songs={")
    if songs_start >= 0:
        songs_end = code.find("\n\nlosescan={", songs_start)
        if songs_end < 0:
            songs_end = len(code)
        for m in re.finditer(r"\[=*\[", code[songs_start:songs_end]):
            starts.add(songs_start + m.start())
    return starts


def is_text_module(module):
    return module in TEXT_MODULES


def export_text_csv(code_path, csv_path):
    text = read_text(code_path)
    karaoke_starts = karaoke_string_starts(text)
    rows = []
    for idx, (start, end, quote, raw, src) in enumerate(scan_lua_strings(text), 1):
        module = module_for_pos(text, start)
        if not is_text_module(module) or src == "":
            continue
        rows.append({
            "id": f"t{idx:05d}",
            "module": module,
            "line": line_for_pos(text, start),
            "start": start,
            "end": end,
            "quote": quote,
            "raw_sha256": sha256(text[start:end].encode("utf-8")),
            "src": mark_karaoke_beats(src) if start in karaoke_starts else src,
            "dst": "",
        })
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TEXT_CSV_FIELDS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def import_text_csv(code_path, csv_path, out_path):
    text = read_text(code_path)
    karaoke_starts = karaoke_string_starts(text)
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    patches = []
    for row in rows:
        dst = row.get("dst", "").replace("\r\n", "\n").replace("\r", "\n")
        if not dst:
            continue
        start = int(row["start"])
        end = int(row["end"])
        original = text[start:end]
        if sha256(original.encode("utf-8")) != row["raw_sha256"]:
            raise SystemExit(f"source mismatch at {row['id']} line {row['line']}")
        quote = row["quote"]
        if start in karaoke_starts:
            dst = karaoke_dst_to_runtime(dst, row.get("src", ""), row["id"])
        if quote == "[[":
            replacement = "[[" + dst + "]]"
        else:
            replacement = lua_quote(dst, quote)
        patches.append((start, end, replacement))
    for start, end, replacement in sorted(patches, reverse=True):
        text = text[:start] + replacement + text[end:]
    write_text(out_path, text)
    return len(patches)


def glyph_rows(font_path, ch, size=KRFONT_SOURCE_SIZE, threshold=KRFONT_THRESHOLD):
    font = ImageFont.truetype(str(font_path), size)
    img = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(img)
    draw.fontmode = "1"
    if is_hangul(ch):
        bbox = font.getbbox(ch)
        draw.text((-bbox[0], -bbox[1]), ch, fill=255, font=font)
    else:
        ascent, descent = font.getmetrics()
        baseline = max(0, min(size, size - descent))
        try:
            bbox = font.getbbox(ch, anchor="ls")
            draw.text((-bbox[0], baseline), ch, fill=255, font=font, anchor="ls")
        except TypeError:
            bbox = font.getbbox(ch)
            draw.text((-bbox[0], baseline - bbox[3]), ch, fill=255, font=font)
    rows = []
    max_x = 0
    for y in range(size):
        row = 0
        for x in range(size):
            if img.getpixel((x, y)) >= threshold:
                row |= 1 << (size - 1 - x)
                max_x = max(max_x, x + 1)
        rows.append(row)
    hex_width = math.ceil(size / 4)
    return "".join(f"{row:0{hex_width}x}" for row in rows), min(size, max(1, max_x))


def lua_key(ch):
    return "[" + lua_quote(ch, '"') + "]"


def is_original_font_char(ch):
    return 0x20 <= ord(ch) <= 0x7E and ch not in KRFONT_EXTRA_CHARS


def original_glyph_rows(ch, size=KRFONT_SOURCE_SIZE):
    if size != 8:
        raise SystemExit("original TIC-80 font extraction requires --source-size 8")
    cp = ord(ch)
    if cp <= 0 or cp >= 128:
        raise SystemExit(f"original TIC-80 font only supports ASCII: {ch!r}")
    off = cp * 8
    src_rows = TIC80_SYSTEM_FONT_BYTES[off:off + 8]
    if len(src_rows) != 8:
        raise SystemExit(f"original TIC-80 font row is missing for {ch!r}")
    rows = []
    max_x = 0
    for src_row in src_rows:
        row = 0
        for x in range(8):
            if (src_row >> x) & 1:
                row |= 1 << (7 - x)
                max_x = max(max_x, x + 1)
        rows.append(row)
    return "".join(f"{row:02x}" for row in rows), min(6, max(1, max_x))


def skand_tile_index(ch):
    index = KRFONT_SKAND_CHARS.find(ch)
    return None if index < 0 else KRFONT_SKAND_START_TILE + index


def skand_glyph_rows(ch, chunks, size=KRFONT_SOURCE_SIZE):
    if size != 8:
        raise SystemExit("skand font extraction requires --source-size 8")
    tile = skand_tile_index(ch)
    if tile is None:
        raise SystemExit(f"skand glyph is not registered: {ch!r}")
    tiles = find_chunk(chunks, TILES, 0)
    sprites = find_chunk(chunks, SPRITES, 0)
    if not tiles or not sprites:
        raise SystemExit("bank0 tiles/sprites chunks are required for skand glyph extraction")
    ram = pad(tiles["data"], TILE_BYTES * TILE_COUNT) + pad(sprites["data"], TILE_BYTES * TILE_COUNT)
    bank_orig = 1
    page_orig = 0
    nb_pages = 4
    tile_width = 32
    ptr_size = TILE_BYTES
    iy, ix = divmod(tile, 16)
    xbuffer, xoffset = divmod(ix, nb_pages)
    ptr_offset = (bank_orig * 16 + iy) * 16 + page_orig * 16 // nb_pages + xbuffer
    byte_base = ptr_offset * ptr_size
    offset = xoffset * 8
    rows = []
    max_x = 0
    for y in range(size):
        row = 0
        for x in range(size):
            pix_addr = offset + x + y * tile_width
            value = ram[byte_base + (pix_addr >> 3)]
            if (value >> (pix_addr & 7)) & 1:
                row |= 1 << (size - 1 - x)
                max_x = max(max_x, x + 1)
        rows.append(row)
    return "".join(f"{row:02x}" for row in rows), min(size, max(1, max_x))


def collect_krfont_chars(code):
    chars = set()
    for _, _, _, _, src in scan_lua_strings(code):
        if any(is_hangul(ch) for ch in src):
            chars.update(ch for ch in src if is_krfont_mixed_char(ch))
    if not chars:
        chars.update(ch for ch in code if is_hangul(ch))
    return sorted(chars)


def build_unicode_block(font_path, chars, source_size=KRFONT_SOURCE_SIZE, draw_size=KRFONT_DRAW_SIZE, threshold=KRFONT_THRESHOLD, skand_chunks=None):
    rows = []
    widths = []
    fixeds = []
    for ch in chars:
        fixed_width = None
        if ch in KRFONT_SKAND_CHARS:
            if skand_chunks is None:
                raise SystemExit("skand glyph extraction requires extracted chunks")
            bits, width = skand_glyph_rows(ch, skand_chunks, source_size)
            fixed_width = 6
        elif is_original_font_char(ch):
            bits, width = original_glyph_rows(ch, source_size)
            fixed_width = 6
        else:
            bits, width = glyph_rows(font_path, ch, source_size, threshold)
        rows.append(f"\t{lua_key(ch)}=\"{bits}\",")
        widths.append(f"\t{lua_key(ch)}={width},")
        if fixed_width:
            fixeds.append(f"\t{lua_key(ch)}={fixed_width},")
    hanguls = [f"\t{lua_key(ch)}=true," for ch in chars if is_hangul(ch)]
    hex_width = math.ceil(source_size / 4)
    if draw_size == source_size:
        renderer = [
            "function krrawrect(x,y,scale,color)",
            "\tx=x//1",
            "\ty=y//1",
            "\tfor sy=0,scale-1 do",
            "\t\tlocal py=y+sy",
            "\t\tif py>=0 and py<136 then",
            "\t\t\tfor sx=0,scale-1 do",
            "\t\t\t\tlocal px=x+sx",
            "\t\t\t\tif px>=0 and px<240 then poke4(py*240+px,color)end",
            "\t\t\tend",
            "\t\tend",
            "\tend",
            "end",
            "function krfont(char,x,y,color,fixed,scale)",
            "\tlocal rows=krglyphs[char]",
            "\tif not rows then return 0 end",
            "\tcolor=(color or 15)&15",
            "\tscale=(scale or 1)//1",
            "\tif scale<1 then scale=1 end",
            "\tfor yy=0,krsrch-1 do",
            "\t\tlocal row=tonumber(rows:sub(yy*krhex+1,yy*krhex+krhex),16)",
            "\t\tfor xx=0,krsrcw-1 do",
            "\t\t\tif (row&(1<<(krsrcw-1-xx)))~=0 then krrawrect(x+xx*scale,y+yy*scale,scale,color)end",
            "\t\tend",
            "\tend",
            "\tlocal w=krwidth[char] or krsrcw",
            "\treturn fixed and (krfixed and krfixed[char] or krsrcw)*scale or (w+1)*scale",
            "end",
        ]
    else:
        renderer = [
            "function krrawrect(x,y,scale,color)",
            "\tx=x//1",
            "\ty=y//1",
            "\tfor sy=0,scale-1 do",
            "\t\tlocal py=y+sy",
            "\t\tif py>=0 and py<136 then",
            "\t\t\tfor sx=0,scale-1 do",
            "\t\t\t\tlocal px=x+sx",
            "\t\t\t\tif px>=0 and px<240 then poke4(py*240+px,color)end",
            "\t\t\tend",
            "\t\tend",
            "\tend",
            "end",
            "function krfont(char,x,y,color,fixed,scale)",
            "\tlocal rows=krglyphs[char]",
            "\tif not rows then return 0 end",
            "\tcolor=(color or 15)&15",
            "\tscale=(scale or 1)//1",
            "\tif scale<1 then scale=1 end",
            "\tlocal srcw=krwidth[char] or krsrcw",
            "\tlocal outw=ceil(srcw*krdraw/krsrcw)",
            "\tfor yy=0,krdraw-1 do",
            "\t\tlocal sy=min(krsrch-1,yy*krsrch//krdraw)",
            "\t\tlocal row=tonumber(rows:sub(sy*krhex+1,sy*krhex+krhex),16)",
            "\t\tfor xx=0,outw-1 do",
            "\t\t\tlocal sx=min(krsrcw-1,xx*krsrcw//outw)",
            "\t\t\tif (row&(1<<(krsrcw-1-sx)))~=0 then krrawrect(x+xx*scale,y+yy*scale,scale,color)end",
            "\t\tend",
            "\tend",
            "\treturn fixed and (krfixed and krfixed[char] or krdraw+1)*scale or (outw+1)*scale",
            "end",
        ]
    return "\n".join([
        f"krsrcw={source_size}",
        f"krsrch={source_size}",
        f"krdraw={draw_size}",
        f"krhex={hex_width}",
        "krglyphs={",
        *rows,
        "}",
        "krwidth={",
        *widths,
        "}",
        "krfixed={",
        *fixeds,
        "}",
        "krhanguls={",
        *hanguls,
        "}",
        *renderer,
    ])


LUA_CURSE_WIDTH_HELPERS = r'''function kr_curse_charbytes(txt,pos)
	local b=strbyte(txt,pos)
	if not b then return 0 end
	if b<128 then return 1 elseif b<224 then return 2 elseif b<240 then return 3 else return 4 end
end
function kr_curse_char_width(c,small)
	if krglyphs and krglyphs[c]then
		if krfixed and krfixed[c]then return krfixed[c]end
		return (krdraw and krdraw~=krsrcw)and krdraw+1 or krsrcw or 8
	end
	if skands and skands[c]then return small and 4 or 6 end
	local b=strbyte(c,1)
	if b and b>=224 then return 8 end
	return small and 4 or 6
end
function kr_curse_text(txt,e,small)
	local s=""
	local sprs={288,304,320}
	e=e or d
	local p=1
	local nchar=0
	while p<=strlen(txt)do
		local n=kr_curse_charbytes(txt,p)
		local c=strsub(txt,p,p+n-1)
		if c=="{"then
			local j=txt:find("}",p,true)
			if j then
				s=s..strsub(txt,p,j)
				p=j+1
			else
				s=s..c
				p=p+n
			end
		elseif c==" "or c=="\t"then
			s=s..c
			p=p+n
		else
			s=s.."{spr:"..(sprs[e%3+1]+e%4)..":0}"
			local extra=kr_curse_char_width(c,small)-(small and 8 or 6)
			if extra~=0 then s=s.."{"..extra.."}"end
			e=e+1
			nchar=nchar+1
			p=p+n
		end
	end
	d=d+nchar
	return s
end
'''


LUA_NEWLINES_FUNCTION = LUA_CURSE_WIDTH_HELPERS + r'''function newlines(s,w_pix,linecount)
	local function charbytes(txt,pos)
		local b=strbyte(txt,pos)
		if not b then return 0 end
		if b<128 then return 1 elseif b<224 then return 2 elseif b<240 then return 3 else return 4 end
	end
	local function nextchar(txt,pos)
		local n=charbytes(txt,pos)
		return strsub(txt,pos,pos+n-1),n
	end
	if s:len()==0 then s="..." end
	local krmode=false
	if krhanguls then
		local p=1
		while p<=strlen(s)do
			local c,n=nextchar(s,p)
			if krhanguls[c]then krmode=true break end
			p=p+n
		end
	end
	local tokens={}
	local i=1
	while i<=strlen(s)do
		local c,n=nextchar(s,i)
		if c=="\r"then
			i=i+n
		elseif c=="\n"then
			to(tokens,{k="break",v="\n"})
			i=i+n
		elseif c==" "or c=="\t"then
			to(tokens,{k="space",v=" "})
			i=i+n
		elseif c=="{"then
			local j=s:find("}",i,true)
			if j then
				local tok=strsub(s,i,j)
				local body=strsub(tok,2,#tok-1)
				if body:find("spr")then
					local run=tok
					local p=j+1
					while p<=strlen(s)and strsub(s,p,p)=="{"do
						local j2=s:find("}",p,true)
						if not j2 then break end
						local tok2=strsub(s,p,j2)
						local body2=strsub(tok2,2,#tok2-1)
						if not body2:find("spr")then break end
						run=run..tok2
						p=j2+1
					end
					to(tokens,{k="sprite_run",v=run})
					i=p
				else
					to(tokens,{k="special",v=tok})
					i=j+1
				end
			else
				to(tokens,{k="word",v=c})
				i=i+n
			end
		elseif strsub(s,i,i+2)=="[s]"then
			to(tokens,{k="ctrl",v="[s]"})
			i=i+3
		else
			local b=strbyte(c,1)
			if b and b>=224 then
				to(tokens,{k="word",v=c})
				i=i+n
			else
				local j=i
				while j<=strlen(s)do
					local c2,n2=nextchar(s,j)
					if c2=="\r"or c2=="\n"or c2==" "or c2=="\t"or c2=="{"or strsub(s,j,j+2)=="[s]"then break end
					local b2=strbyte(c2,1)
					if b2 and b2>=224 then break end
					j=j+n2
				end
				if j==i then
					to(tokens,{k="word",v=c})
					i=i+n
				else
					to(tokens,{k="word",v=strsub(s,i,j-1)})
					i=j
				end
			end
		end
	end
	local function char_width(c,small)
		if krmode and krglyphs and krglyphs[c]then
			if krfixed and krfixed[c]then return small and 4 or krfixed[c] end
			return (krdraw and krdraw~=krsrcw)and krdraw+1 or krsrcw or 8
		end
		if skands and skands[c]then return small and 4 or 6 end
		local b=strbyte(c,1)
		if b and b>=224 then return 8 end
		return small and 4 or 6
	end
	local function text_width(txt,small)
		local w=0
		local p=1
		while p<=strlen(txt)do
			local c,n=nextchar(txt,p)
			w=w+char_width(c,small)
			p=p+n
		end
		return w
	end
	local function wrd_value(body)
		local i=body:find(":")
		if not i then return nil end
		local j=body:find(":",i+1)or(#body+1)
		return strsub(body,i+1,j-1)
	end
	local function sprite_run_width(tok,small)
		local w=0
		local p=1
		while p<=strlen(tok)do
			local j=tok:find("}",p,true)
			if not j then break end
			w=w+(small and 8 or 6)
			p=j+1
		end
		return w,tok
	end
	local function special_width(tok,small)
		local body=strsub(tok,2,#tok-1)
		local number=body:getNumber()
		if number and body==number then
			local n=tonumber(number)
			if small then
				n=n/6*4
				tok="{"..tostring(n).."}"
			end
			return n,tok
		end
		if body:find("wrd")then
			local wrd=wrd_value(body)
			if wrd then return text_width(wrd,small),tok end
		end
		if body:find("spr")then return small and 8 or 6,tok end
		return small and 4 or 6,tok
	end
	local lines={}
	local line={}
	local line_w=0
	local small=false
	local small_left=0
	local function flush_line()
		while #line>0 and line[#line]==" "do del(line)end
		local out=table.concat(line)
		if out==""then out=" "end
		to(lines,out)
		line={}
		line_w=0
		if small_left>0 then
			small_left=small_left-1
			if small_left==0 then small=false end
		end
	end
	local function add_piece(txt,w)
		to(line,txt)
		line_w=line_w+w
	end
	local function add_word(txt)
		local p=1
		while p<=strlen(txt)do
			local c,n=nextchar(txt,p)
			local cw=char_width(c,small)
			if line_w>0 and line_w+cw>w_pix then flush_line()end
			add_piece(c,cw)
			p=p+n
		end
	end
	for _,token in ipairs(tokens)do
		if token.k=="break"then
			flush_line()
		elseif token.k=="ctrl"then
			to(line,token.v)
			small=true
			small_left=4
		elseif token.k=="space"then
			local sw=small and 4 or 6
			if line_w>0 then
				if line_w+sw>w_pix then flush_line()else add_piece(" ",sw)end
			end
		else
			local w,out
			if token.k=="special"then w,out=special_width(token.v,small)
			elseif token.k=="sprite_run"then w,out=sprite_run_width(token.v,small)
			else out=token.v w=text_width(out,small)end
			if line_w>0 and line_w+w>w_pix then
				flush_line()
				if token.k=="special"then w,out=special_width(token.v,small)
				elseif token.k=="sprite_run"then w,out=sprite_run_width(token.v,small)
				else out=token.v w=text_width(out,small)end
			end
			if w>w_pix and token.k=="word"then add_word(out)else add_piece(out,w)end
		end
	end
	if #line>0 or #lines==0 then flush_line()end
	if linecount then
		while #lines<linecount do to(lines," ")end
	end
	return table.concat(lines,"\n")
end'''


def patch_newlines_function(code):
    pattern = r"\nfunction newlines\(s,\s*w_pix,\s*linecount\).*?\nfunction questionmarks\(n\)"
    replacement = "\n" + LUA_NEWLINES_FUNCTION + "\nfunction questionmarks(n)"
    code, count = re.subn(pattern, lambda _: replacement, code, count=1, flags=re.S)
    if count == 0:
        raise SystemExit("newlines function was not found")
    return code


def patch_dex_body_wrap_width(code):
    old = 'newlines(F.text or "_",132,4)'
    new = 'newlines(F.text or "_",128,4)'
    if new in code:
        return code
    if old not in code:
        raise SystemExit("monster dex body wrap width call was not found")
    return code.replace(old, new, 1)


def patch_kylt_blurb_nil_entity(code):
    old = 'text= E.alinen and "\\n{rune:"..run.."}\\n"..run2..alitxt'
    new = 'text= E and E.alinen and "\\n{rune:"..run.."}\\n"..run2..alitxt'
    if new in code:
        return code
    if old not in code:
        raise SystemExit("kylt blurb alinen branch was not found")
    return code.replace(old, new, 1)


def patch_line_buffet_nil_entity(code):
    replacements = [
        ('if E.type=="kylt"and words[1]then', 'if E and E.type=="kylt"and words[1]then'),
        ('if E.type=="kylt"then to(words,1,"~")end', 'if E and E.type=="kylt"then to(words,1,"~")end'),
    ]
    for old, new in replacements:
        if new in code:
            continue
        if old not in code:
            raise SystemExit(f"line buffet nil-entity pattern was not found: {old}")
        code = code.replace(old, new, 1)
    return code


def patch_line_buffet_curse_text(code):
    old = '\t\tif #line.words==0 then to(line.words,{text=""})end\n\t\tline.text=nil'
    new = '\t\tif #line.words==0 then to(line.words,{text=""})end\n\t\tline.curseText=line.text\n\t\tline.text=nil'
    if new in code:
        return code
    if old not in code:
        raise SystemExit("line buffet text cleanup block was not found")
    return code.replace(old, new, 1)


KARAOKE_GETLINE_CURRTOQUEUE = '''	getLine=function(E,line)
		local linetxt=E.txtLineStrs[line]:gsub("_ ","")
		local w=getcenterwidth(linetxt,false,1,false)
		return linetxt,w
	end,
	currToQueue=function(E,t)
		local linetxt,w=E:getLine(E.currLine)
		local linetxt2,w2
		if E.currLine%2==1 then linetxt2,w2=E:getLine(E.currLine+1)end
		local word=E.txtLines[E.currLine][E.curr_i]
		E.txtQueue[E.currLine]=E.txtQueue[E.currLine]or{t=t,line=E.currLine,w=0}
		local lineObj=E.txtQueue[E.currLine]
		local part=E.kara[E.part]
		local cleanword=word:gsub("_","")
		local step=getcenterwidth(cleanword,false,1,false)
		if cleanword~="¤"and not word:find("_")then step=step+getcenterwidth(" ",false,1,false)end
		local y0,y1=part.noImg and 68-16 or 8,part.noImg and 16 or 106
		to(lineObj,{
			word=cleanword,
			t=0,
			x=lineObj.w+20,
			y=(E.currLine+3)%4//2*y1+y0+(E.currLine+1)%2*8,
			line=E.currLine,
			i=E.curr_i,
			upd=function(W,line)
				W.t=W.t+1
				if line.t==line.t_kill then rm(E.txtQueue[W.line],W)end
			end,
			drw=function(W,line)
				local x=W.x+100-w/2
				local col=part.noImg and"GRAY"
				if W.i==1 and W.line%2==1 and not col then
					local x2=120-w2/2
					utf8printFade(linetxt,x,W.y,"in",W.t,1,false,1,false,false,"DRK")
					utf8printFade(linetxt2,x2,W.y+8,"in",W.t,1,false,1,false,false,"DRK")
				end
				if line.t_fade==nil or line.t<line.t_fade then
					utf8printFade(W.word,x,W.y,"in",W.t,1,false,1,false,false,col)
				else
					utf8printFade(W.word,x,W.y,"out",line.t-line.t_fade,4,false,1,false,false,col)
				end
			end,
		})
		lineObj.w=lineObj.w+step
	end,'''


def patch_karaoke_renderer(code, base_code=None):
    counts = extract_karaoke_counts(base_code or code)
    if not counts:
        return code
    code = re.sub(r"\nkrkara_counts=\{.*?\nCS\.scenes\.endred2=", "\nCS.scenes.endred2=", code, count=1, flags=re.S)
    pattern = r"\n\tgetLine=function\(E,line\).*?\n\tupd=function\(E\)"
    code, count = re.subn(pattern, "\n" + KARAOKE_GETLINE_CURRTOQUEUE + "\n\tupd=function(E)", code, count=1, flags=re.S)
    if count == 0:
        raise SystemExit("endred2 karaoke queue block was not found")
    return code


FINALBOSS_UPD_PREFIX = '''upd=function(E)
\tif E.phase==5 and W.endSeq.i<8 and E.scn.i>=maxi[E.type]-4 then W.endSeq:go(8)end
\tif E.phase<5 and E.scn.i>=maxi[E.type] -4 -(5-E.phase)*40 then--200'''


FINALBOSS_UPD_PREFIX_TEST_MODE = '''upd=function(E)
\tif E.scn.i>0 then
\t\tE.phase=5
\t\tE.scn.i=maxi[E.type]
\t\tif W.endSeq.i<8.5 then W.endSeq:go(8.5)end
\t\treturn
\tend
\tif E.phase==5 and W.endSeq.i<8 and E.scn.i>=maxi[E.type]-4 then W.endSeq:go(8)end
\tif E.phase<5 and E.scn.i>=maxi[E.type] -4 -(5-E.phase)*40 then--200'''


TITLE_LOAD_PREFIX = '''\t\t\telseif mode=="load"or mode=="new"then
\t\t\t\tcam.setRoom(13)
\t\t\t\tCS:exit()'''


TITLE_LOAD_PREFIX_TEST_MODE = '''\t\t\telseif mode=="load"or mode=="new"then
\t\t\t\tif mode=="load"then
\t\t\t\t\tcam.setRoom(13)
\t\t\t\t\tCS:exit()
\t\t\t\t\tW.ending="RED"
\t\t\t\t\tW.pending=nil
\t\t\t\t\tno_sfx()
\t\t\t\t\tMUS:startSpecial(-1)
\t\t\t\t\tstartGam:enter(0,0,4,"endred2")
\t\t\t\t\treturn
\t\t\t\tend
\t\t\t\tcam.setRoom(13)
\t\t\t\tCS:exit()'''


TITLE_LOAD_PREFIX_TEST_BOSS = '''\t\t\telseif mode=="load"or mode=="new"then
\t\t\t\tif mode=="load"then
\t\t\t\t\tcam.setRoom(13)
\t\t\t\t\tCS:exit()
\t\t\t\t\tstartGam:enter(0,0,0,nil,function()
\t\t\t\t\t\tcam.setRoom(88)
\t\t\t\t\t\tskipToMenu[1]=false
\t\t\t\t\t\tW.pending=nil
\t\t\t\t\t\tP:setLoc(232*8,132*8)
\t\t\t\t\t\tcam.setMan(P)
\t\t\t\t\t\tLYN.roomdat[1]=LYN.finalCaveForm+1
\t\t\t\t\t\tLYN.roomdat[2][LYN.finalCaveForm+1]=false
\t\t\t\t\t\ttoForm(LYN,LYN.finalCaveForm+1,nil,nil,true)
\t\t\t\t\t\tLYN:setroom()
\t\t\t\t\t\tlocal entr=D:entry(LYN)
\t\t\t\t\t\tentr.entrdat[1]=true
\t\t\t\t\t\tif entr.forms[LYN.form]then entr.forms[LYN.form].found=false end
\t\t\t\t\t\tif LYN.EDATS and LYN.EDATS[LYN.form]then LYN.EDATS[LYN.form][1]=false end
\t\t\t\t\t\tLYN:unHide()
\t\t\t\t\t\tcam.curateEnts()
\t\t\t\t\t\tW.endSeq:go(1)
\t\t\t\t\t\tTS:delay(30,function()
\t\t\t\t\t\t\tPs.activE=LYN
\t\t\t\t\t\t\tD:scnDone(LYN,entr)
\t\t\t\t\t\t\tif LYN.onScanDone then LYN:onScanDone()end
\t\t\t\t\t\tend)
\t\t\t\t\tend)
\t\t\t\t\treturn
\t\t\t\tend
\t\t\t\tcam.setRoom(13)
\t\t\t\tCS:exit()'''


def patch_test_mode(code):
    changed = False
    if FINALBOSS_UPD_PREFIX not in code:
        if FINALBOSS_UPD_PREFIX_TEST_MODE not in code:
            raise SystemExit("final boss update block was not found")
    elif FINALBOSS_UPD_PREFIX_TEST_MODE not in code:
        code = code.replace(FINALBOSS_UPD_PREFIX, FINALBOSS_UPD_PREFIX_TEST_MODE, 1)
        changed = True
    if TITLE_LOAD_PREFIX not in code:
        if TITLE_LOAD_PREFIX_TEST_MODE not in code:
            raise SystemExit("title load branch was not found")
    elif TITLE_LOAD_PREFIX_TEST_MODE not in code:
        code = code.replace(TITLE_LOAD_PREFIX, TITLE_LOAD_PREFIX_TEST_MODE, 1)
        changed = True
    return code


def patch_test_boss_mode(code):
    if TITLE_LOAD_PREFIX_TEST_BOSS not in code:
        if TITLE_LOAD_PREFIX not in code:
            raise SystemExit("title load branch was not found")
        code = code.replace(TITLE_LOAD_PREFIX, TITLE_LOAD_PREFIX_TEST_BOSS, 1)
    return code


PC_CURSOR_OLD = '''			if has({"adding","clearing",},E.state) or E.t%60>30 then
				local w_char=LANG==LANGS.JP and 8 or 6 --todo ei toimi vielä
				rect(
					x+6+(E.CRS_X-1)*w_char,
					y-2+8*E.CRS_Y,
					6,8,E.inputCol or 11)
			end'''


PC_CURSOR_NEW = '''			if has({"adding","clearing",},E.state) or E.t%60>30 then
				local cursorText=E.SCREEN[E.CRS_Y]and E.SCREEN[E.CRS_Y].text or""
				local cursorW=getcenterwidth(cursorText,true,1,false)
				rect(
					x+6+cursorW,
					y-2+8*E.CRS_Y,
					6,8,E.inputCol or 11)
			end'''


def patch_pc_cursor_renderer(code):
    if PC_CURSOR_NEW in code:
        return code
    if PC_CURSOR_OLD not in code:
        raise SystemExit("PC cursor draw block was not found")
    return code.replace(PC_CURSOR_OLD, PC_CURSOR_NEW, 1)


def patch_dex_body_word_colors(code):
    old = (
        "\t\tlocal color=15\n"
        "\t\tfor _,word in ipairs(words)do\n"
        "\t\t\tlocal prettyword=word:gsub(\"%'s\",\"\"):gsub(\"[%c%p%s]\",\"\")\n"
        "\t\t\tcolor=line.mode~=\"nocol\"and prettyword:len()>1\n"
        "\t\t\t\tand prettyword==prettyword:upper()\n"
        "\t\t\t\tand not tonumber(prettyword)\n"
        "\t\t\t\tand 14 or line.col\n"
    )
    new = (
        "\t\tlocal color=E and E.type==\"mon\"and i>F.skipline and 14 or 15\n"
        "\t\tfor _,word in ipairs(words)do\n"
        "\t\t\tlocal prettyword=word:gsub(\"%'s\",\"\"):gsub(\"[%c%p%s]\",\"\")\n"
        "\t\t\tcolor=line.mode~=\"nocol\"and prettyword:len()>1\n"
        "\t\t\t\tand prettyword==prettyword:upper()\n"
        "\t\t\t\tand not tonumber(prettyword)\n"
        "\t\t\t\tand 14 or line.col or color\n"
    )
    if new in code:
        return code
    unguarded = new.replace("E and E.type", "E.type")
    if unguarded in code:
        return code.replace(unguarded, new, 1)
    if old not in code:
        raise SystemExit("dex blurb word color block was not found")
    return code.replace(old, new, 1)


def patch_dex_curse_widths(code):
    old = (
        "\t\t\tif showPartial>0 then\n"
        "\t\t\t\tprintWord(utf8sub(word.text,1,showPartial),rowLetterX)\n"
        "\t\t\t\tprintWord(curse(wordlen-showPartial,j+showPartial),rowLetterX+showPartial*6)\n"
        "\t\t\t\trowLetterX=rowLetterX+printWord(word.text..\" \",240)\n"
        "\t\t\telse\n"
        "\t\t\t\tlocal text=showCurse and notCurly and curse(wordlen,j)or word.text\n"
        "\t\t\t\trowLetterX=rowLetterX+printWord(text..\" \",rowLetterX)\n"
        "\t\t\tend"
    )
    new = (
        "\t\t\tif showPartial>0 then\n"
        "\t\t\t\tlocal prefix=utf8sub(word.text,1,showPartial)\n"
        "\t\t\t\tlocal suffix=utf8sub(word.text,showPartial+1)\n"
        "\t\t\t\tprintWord(prefix,rowLetterX)\n"
        "\t\t\t\tprintWord(kr_curse_text(suffix,j+showPartial,smallfont),rowLetterX+getcenterwidth(prefix,true,1,smallfont))\n"
        "\t\t\t\trowLetterX=rowLetterX+printWord(word.text..\" \",240)\n"
        "\t\t\telse\n"
        "\t\t\t\tlocal text=showCurse and notCurly and kr_curse_text(word.text,j,smallfont)or word.text\n"
        "\t\t\t\trowLetterX=rowLetterX+printWord(text..\" \",rowLetterX)\n"
        "\t\t\tend"
    )
    if new in code:
        return code
    if old not in code:
        raise SystemExit("dex curse text draw block was not found")
    return code.replace(old, new, 1)


def patch_dex_page_clamp(code):
    old = "\tif F.numPages==1 then D.page=1 end"
    new = (
        "\tif F.numPages==1 then D.page=1 end\n"
        "\tif D.page<1 then D.page=1 end\n"
        "\tif D.page>F.numPages then D.page=F.numPages end"
    )
    if new in code:
        return code
    if old not in code:
        raise SystemExit("dex page clamp insertion point was not found")
    return code.replace(old, new, 1)


def patch_dex_static_curse_lines(code):
    old = (
        "\t\tlocal rowLetterX=0\n"
        "\n"
        "\t\tfor j,word in ipairs(blrbLine.words)do\n"
    )
    new = (
        "\t\tlocal rowLetterX=0\n"
        "\t\tif showCurse and not curseAnim and blrbLine.curseText then\n"
        "\t\t\tutf8print(kr_curse_text(blrbLine.curseText,i,smallfont),x+line_x+1,y+line_y+1,line_color,true,1,false,smallfont)\n"
        "\t\t\treturn line_x,line_y+8,char\n"
        "\t\tend\n"
        "\n"
        "\t\tfor j,word in ipairs(blrbLine.words)do\n"
    )
    if new in code:
        return code
    if old not in code:
        raise SystemExit("dex row word loop block was not found")
    return code.replace(old, new, 1)


def patch_unicode_renderer(code, font_path, source_size=KRFONT_SOURCE_SIZE, draw_size=KRFONT_DRAW_SIZE, threshold=KRFONT_THRESHOLD, base_code=None, skand_chunks=None):
    code = re.sub(r"\nkrglyphs=\{.*?\nend\n", "\n", code, count=1, flags=re.S)
    code = re.sub(r"\n(?:krw=\d+\nkrh=\d+\n|krsrcw=\d+\nkrsrch=\d+\nkrdraw=\d+\n)krhex=\d+\n", "\n", code, count=1)
    old_branches = [
        '\t\telseif krglyphs and krglyphs[char]then\n\t\t\tx=x+krfont(char,x,y,color,fixed,scale)\n',
        '\t\telseif krglyphs and krglyphs[char] and (krmode or krhanguls[char])then\n\t\t\tx=x+krfont(char,x,y,color,fixed,scale)\n',
        '\t\telseif ((krglyphs and krglyphs[char])or(krsys and krsys[char])) and (krmode or krhanguls[char])then\n\t\t\tx=x+krfont(char,x,y,color,fixed,scale)\n',
    ]
    for old in old_branches:
        code = code.replace(old, "")
    mode = (
        "\tlocal krmode=false\n"
        "\tif krhanguls then\n"
        "\t\tlocal krtxt=fulltext or text\n"
        "\t\tlocal krpos=1\n"
        "\t\twhile krpos<=strlen(krtxt)do\n"
        "\t\t\tlocal krlen=utf8charbytes(krtxt,krpos)\n"
        "\t\t\tlocal krc=strsub(krtxt,krpos,krpos+krlen-1)\n"
        "\t\t\tif krhanguls[krc]then krmode=true break end\n"
        "\t\t\tkrpos=krpos+krlen\n"
        "\t\tend\n"
        "\tend\n"
    )
    if "local krmode=false" not in code:
        needle = "\tlocal w=0\n"
        if needle not in code:
            raise SystemExit("utf8print width initialization was not found")
        code = code.replace(needle, mode + needle, 1)
    branch = '\t\telseif krglyphs and krglyphs[char] and (krmode or krhanguls[char])then\n\t\t\tx=x+krfont(char,x,y,color,fixed,scale)\n'
    if "krglyphs and krglyphs[char] and (krmode or krhanguls[char])" not in code:
        needle = "\t\telseif skands[char]then"
        if needle not in code:
            raise SystemExit("utf8print skands branch was not found")
        code = code.replace(needle, branch + needle, 1)
    chars = collect_krfont_chars(code)
    if chars:
        marker = "skands=utf8enumerate(skandstr)\n"
        if marker not in code:
            raise SystemExit("skandstr initialization was not found")
        block = build_unicode_block(font_path, chars, source_size, draw_size, threshold, skand_chunks)
        code = code.replace(marker, marker + block + "\n", 1)
    code = patch_newlines_function(code)
    code = patch_dex_body_wrap_width(code)
    code = patch_kylt_blurb_nil_entity(code)
    code = patch_line_buffet_nil_entity(code)
    code = patch_line_buffet_curse_text(code)
    code = patch_dex_curse_widths(code)
    code = patch_dex_page_clamp(code)
    code = patch_dex_static_curse_lines(code)
    code = patch_karaoke_renderer(code, base_code)
    code = patch_pc_cursor_renderer(code)
    code = patch_dex_body_word_colors(code)
    return code, len(chars)


def write_manifest(out_dir, info, chunks, full_code_size):
    manifest = dict(info)
    manifest["full_code_size"] = full_code_size
    manifest["chunks"] = [
        {
            "index": c["index"],
            "offset": c["offset"],
            "type": c["type"],
            "name": c["name"],
            "bank": c["bank"],
            "size16": c["size16"],
            "temp": c["temp"],
            "size": c["size"],
            "sha256": sha256(c["data"]),
        }
        for c in chunks
    ]
    write_text(out_dir / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))


def align(value, alignment):
    return (value + alignment - 1) // alignment * alignment


def section_name(raw):
    return raw[:8].rstrip(b"\0").decode("ascii", "replace")


def add_pe_sections_to_base(base, section_specs):
    data = bytearray(base)
    peoff = struct.unpack_from("<I", data, 0x3C)[0]
    if data[peoff:peoff + 4] != b"PE\0\0":
        raise SystemExit("input is not a PE file")
    file_header = peoff + 4
    section_count = struct.unpack_from("<H", data, file_header + 2)[0]
    opt_size = struct.unpack_from("<H", data, file_header + 16)[0]
    optional = peoff + 24
    magic = struct.unpack_from("<H", data, optional)[0]
    if magic != 0x20B:
        raise SystemExit("only PE32+ x64 is supported")
    section_alignment = struct.unpack_from("<I", data, optional + 32)[0]
    file_alignment = struct.unpack_from("<I", data, optional + 36)[0]
    size_of_headers = struct.unpack_from("<I", data, optional + 60)[0]
    section_table = optional + opt_size
    new_count = section_count + len(section_specs)
    new_table_end = section_table + new_count * 40
    raw_starts = []
    raw_end = 0
    va_end = 0
    names = set()
    for i in range(section_count):
        off = section_table + i * 40
        name = section_name(bytes(data[off:off + 8]))
        names.add(name)
        virtual_size, virtual_address, raw_size, raw_ptr = struct.unpack_from("<IIII", data, off + 8)
        if raw_ptr:
            raw_starts.append(raw_ptr)
            raw_end = max(raw_end, raw_ptr + raw_size)
        va_end = max(va_end, virtual_address + align(max(virtual_size, raw_size), section_alignment))
    first_raw = min(raw_starts) if raw_starts else size_of_headers
    if new_table_end > size_of_headers or new_table_end > first_raw:
        raise SystemExit("not enough PE header slack for new section headers")
    raw_ptr = align(raw_end, file_alignment)
    virtual_address = align(va_end, section_alignment)
    for spec in section_specs:
        if spec["name"] in names:
            raise SystemExit(f"section already exists: {spec['name']}")
        raw_size = align(spec["size"], file_alignment)
        virtual_size = spec["size"]
        if len(data) < raw_ptr:
            data.extend(b"\0" * (raw_ptr - len(data)))
        data.extend(b"\0" * raw_size)
        off = section_table + section_count * 40
        name = spec["name"].encode("ascii")[:8].ljust(8, b"\0")
        data[off:off + 8] = name
        struct.pack_into("<IIIIIIHHI", data, off + 8, virtual_size, virtual_address, raw_size, raw_ptr, 0, 0, 0, 0, spec["chars"])
        names.add(spec["name"])
        section_count += 1
        raw_ptr = align(raw_ptr + raw_size, file_alignment)
        virtual_address = align(virtual_address + virtual_size, section_alignment)
    struct.pack_into("<H", data, file_header + 2, section_count)
    struct.pack_into("<I", data, optional + 56, virtual_address)
    struct.pack_into("<I", data, optional + 64, 0)
    return bytes(data)


def add_patch_sections(exe, patchc_size=PATCHC_SIZE, patchd_size=PATCHD_SIZE):
    overlay_off, app_size, cart_size = find_overlay(exe)
    base = exe[:app_size]
    comp = exe[overlay_off + HEADER_SIZE:overlay_off + HEADER_SIZE + cart_size]
    specs = [
        {"name": ".patchc", "size": patchc_size, "chars": 0x60000020},
        {"name": ".patchd", "size": patchd_size, "chars": 0xE0000040},
    ]
    new_base = add_pe_sections_to_base(base, specs)
    header = MAGIC + struct.pack("<II", len(new_base), len(comp))
    return new_base + header + comp


def text_csv_path(args, out_dir):
    if getattr(args, "text_csv", None):
        return Path(args.text_csv)
    if getattr(args, "dir", None) or getattr(args, "out", None):
        return out_dir / DEFAULT_TEXT_CSV
    return Path(DEFAULT_TEXT_CSV)


def cart_path(args, out_dir, use_default=False):
    if getattr(args, "cart", None):
        return Path(args.cart)
    if use_default:
        return out_dir / DEFAULT_OUTPUT_CART
    return None


def cmd_extract(args):
    exe_path = Path(args.exe or args.original_exe)
    out_dir = Path(args.out or args.extract_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    exe, cart, info = extract_cart_from_exe(exe_path)
    chunks, full_code_size = parse_cart(cart)
    code = extract_code(chunks)
    write_bytes(out_dir / "emuurom.cart.bin", cart)
    write_bytes(out_dir / "code.lua", code)
    write_manifest(out_dir, info, chunks, full_code_size)
    csv_path = text_csv_path(args, out_dir)
    count = export_text_csv(out_dir / "code.lua", csv_path)
    export_images(chunks, out_dir)
    print(f"extracted cart={len(cart)} bytes code={len(code)} bytes text_rows={count} full_code_size={full_code_size} text_csv={csv_path}")


def load_extracted(out_dir):
    out_dir = Path(out_dir)
    cart = read_bytes(out_dir / "emuurom.cart.bin")
    manifest = json.loads(read_text(out_dir / "manifest.json"))
    chunks, full_code_size = parse_cart(cart)
    return out_dir, cart, manifest, chunks, full_code_size


def replace_code_chunks(chunks, code, full_code_size):
    first_code = next((i for i, c in enumerate(chunks) if c["type"] == CODE), None)
    if first_code is None:
        raise SystemExit("code chunk insertion point was not found")
    kept = [c for c in chunks[:first_code] if c["type"] != CODE]
    return kept + make_code_chunks(code, full_code_size)


def apply_text(out_dir, csv_path):
    src = out_dir / "code.lua"
    dst = out_dir / "code_patched.lua"
    count = import_text_csv(src, csv_path, dst)
    print(f"applied text rows={count} -> {dst}")
    return dst, count


def patch_unicode(out_dir, font_path, source_size, draw_size, threshold, test_mode=False, test_boss=False):
    if test_mode and test_boss:
        raise SystemExit("--test-mode and --test-boss cannot be used together")
    code_path = out_dir / "code_patched.lua"
    if not code_path.exists():
        code_path = out_dir / "code.lua"
    base_path = out_dir / "code.lua"
    base_code = read_text(base_path) if base_path.exists() else None
    _, _, _, chunks, _ = load_extracted(out_dir)
    code, count = patch_unicode_renderer(read_text(code_path), font_path, source_size, draw_size, threshold, base_code, chunks)
    if test_mode:
        code = patch_test_mode(code)
    if test_boss:
        code = patch_test_boss_mode(code)
    dst = out_dir / "code_unicode.lua"
    write_text(dst, code)
    mode = " test_mode=on" if test_mode else " test_boss=on" if test_boss else ""
    print(f"patched unicode glyphs={count} source_size={source_size} draw_size={draw_size} threshold={threshold}{mode} -> {dst}")
    return dst, count


def build_output(exe_path, out_dir, out_path, cart_out, import_image_changes):
    out_dir, cart, manifest, chunks, full_code_size = load_extracted(out_dir)
    code_path = out_dir / "code_unicode.lua"
    if not code_path.exists():
        code_path = out_dir / "code_patched.lua"
    if not code_path.exists():
        code_path = out_dir / "code.lua"
    code = read_bytes(code_path)
    chunks = replace_code_chunks(chunks, code, full_code_size)
    changed_images = import_images(chunks, out_dir) if import_image_changes else []
    new_cart = rebuild_cart(chunks)
    if cart_out:
        write_bytes(cart_out, new_cart)
    exe = read_bytes(exe_path)
    app_size = manifest["app_size"]
    overlay_off, current_app_size, _ = find_overlay(exe)
    if overlay_off != app_size or current_app_size != app_size:
        raise SystemExit("input exe does not match the extracted appSize")
    comp = zlib.compress(new_cart, 9)
    header = MAGIC + struct.pack("<II", app_size, len(comp))
    patched = exe[:app_size] + header + comp
    write_bytes(out_path, patched)
    print(f"built {out_path} cart={len(new_cart)} compressed={len(comp)} images={len(changed_images)}")
    return out_path


def cmd_apply_text(args):
    out_dir = Path(args.dir or args.extract_dir)
    apply_text(out_dir, text_csv_path(args, out_dir))


def cmd_patch_unicode(args):
    out_dir = Path(args.dir or args.extract_dir)
    patch_unicode(out_dir, Path(args.font), int(args.source_size, 0), int(args.draw_size, 0), int(args.threshold, 0), args.test_mode, args.test_boss)


def cmd_build(args):
    out_dir = Path(args.dir or args.extract_dir)
    build_output(Path(args.exe or args.original_exe), out_dir, Path(args.out or args.output_exe), cart_path(args, out_dir), args.import_images)


def cmd_import(args):
    out_dir = Path(args.extract_dir)
    apply_text(out_dir, Path(args.text_csv))
    patch_unicode(out_dir, Path(args.font), int(args.source_size, 0), int(args.draw_size, 0), int(args.threshold, 0), args.test_mode, args.test_boss)
    if not args.no_build:
        build_output(Path(args.original_exe), out_dir, Path(args.output_exe), cart_path(args, out_dir, True), not args.no_import_images)


def cmd_info(args):
    exe, cart, info = extract_cart_from_exe(args.exe)
    chunks, full_code_size = parse_cart(cart)
    code = extract_code(chunks)
    print(json.dumps({
        **info,
        "uncompressed_cart_size": len(cart),
        "code_size": len(code),
        "full_code_size": full_code_size,
        "chunk_count": len(chunks),
        "code_chunks": [{"bank": c["bank"], "size": c["size"], "size16": c["size16"]} for c in chunks if c["type"] == CODE],
    }, ensure_ascii=False, indent=2))


def cmd_add_sections(args):
    exe = read_bytes(args.exe)
    patched = add_patch_sections(exe, int(args.patchc_size, 0), int(args.patchd_size, 0))
    write_bytes(args.out, patched)
    print(f"added .patchc/.patchd -> {args.out} size={len(patched)}")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info")
    p.add_argument("exe")
    p.set_defaults(func=cmd_info)
    p = sub.add_parser("extract")
    p.add_argument("exe", nargs="?")
    p.add_argument("out", nargs="?")
    p.add_argument("--original-exe", default=DEFAULT_ORIGINAL_EXE)
    p.add_argument("--extract-dir", default=DEFAULT_EXTRACT_DIR)
    p.add_argument("--text-csv")
    p.set_defaults(func=cmd_extract)
    p = sub.add_parser("apply-text")
    p.add_argument("dir", nargs="?")
    p.add_argument("--extract-dir", default=DEFAULT_EXTRACT_DIR)
    p.add_argument("--text-csv")
    p.set_defaults(func=cmd_apply_text)
    p = sub.add_parser("patch-unicode")
    p.add_argument("dir", nargs="?")
    p.add_argument("font", nargs="?", default=DEFAULT_FONT)
    p.add_argument("--extract-dir", default=DEFAULT_EXTRACT_DIR)
    p.add_argument("--source-size", default=str(KRFONT_SOURCE_SIZE))
    p.add_argument("--draw-size", default=str(KRFONT_DRAW_SIZE))
    p.add_argument("--threshold", default=str(KRFONT_THRESHOLD))
    p.add_argument("--test-mode", action="store_true")
    p.add_argument("--test-boss", action="store_true")
    p.set_defaults(func=cmd_patch_unicode)
    p = sub.add_parser("build")
    p.add_argument("exe", nargs="?")
    p.add_argument("dir", nargs="?")
    p.add_argument("out", nargs="?")
    p.add_argument("--original-exe", default=DEFAULT_ORIGINAL_EXE)
    p.add_argument("--extract-dir", default=DEFAULT_EXTRACT_DIR)
    p.add_argument("--output-exe", default=DEFAULT_OUTPUT_EXE)
    p.add_argument("--cart")
    p.add_argument("--import-images", action="store_true")
    p.set_defaults(func=cmd_build)
    p = sub.add_parser("import")
    p.add_argument("--original-exe", default=DEFAULT_ORIGINAL_EXE)
    p.add_argument("--extract-dir", default=DEFAULT_EXTRACT_DIR)
    p.add_argument("--text-csv", default=DEFAULT_TEXT_CSV)
    p.add_argument("--font", default=DEFAULT_FONT)
    p.add_argument("--output-exe", default=DEFAULT_OUTPUT_EXE)
    p.add_argument("--cart")
    p.add_argument("--no-build", action="store_true")
    p.add_argument("--no-import-images", action="store_true")
    p.add_argument("--source-size", default=str(KRFONT_SOURCE_SIZE))
    p.add_argument("--draw-size", default=str(KRFONT_DRAW_SIZE))
    p.add_argument("--threshold", default=str(KRFONT_THRESHOLD))
    p.add_argument("--test-mode", action="store_true")
    p.add_argument("--test-boss", action="store_true")
    p.set_defaults(func=cmd_import)
    p = sub.add_parser("add-sections")
    p.add_argument("exe")
    p.add_argument("out")
    p.add_argument("--patchc-size", default=hex(PATCHC_SIZE))
    p.add_argument("--patchd-size", default=hex(PATCHD_SIZE))
    p.set_defaults(func=cmd_add_sections)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
