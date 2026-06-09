from dataclasses import dataclass
from pathlib import Path
import argparse
import struct

from PIL import Image
from PIL.PngImagePlugin import PngInfo


RESOURCE_BASE = 0x00A20BD0
RING_SIZE = 0x400
RING_START = 0x3BE
MAX_MATCH = 0x42
MIN_MATCH = 3
FORMAT_I4 = 0x0005


@dataclass(frozen=True)
class ResourceEntry:
    resource_id: int
    relative_offset: int
    span_size: int
    decompressed_size: int

    @property
    def compressed_offset(self) -> int:
        return RESOURCE_BASE + self.relative_offset + 4

    @property
    def size_word_offset(self) -> int:
        return RESOURCE_BASE + self.relative_offset

    @property
    def compressed_capacity(self) -> int:
        return self.span_size - 4


class ResourceTable:
    def __init__(self, rom: bytes):
        self.rom = rom
        self.count = struct.unpack_from(">I", rom, RESOURCE_BASE)[0]

    @classmethod
    def from_rom(cls, rom: bytes) -> "ResourceTable":
        return cls(rom)

    def entry(self, resource_id: int) -> ResourceEntry:
        if resource_id < 0 or resource_id >= self.count:
            raise IndexError(resource_id)
        table_offset = RESOURCE_BASE + 4 + resource_id * 8
        relative_offset, span_size = struct.unpack_from(">II", self.rom, table_offset)
        size_word_offset = RESOURCE_BASE + relative_offset
        decompressed_size = struct.unpack_from(">I", self.rom, size_word_offset)[0]
        return ResourceEntry(resource_id, relative_offset, span_size, decompressed_size)

    def extract(self, resource_id: int) -> bytes:
        entry = self.entry(resource_id)
        if entry.compressed_capacity < 0:
            raise ValueError(f"resource {resource_id:04x} has invalid span")
        src = self.rom[entry.compressed_offset : entry.compressed_offset + entry.compressed_capacity]
        decoded, _ = lz_decode(src, entry.decompressed_size)
        return decoded


def lz_decode(src: bytes, decompressed_size: int) -> tuple[bytes, int]:
    ring = bytearray(RING_SIZE)
    ring_pos = RING_START
    flags = 0
    out = bytearray()
    pos = 0
    while len(out) < decompressed_size:
        flags >>= 1
        test = flags
        if (flags & 0x100) == 0:
            if pos >= len(src):
                raise EOFError("missing flag byte")
            test = src[pos]
            pos += 1
            flags = test | 0xFF00
        if test & 1:
            if pos >= len(src):
                raise EOFError("missing literal byte")
            value = src[pos]
            pos += 1
            out.append(value)
            ring[ring_pos] = value
            ring_pos = (ring_pos + 1) & 0x3FF
        else:
            if pos + 2 > len(src):
                raise EOFError("missing match bytes")
            b1 = src[pos]
            b2 = src[pos + 1]
            pos += 2
            source = b1 | ((b2 & 0xC0) << 2)
            length = (b2 & 0x3F) + MIN_MATCH
            for offset in range(length):
                value = ring[(source + offset) & 0x3FF]
                out.append(value)
                ring[ring_pos] = value
                ring_pos = (ring_pos + 1) & 0x3FF
                if len(out) >= decompressed_size:
                    break
        flags &= 0xFFFF
    return bytes(out), pos


def lz_encode(data: bytes) -> bytes:
    out = bytearray()
    index: dict[bytes, list[int]] = {}
    pos = 0
    flag_pos = -1
    flag_mask = 0
    tokens_in_group = 8
    while pos < len(data):
        if tokens_in_group == 8:
            flag_pos = len(out)
            out.append(0)
            flag_mask = 1
            tokens_in_group = 0
        source_pos, length = _find_match(data, pos, index)
        if length >= MIN_MATCH and pos + 1 < len(data):
            _, next_length = _find_match(data, pos + 1, index)
            if next_length > length + 1:
                length = 0
        if length >= MIN_MATCH:
            encoded_pos = source_pos & 0x3FF
            out.append(encoded_pos & 0xFF)
            out.append(((encoded_pos >> 2) & 0xC0) | (length - MIN_MATCH))
            for add_pos in range(pos, pos + length):
                _index_position(index, data, add_pos)
            pos += length
        else:
            out[flag_pos] |= flag_mask
            out.append(data[pos])
            _index_position(index, data, pos)
            pos += 1
        flag_mask <<= 1
        tokens_in_group += 1
    return bytes(out)


def patch_resource_in_place(rom: bytes, resource_id: int, decoded: bytes) -> bytes:
    table = ResourceTable.from_rom(rom)
    entry = table.entry(resource_id)
    if table.extract(resource_id) == decoded:
        return rom
    encoded = lz_encode(decoded)
    if len(encoded) > entry.compressed_capacity:
        raise ValueError(
            f"resource {resource_id:04x} encoded size 0x{len(encoded):x} exceeds capacity 0x{entry.compressed_capacity:x}"
        )
    patched = bytearray(rom)
    struct.pack_into(">I", patched, entry.size_word_offset, len(decoded))
    start = entry.compressed_offset
    end = start + entry.compressed_capacity
    patched[start:end] = encoded + bytes(entry.compressed_capacity - len(encoded))
    return bytes(patched)


def patch_resource_to_pool(rom: bytes, resource_id: int, decoded: bytes, pool_offset: int, span_size: int | None = None) -> bytes:
    if pool_offset % 4:
        raise ValueError(f"resource pool offset 0x{pool_offset:x} must be 4-byte aligned")
    table = ResourceTable.from_rom(rom)
    table.entry(resource_id)
    encoded = lz_encode(decoded)
    payload = struct.pack(">I", len(decoded)) + encoded
    if span_size is None:
        span_size = len(payload)
    if span_size < len(payload):
        raise ValueError(f"resource payload size 0x{len(payload):x} exceeds requested span 0x{span_size:x}")
    end_offset = pool_offset + span_size
    if pool_offset < 0 or end_offset > len(rom):
        raise ValueError(f"resource pool write 0x{pool_offset:x}-0x{end_offset:x} exceeds ROM size 0x{len(rom):x}")
    if any(value not in (0x00, 0xFF) for value in rom[pool_offset:end_offset]):
        raise ValueError(f"resource pool write 0x{pool_offset:x}-0x{end_offset:x} overlaps non-padding bytes")
    relative_offset = pool_offset - RESOURCE_BASE
    if relative_offset < 0:
        raise ValueError(f"resource pool offset 0x{pool_offset:x} is before resource base 0x{RESOURCE_BASE:x}")
    patched = bytearray(rom)
    table_offset = RESOURCE_BASE + 4 + resource_id * 8
    struct.pack_into(">II", patched, table_offset, relative_offset, span_size)
    patched[pool_offset:end_offset] = payload + bytes(span_size - len(payload))
    return bytes(patched)


def fmt5_resource_to_image(decoded: bytes, visible_palette: bool = False) -> Image.Image:
    fmt, width, height, _ = _read_fmt5_header(decoded)
    if fmt != FORMAT_I4:
        raise ValueError(f"unsupported texture format 0x{fmt:04x}")
    pixel_count = width * height
    pixels = decoded[8 : 8 + ((pixel_count + 1) // 2)]
    indices = bytearray()
    for value in pixels:
        indices.append(value >> 4)
        if len(indices) < pixel_count:
            indices.append(value & 0x0F)
    image = Image.frombytes("P", (width, height), bytes(indices))
    image.putpalette(_visible_palette() if visible_palette else _gray16_palette())
    return image


def image_to_fmt5_resource(image: Image.Image, flags: int = 0) -> bytes:
    width, height = image.size
    indices = _image_indices(image)
    packed = bytearray()
    for pos in range(0, len(indices), 2):
        first = indices[pos]
        second = indices[pos + 1] if pos + 1 < len(indices) else 0
        packed.append((first << 4) | second)
    return struct.pack(">HHHH", FORMAT_I4, width, height, flags) + bytes(packed)


def export_fmt5_png(decoded: bytes, output: Path, visible_palette: bool = False) -> None:
    _, _, _, flags = _read_fmt5_header(decoded)
    image = fmt5_resource_to_image(decoded, visible_palette=visible_palette)
    metadata = PngInfo()
    metadata.add_text("srw64_format", f"0x{FORMAT_I4:04x}")
    metadata.add_text("srw64_flags", f"0x{flags:04x}")
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, pnginfo=metadata)


def fmt5_resource_from_png(path: Path) -> bytes:
    with Image.open(path) as image:
        flags = int(image.info.get("srw64_flags", "0"), 0)
        return image_to_fmt5_resource(image, flags=flags)


def _find_match(data: bytes, pos: int, index: dict[bytes, list[int]]) -> tuple[int, int]:
    remaining = len(data) - pos
    if remaining < MIN_MATCH:
        return 0, 0
    best_source = 0
    best_length = 0
    max_length = min(MAX_MATCH, remaining)
    if pos < 0x42 and data[pos : pos + MIN_MATCH] == b"\x00\x00\x00":
        zero_length = 0
        while zero_length < max_length and data[pos + zero_length] == 0:
            zero_length += 1
        best_length = zero_length
        best_source = 0
    key = data[pos : pos + MIN_MATCH]
    candidates = index.get(key, [])
    while candidates and pos - candidates[0] > RING_SIZE:
        del candidates[0]
    for candidate in reversed(candidates[-1024:]):
        distance = pos - candidate
        if distance <= 0 or distance > RING_SIZE:
            continue
        length = 0
        while length < max_length and data[candidate + length] == data[pos + length]:
            length += 1
        if length > best_length:
            best_length = length
            best_source = (RING_START + candidate) & 0x3FF
            if best_length == max_length:
                break
    return best_source, best_length


def _read_fmt5_header(decoded: bytes) -> tuple[int, int, int, int]:
    if len(decoded) < 8:
        raise ValueError("resource is too small for a texture header")
    fmt, width, height, flags = struct.unpack_from(">HHHH", decoded, 0)
    expected_size = 8 + ((width * height + 1) // 2)
    if fmt == FORMAT_I4 and len(decoded) != expected_size:
        raise ValueError(f"fmt5 texture size 0x{len(decoded):x} does not match expected 0x{expected_size:x}")
    return fmt, width, height, flags


def _gray16_palette() -> list[int]:
    values: list[int] = []
    for index in range(256):
        value = index * 17 if index < 16 else 0
        values.extend([value, value, value])
    return values


def _visible_palette() -> list[int]:
    values = [0, 0, 0]
    for _ in range(1, 256):
        values.extend([255, 255, 255])
    return values


def _image_indices(image: Image.Image) -> bytes:
    if image.mode == "P":
        data = image.tobytes()
        over = max(data) if data else 0
        if over > 0x0F:
            raise ValueError(f"fmt5 palette index 0x{over:x} exceeds 4bpp range")
        return data
    gray = image.convert("L").tobytes()
    return bytes(min(15, (value + 8) // 17) for value in gray)


def _index_position(index: dict[bytes, list[int]], data: bytes, pos: int) -> None:
    if pos + MIN_MATCH > len(data):
        return
    key = data[pos : pos + MIN_MATCH]
    values = index.setdefault(key, [])
    values.append(pos)
    if len(values) > 512:
        del values[:256]


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    info = subparsers.add_parser("info")
    info.add_argument("rom", type=Path)
    info.add_argument("resource_id", type=lambda value: int(value, 0))
    extract = subparsers.add_parser("extract")
    extract.add_argument("rom", type=Path)
    extract.add_argument("resource_id", type=lambda value: int(value, 0))
    extract.add_argument("output", type=Path)
    export_png = subparsers.add_parser("export-png")
    export_png.add_argument("rom", type=Path)
    export_png.add_argument("resource_id", type=lambda value: int(value, 0))
    export_png.add_argument("output", type=Path)
    export_png.add_argument("--visible-palette", action="store_true")
    patch_png = subparsers.add_parser("patch-png")
    patch_png.add_argument("rom", type=Path)
    patch_png.add_argument("resource_id", type=lambda value: int(value, 0))
    patch_png.add_argument("png", type=Path)
    patch_png.add_argument("output_rom", type=Path)
    args = parser.parse_args()
    rom = args.rom.read_bytes()
    table = ResourceTable.from_rom(rom)
    if args.command == "info":
        entry = table.entry(args.resource_id)
        print(f"id=0x{entry.resource_id:04x}")
        print(f"relative_offset=0x{entry.relative_offset:08x}")
        print(f"span_size=0x{entry.span_size:08x}")
        print(f"decompressed_size=0x{entry.decompressed_size:08x}")
        print(f"compressed_capacity=0x{entry.compressed_capacity:08x}")
        return 0
    if args.command == "extract":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(table.extract(args.resource_id))
        return 0
    if args.command == "export-png":
        export_fmt5_png(table.extract(args.resource_id), args.output, visible_palette=args.visible_palette)
        return 0
    if args.command == "patch-png":
        patched = patch_resource_in_place(rom, args.resource_id, fmt5_resource_from_png(args.png))
        args.output_rom.parent.mkdir(parents=True, exist_ok=True)
        args.output_rom.write_bytes(patched)
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
