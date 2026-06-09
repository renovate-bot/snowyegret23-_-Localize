from dataclasses import dataclass
from pathlib import Path
import argparse
import csv
import os
from collections import Counter
import struct
import sys

from PIL import Image, ImageDraw, ImageFont

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.srw64_resources import (
    ResourceTable,
    fmt5_resource_to_image,
    image_to_fmt5_resource,
    patch_resource_in_place,
)


TEXT_BASE_TABLE_FILE = 0x05AB60
TEXT_TABLE_COUNT = 20
TEXT_ENTRY_HEADER_SIZE = 8
FONT_LINE_HEIGHT = 14
FONT_RESOURCE_LOW = 0
FONT_RESOURCE_HIGH = 1


@dataclass(frozen=True)
class TextEntry:
    table_id: int
    text_id: int
    table_base: int
    relative_offset: int
    byte_size: int
    data: bytes

    @property
    def header(self) -> bytes:
        return self.data[:TEXT_ENTRY_HEADER_SIZE]

    @property
    def glyphs(self) -> list[int]:
        glyphs: list[int] = []
        for offset in range(TEXT_ENTRY_HEADER_SIZE, len(self.data), 2):
            glyphs.append(struct.unpack_from(">h", self.data, offset)[0])
        return glyphs


class TextTable:
    def __init__(self, rom: bytes):
        self.rom = rom
        self.table_bases = list(struct.unpack_from(">" + "I" * TEXT_TABLE_COUNT, rom, TEXT_BASE_TABLE_FILE))

    @classmethod
    def from_rom(cls, rom: bytes) -> "TextTable":
        return cls(rom)

    def entry_count(self, table_id: int) -> int:
        if table_id < 0 or table_id >= len(self.table_bases):
            raise IndexError(table_id)
        table_base = self.table_bases[table_id]
        if table_base <= 0 or table_base >= len(self.rom):
            raise ValueError(f"invalid text table base 0x{table_base:08x}")
        return struct.unpack_from(">I", self.rom, table_base)[0]

    def entry(self, table_id: int, text_id: int) -> TextEntry:
        if table_id < 0 or table_id >= len(self.table_bases):
            raise IndexError(table_id)
        table_base = self.table_bases[table_id]
        if table_base <= 0 or table_base >= len(self.rom):
            raise ValueError(f"invalid text table base 0x{table_base:08x}")
        if text_id < 0 or text_id >= self.entry_count(table_id):
            raise IndexError(text_id)
        descriptor_offset = table_base + 4 + text_id * 8
        relative_offset, byte_size = struct.unpack_from(">II", self.rom, descriptor_offset)
        data_offset = table_base + relative_offset
        data = self.rom[data_offset : data_offset + byte_size]
        if len(data) != byte_size:
            raise ValueError(f"text entry {table_id}:{text_id} exceeds ROM size")
        return TextEntry(table_id, text_id, table_base, relative_offset, byte_size, data)


def glyph_usage(rom: bytes) -> Counter[int]:
    table = TextTable.from_rom(rom)
    usage: Counter[int] = Counter()
    for table_id in range(len(table.table_bases)):
        table_base = table.table_bases[table_id]
        if table_base <= 0 or table_base >= len(rom):
            continue
        for text_id in range(table.entry_count(table_id)):
            entry = table.entry(table_id, text_id)
            for glyph in entry.glyphs:
                if glyph >= 0:
                    usage[glyph] += 1
    return usage


def free_glyphs(usage: Counter[int], start: int, end: int) -> list[int]:
    return [glyph for glyph in range(start, end + 1) if glyph not in usage]


def patch_text_entry_glyphs(rom: bytes, table_id: int, text_id: int, glyphs: list[int]) -> bytes:
    entry = TextTable.from_rom(rom).entry(table_id, text_id)
    body_size = entry.byte_size - TEXT_ENTRY_HEADER_SIZE
    if body_size != len(glyphs) * 2:
        raise ValueError(f"glyph byte size 0x{len(glyphs) * 2:x} must equal entry body size 0x{body_size:x}")
    patched = bytearray(rom)
    _write_text_entry_glyphs(patched, entry, glyphs)
    return bytes(patched)


def patch_text_entry_to_pool(rom: bytes, table_id: int, text_id: int, glyphs: list[int], pool_offset: int) -> bytes:
    if pool_offset % 2:
        raise ValueError(f"text pool offset 0x{pool_offset:x} must be 2-byte aligned")
    entry = TextTable.from_rom(rom).entry(table_id, text_id)
    patched = bytearray(rom)
    _write_text_entry_to_pool(patched, entry, glyphs, pool_offset)
    return bytes(patched)


def _write_text_entry_glyphs(patched: bytearray, entry: TextEntry, glyphs: list[int]) -> None:
    offset = entry.table_base + entry.relative_offset + TEXT_ENTRY_HEADER_SIZE
    for index, glyph in enumerate(glyphs):
        struct.pack_into(">h", patched, offset + index * 2, glyph)


def _write_text_entry_to_pool(patched: bytearray, entry: TextEntry, glyphs: list[int], pool_offset: int) -> None:
    if pool_offset % 2:
        raise ValueError(f"text pool offset 0x{pool_offset:x} must be 2-byte aligned")
    data = entry.header + b"".join(struct.pack(">h", glyph) for glyph in glyphs)
    end_offset = pool_offset + len(data)
    if pool_offset < 0 or end_offset > len(patched):
        raise ValueError(f"text pool write 0x{pool_offset:x}-0x{end_offset:x} exceeds ROM size 0x{len(patched):x}")
    if any(value not in (0x00, 0xFF) for value in patched[pool_offset:end_offset]):
        raise ValueError(f"text pool write 0x{pool_offset:x}-0x{end_offset:x} overlaps non-padding bytes")
    relative_offset = pool_offset - entry.table_base
    if relative_offset < 0:
        raise ValueError(f"text pool offset 0x{pool_offset:x} is before table base 0x{entry.table_base:x}")
    descriptor_offset = entry.table_base + 4 + entry.text_id * 8
    struct.pack_into(">II", patched, descriptor_offset, relative_offset, len(data))
    patched[pool_offset:end_offset] = data


def export_text_table(
    rom: bytes,
    table_id: int,
    csv_path: Path,
    preview_dir: Path | None = None,
    limit: int | None = None,
    scale: int = 1,
) -> int:
    table = TextTable.from_rom(rom)
    entry_count = table.entry_count(table_id)
    if limit is not None:
        entry_count = min(entry_count, limit)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    font_low, font_high = _load_font_images(rom)
    if preview_dir is not None:
        preview_dir.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["table_id", "text_id", "byte_size", "glyph_count", "glyphs", "preview_path"],
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        for text_id in range(entry_count):
            entry = table.entry(table_id, text_id)
            preview_path = ""
            if preview_dir is not None:
                preview_name = f"table_{table_id:02d}_text_{text_id:05d}.png"
                preview_file = preview_dir / preview_name
                _render_glyphs_with_fonts(font_low, font_high, entry.glyphs, scale=scale).save(preview_file)
                preview_path = os.path.relpath(preview_file, csv_path.parent).replace("\\", "/")
            writer.writerow(
                {
                    "table_id": table_id,
                    "text_id": text_id,
                    "byte_size": entry.byte_size,
                    "glyph_count": len(entry.glyphs),
                    "glyphs": ",".join(str(glyph) for glyph in entry.glyphs),
                    "preview_path": preview_path,
                }
            )
    return entry_count


def export_text_tables(
    rom: bytes,
    csv_dir: Path,
    preview_dir: Path | None = None,
    limit: int | None = None,
    scale: int = 1,
) -> dict[int, int]:
    table = TextTable.from_rom(rom)
    counts: dict[int, int] = {}
    for table_id, table_base in enumerate(table.table_bases):
        if table_base <= 0 or table_base >= len(rom):
            continue
        try:
            table.entry_count(table_id)
        except ValueError:
            continue
        table_preview_dir = preview_dir / f"table_{table_id:02d}" if preview_dir is not None else None
        counts[table_id] = export_text_table(
            rom,
            table_id,
            csv_dir / f"table_{table_id:02d}.csv",
            preview_dir=table_preview_dir,
            limit=limit,
            scale=scale,
        )
    return counts


def load_glyph_map(path: Path) -> dict[int, str]:
    mapping: dict[int, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row_index, row in enumerate(csv.DictReader(handle), start=2):
            glyph_id_text = row.get("glyph_id", "").strip()
            char = row.get("char", "")
            if not glyph_id_text or not char:
                continue
            mapping[int(glyph_id_text, 0)] = char
    return mapping


def load_unknown_glyph_policy(path: Path) -> dict[int, str]:
    policy: dict[int, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row_index, row in enumerate(csv.DictReader(handle), start=2):
            glyph_id_text = row.get("glyph_id", "").strip()
            action = row.get("action", "").strip()
            if not glyph_id_text or action != "preserve_token":
                continue
            glyph_id = int(glyph_id_text, 0)
            if glyph_id in policy:
                raise ValueError(f"row {row_index}: duplicate unknown glyph policy for {glyph_id}")
            policy[glyph_id] = row.get("kind", "").strip() or "preserve_token"
    return policy


def parse_unknown_glyph_ids(value: str) -> list[int]:
    glyphs: list[int] = []
    for piece in value.split(","):
        text = piece.strip()
        if not text:
            continue
        if text.startswith("<g") and text.endswith(">"):
            text = text[2:-1]
        glyphs.append(int(text, 0))
    return glyphs


def decode_glyphs_to_text(glyphs: list[int], glyph_map: dict[int, str]) -> str:
    parts: list[str] = []
    for glyph in glyphs:
        if glyph == -1:
            break
        if glyph in (-2, -3):
            parts.append("\n")
        elif glyph == 0:
            parts.append(" ")
        elif glyph in glyph_map:
            parts.append(glyph_map[glyph])
        elif glyph >= 0:
            parts.append(f"<g{glyph}>")
    return "".join(parts)


def export_translation_table(
    rom: bytes,
    table_id: int,
    csv_path: Path,
    glyph_map_path: Path,
    limit: int | None = None,
) -> int:
    table = TextTable.from_rom(rom)
    glyph_map = load_glyph_map(glyph_map_path)
    entry_count = table.entry_count(table_id)
    if limit is not None:
        entry_count = min(entry_count, limit)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["key", "src", "dst", "table_id", "text_id", "byte_size", "glyph_count", "glyphs", "unknown_glyphs"],
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        for text_id in range(entry_count):
            entry = table.entry(table_id, text_id)
            unknown = [glyph for glyph in entry.glyphs if glyph >= 0 and glyph != 0 and glyph not in glyph_map]
            writer.writerow(
                {
                    "key": f"t{table_id:02d}_{text_id:05d}",
                    "src": decode_glyphs_to_text(entry.glyphs, glyph_map),
                    "dst": "",
                    "table_id": table_id,
                    "text_id": text_id,
                    "byte_size": entry.byte_size,
                    "glyph_count": len(entry.glyphs),
                    "glyphs": ",".join(str(glyph) for glyph in entry.glyphs),
                    "unknown_glyphs": ",".join(str(glyph) for glyph in unknown),
                }
            )
    return entry_count


def export_translation_tables(
    rom: bytes,
    csv_path: Path,
    glyph_map_path: Path,
    limit: int | None = None,
) -> int:
    table = TextTable.from_rom(rom)
    glyph_map = load_glyph_map(glyph_map_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["key", "src", "dst", "table_id", "text_id", "byte_size", "glyph_count", "glyphs", "unknown_glyphs"],
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        for table_id, table_base in enumerate(table.table_bases):
            if table_base <= 0 or table_base >= len(rom):
                continue
            try:
                entry_count = table.entry_count(table_id)
            except ValueError:
                continue
            if limit is not None:
                entry_count = min(entry_count, limit)
            for text_id in range(entry_count):
                entry = table.entry(table_id, text_id)
                unknown = [glyph for glyph in entry.glyphs if glyph >= 0 and glyph != 0 and glyph not in glyph_map]
                writer.writerow(
                    {
                        "key": f"t{table_id:02d}_{text_id:05d}",
                        "src": decode_glyphs_to_text(entry.glyphs, glyph_map),
                        "dst": "",
                        "table_id": table_id,
                        "text_id": text_id,
                        "byte_size": entry.byte_size,
                        "glyph_count": len(entry.glyphs),
                        "glyphs": ",".join(str(glyph) for glyph in entry.glyphs),
                        "unknown_glyphs": ",".join(str(glyph) for glyph in unknown),
                    }
                )
                total += 1
    return total


def text_patch_unit_count(text: str) -> int:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return len(normalized)


def classify_translation_rows(
    csv_path: Path,
    output_path: Path,
    unknown_glyph_policy_path: Path | None = None,
    allow_text_expansion: bool = False,
) -> Counter[str]:
    counts: Counter[str] = Counter()
    token_policy = load_unknown_glyph_policy(unknown_glyph_policy_path) if unknown_glyph_policy_path is not None else {}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as source, output_path.open(
        "w", encoding="utf-8-sig", newline=""
    ) as target:
        reader = csv.DictReader(source)
        writer = csv.DictWriter(
            target,
            fieldnames=[
                "key",
                "src",
                "dst",
                "table_id",
                "text_id",
                "byte_size",
                "slot_capacity",
                "dst_glyph_count",
                "remaining_slots",
                "src_has_unknown",
                "status",
                "reason",
                "unknown_glyphs",
            ],
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        for row in reader:
            dst = row.get("dst", "")
            slot_capacity = int(row.get("glyph_count", "0") or "0", 0)
            dst_glyph_count = text_patch_unit_count(dst)
            remaining_slots = slot_capacity - dst_glyph_count
            unknown_glyphs = row.get("unknown_glyphs", "").strip()
            unknown_ids = parse_unknown_glyph_ids(unknown_glyphs)
            src_has_unknown = len(unknown_ids) > 0
            if src_has_unknown:
                if token_policy and all(glyph_id in token_policy for glyph_id in unknown_ids):
                    status = "token_src"
                    reason = "source has token-preserved glyph placeholders"
                else:
                    status = "unknown_src"
                    reason = "source has unknown glyph placeholders"
            elif dst == "":
                status = "empty_dst"
                reason = "dst is empty"
            elif remaining_slots < 0:
                if allow_text_expansion:
                    status = "ready_expanded"
                    reason = f"dst glyph count {dst_glyph_count} requires text pool expansion beyond slot capacity {slot_capacity}"
                else:
                    status = "too_long"
                    reason = f"dst glyph count {dst_glyph_count} exceeds slot capacity {slot_capacity}"
            else:
                status = "ready"
                reason = "dst fits original glyph slots"
            counts[status] += 1
            writer.writerow(
                {
                    "key": row.get("key", ""),
                    "src": row.get("src", ""),
                    "dst": dst,
                    "table_id": row.get("table_id", ""),
                    "text_id": row.get("text_id", ""),
                    "byte_size": row.get("byte_size", ""),
                    "slot_capacity": slot_capacity,
                    "dst_glyph_count": dst_glyph_count,
                    "remaining_slots": remaining_slots,
                    "src_has_unknown": "1" if src_has_unknown else "0",
                    "status": status,
                    "reason": reason,
                    "unknown_glyphs": unknown_glyphs,
                }
            )
    return counts


def merge_translation_batch(
    translation_csv: Path,
    batch_csv: Path,
    output_csv: Path,
    overwrite: bool = False,
) -> Counter[str]:
    counts: Counter[str] = Counter()
    batch: dict[str, str] = {}
    with batch_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        for row_index, row in enumerate(csv.DictReader(handle), start=2):
            key = _required(row, "key", row_index)
            dst = row.get("dst", "")
            if dst == "":
                counts["skipped_empty_batch_dst"] += 1
                continue
            if key in batch and batch[key] != dst:
                raise ValueError(f"row {row_index}: conflicting duplicate key {key}")
            batch[key] = dst

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    with translation_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "dst" not in reader.fieldnames:
            raise ValueError("translation CSV must contain a dst column")
        fieldnames = list(reader.fieldnames)
        for row in reader:
            key = row.get("key", "")
            if key in batch:
                seen.add(key)
                existing_dst = row.get("dst", "")
                next_dst = batch[key]
                if existing_dst and existing_dst != next_dst and not overwrite:
                    raise ValueError(f"{key}: dst already exists; use --overwrite to replace it")
                if existing_dst == next_dst:
                    counts["unchanged"] += 1
                else:
                    row["dst"] = next_dst
                    counts["updated"] += 1
            rows.append(row)

    missing = sorted(set(batch) - seen)
    if missing:
        raise ValueError("batch keys not found in translation CSV: " + ",".join(missing[:10]))

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    return counts


def load_translated_batch_keys(batch_dir: Path) -> set[str]:
    keys: set[str] = set()
    if not batch_dir.exists():
        return keys
    for path in sorted(batch_dir.glob("*.csv")):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row_index, row in enumerate(csv.DictReader(handle), start=2):
                key = _required(row, "key", row_index)
                if row.get("dst", ""):
                    keys.add(key)
    return keys


def load_batch_keys(batch_dir: Path) -> set[str]:
    keys: set[str] = set()
    if not batch_dir.exists():
        return keys
    for path in sorted(batch_dir.glob("*.csv")):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row_index, row in enumerate(csv.DictReader(handle), start=2):
                keys.add(_required(row, "key", row_index))
    return keys


def make_translation_batch(
    patchability_csv: Path,
    output_csv: Path,
    translated_dir: Path | None = None,
    skip_dir: Path | None = None,
    limit: int = 80,
) -> int:
    translated_keys = load_translated_batch_keys(translated_dir) if translated_dir is not None else set()
    skip_keys = load_batch_keys(skip_dir) if skip_dir is not None else set()
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with patchability_csv.open("r", encoding="utf-8-sig", newline="") as source, output_csv.open(
        "w", encoding="utf-8-sig", newline=""
    ) as target:
        reader = csv.DictReader(source)
        writer = csv.DictWriter(
            target,
            fieldnames=["key", "src", "dst", "slot_capacity", "table_id", "text_id"],
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        for row in reader:
            key = row.get("key", "")
            if row.get("status", "") != "empty_dst" or key in translated_keys or key in skip_keys:
                continue
            writer.writerow(
                {
                    "key": key,
                    "src": row.get("src", ""),
                    "dst": "",
                    "slot_capacity": row.get("slot_capacity", ""),
                    "table_id": row.get("table_id", ""),
                    "text_id": row.get("text_id", ""),
                }
            )
            written += 1
            if written >= limit:
                break
    return written


def merge_translation_batches(
    translation_csv: Path,
    batch_dir: Path,
    output_csv: Path,
    overwrite: bool = False,
) -> Counter[str]:
    batch_paths = sorted(batch_dir.glob("*.csv"))
    counts: Counter[str] = Counter()
    if not batch_paths:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        output_csv.write_bytes(translation_csv.read_bytes())
        return counts

    current_input = translation_csv
    temp_paths: list[Path] = []
    try:
        for index, batch_path in enumerate(batch_paths):
            current_output = output_csv if index == len(batch_paths) - 1 else output_csv.with_suffix(f".tmp{index}.csv")
            batch_counts = merge_translation_batch(current_input, batch_path, current_output, overwrite=overwrite)
            for key, value in batch_counts.items():
                counts[key] += value
            counts["batch_files"] += 1
            if current_output != output_csv:
                temp_paths.append(current_output)
                current_input = current_output
    finally:
        for path in temp_paths:
            if path.exists():
                path.unlink()
    return counts


def validate_translation_batch(source_csv: Path, batch_csv: Path, allow_text_expansion: bool = False) -> Counter[str]:
    with source_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    with batch_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        batch_rows = list(csv.DictReader(handle))

    counts: Counter[str] = Counter()
    counts["source_rows"] = len(source_rows)
    counts["batch_rows"] = len(batch_rows)
    source_keys = [row.get("key", "") for row in source_rows]
    batch_keys = [row.get("key", "") for row in batch_rows]
    if source_keys != batch_keys:
        counts["key_mismatch"] = 1

    empty_dst = [row.get("key", "") for row in batch_rows if row.get("dst", "") == ""]
    too_long: list[str] = []
    expanded: list[str] = []
    for row in batch_rows:
        capacity = int(row.get("slot_capacity", "0") or "0", 0)
        units = text_patch_unit_count(row.get("dst", ""))
        if units > capacity:
            if allow_text_expansion:
                expanded.append(row.get("key", ""))
            else:
                too_long.append(row.get("key", ""))
    counts["empty_dst"] = len(empty_dst)
    counts["too_long"] = len(too_long)
    counts["expanded"] = len(expanded)
    return counts


def summarize_translation_status(patchability_csv: Path, batch_dir: Path, allow_text_expansion: bool = False) -> Counter[str]:
    counts: Counter[str] = Counter()
    source_status_by_key: dict[str, str] = {}
    with patchability_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = row.get("key", "")
            status = row.get("status", "")
            source_status_by_key[key] = status
            counts[f"source_{status}"] += 1

    seen_keys: set[str] = set()
    translated_keys: set[str] = set()
    if batch_dir.exists():
        for path in sorted(batch_dir.glob("*.csv")):
            counts["batch_files"] += 1
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row_index, row in enumerate(csv.DictReader(handle), start=2):
                    counts["batch_rows"] += 1
                    key = _required(row, "key", row_index)
                    if key in seen_keys:
                        counts["duplicate_batch_keys"] += 1
                    seen_keys.add(key)
                    dst = row.get("dst", "")
                    if dst == "":
                        counts["empty_batch_dst"] += 1
                        continue
                    capacity = int(row.get("slot_capacity", "0") or "0", 0)
                    if text_patch_unit_count(dst) > capacity:
                        if allow_text_expansion:
                            counts["expanded_batch_dst"] += 1
                        else:
                            counts["too_long_batch_dst"] += 1
                    translated_keys.add(key)

    counts["translated_keys"] = len(translated_keys)
    counts["ready_from_batches"] = sum(1 for key in translated_keys if source_status_by_key.get(key) == "empty_dst")
    counts["unknown_src_translated"] = sum(1 for key in translated_keys if source_status_by_key.get(key) == "unknown_src")
    counts["token_src_translated"] = sum(1 for key in translated_keys if source_status_by_key.get(key) == "token_src")
    return counts


def export_unknown_glyphs(
    rom: bytes,
    glyph_map_path: Path,
    csv_path: Path,
    chart_path: Path | None = None,
    limit: int | None = None,
    scale: int = 3,
) -> int:
    known = load_glyph_map(glyph_map_path)
    usage = glyph_usage(rom)
    unknown = [
        (glyph, count)
        for glyph, count in usage.items()
        if glyph > 0 and glyph not in known
    ]
    unknown.sort(key=lambda item: (-item[1], item[0]))
    if limit is not None:
        unknown = unknown[:limit]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["rank", "glyph_id", "count"], quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for rank, (glyph, count) in enumerate(unknown, start=1):
            writer.writerow({"rank": rank, "glyph_id": glyph, "count": count})
    if chart_path is not None:
        _write_glyph_frequency_chart(rom, unknown, chart_path, scale=scale)
    return len(unknown)


def apply_text_patch_plan(
    rom: bytes,
    plan_path: Path,
    font_path: Path,
    default_font_size: int = 13,
    ink: int | None = None,
    y_offset: int = 0,
    text_pool_offset: int | None = None,
) -> bytes:
    text_pool_cursor = text_pool_offset
    allocations: dict[str, int] = {}
    glyph_draws: list[tuple[int, str, Path, int, int | None, int]] = []
    entry_rows: list[tuple[int, dict[str, str]]] = []
    with plan_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row_index, row in enumerate(csv.DictReader(handle), start=2):
            kind = _required(row, "kind", row_index).strip().lower()
            if kind == "glyph":
                glyph_id = _required_int(row, "glyph_id", row_index)
                char = _required(row, "char", row_index)
                row_font = Path(row.get("font") or font_path)
                font_size = _optional_int(row, "font_size", default_font_size)
                row_ink = _optional_int(row, "ink", ink)
                row_y_offset = _optional_int(row, "y_offset", y_offset)
                glyph_draws.append((glyph_id, char, row_font, font_size, row_ink, row_y_offset))
                allocations[char] = glyph_id
                continue
            if kind == "entry":
                entry_rows.append((row_index, row))
                continue
            raise ValueError(f"row {row_index}: unsupported kind {kind!r}")

    patched = bytearray(draw_glyphs_into_font(rom, glyph_draws))
    table = TextTable.from_rom(patched)
    for row_index, row in entry_rows:
        table_id = _required_int(row, "table_id", row_index)
        text_id = _required_int(row, "text_id", row_index)
        glyphs_text = row.get("glyphs", "").strip()
        if glyphs_text:
            glyphs = _parse_glyphs(glyphs_text)
        else:
            text = _required(row, "text", row_index)
            glyphs = _text_to_glyphs(text, allocations)
        entry = table.entry(table_id, text_id)
        if len(glyphs) < len(entry.glyphs):
            glyphs = _pad_entry_glyphs(entry, glyphs)
            _write_text_entry_glyphs(patched, entry, glyphs)
        elif len(glyphs) == len(entry.glyphs) and (glyphs_text or text_pool_cursor is None):
            _write_text_entry_glyphs(patched, entry, glyphs)
        elif text_pool_cursor is not None:
            pool_glyphs = list(glyphs)
            if not pool_glyphs or pool_glyphs[-1] >= 0:
                pool_glyphs.append(-1)
            _write_text_entry_to_pool(patched, entry, pool_glyphs, text_pool_cursor)
            text_pool_cursor += TEXT_ENTRY_HEADER_SIZE + len(pool_glyphs) * 2
        else:
            raise ValueError(
                f"text glyph count {len(glyphs)} exceeds entry slot count {len(entry.glyphs)} for {table_id}:{text_id}"
            )
    return bytes(patched)


def draw_glyphs_into_font(rom: bytes, glyph_draws: list[tuple[int, str, Path, int, int | None, int]]) -> bytes:
    if not glyph_draws:
        return rom
    grouped: dict[int, list[tuple[int, str, Path, int, int | None, int]]] = {}
    for draw_spec in glyph_draws:
        glyph_id = draw_spec[0]
        resource_id, _, _, _, _ = _glyph_box(glyph_id)
        grouped.setdefault(resource_id, []).append(draw_spec)

    patched = rom
    for resource_id, rows in grouped.items():
        resource_table = ResourceTable.from_rom(patched)
        decoded = resource_table.extract(resource_id)
        _, _, _, flags = struct.unpack_from(">HHHH", decoded, 0)
        image = fmt5_resource_to_image(decoded)
        default_ink = _dominant_nonzero_index(image)
        draw = ImageDraw.Draw(image)
        font_cache: dict[tuple[Path, int], ImageFont.FreeTypeFont] = {}
        for glyph_id, char, font_path, font_size, ink, y_offset in rows:
            box_resource_id, x, y, width, height = _glyph_box(glyph_id)
            if box_resource_id != resource_id:
                raise AssertionError(glyph_id)
            if x + width > image.width or y + height > image.height:
                raise ValueError(f"glyph {glyph_id} box exceeds font resource {resource_id} size {image.size}")
            row_ink = default_ink if ink is None else ink
            if row_ink < 1 or row_ink > 15:
                raise ValueError(row_ink)
            draw.rectangle((x, y, x + width - 1, y + height - 1), fill=0)
            font_key = (font_path, font_size)
            if font_key not in font_cache:
                font_cache[font_key] = ImageFont.truetype(str(font_path), font_size)
            font = font_cache[font_key]
            bbox = draw.textbbox((0, 0), char, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            tx = x + (width - text_width) // 2 - bbox[0]
            ty = y + (height - text_height) // 2 - bbox[1] - 1 + y_offset
            draw.text((tx, ty), char, font=font, fill=row_ink)
        patched = patch_resource_in_place(patched, resource_id, image_to_fmt5_resource(image, flags=flags))
    return patched


def draw_glyph_into_font(
    rom: bytes,
    glyph_id: int,
    char: str,
    font_path: Path,
    font_size: int = 13,
    ink: int | None = None,
    y_offset: int = 0,
) -> bytes:
    resource_id, x, y, width, height = _glyph_box(glyph_id)
    resource_table = ResourceTable.from_rom(rom)
    decoded = resource_table.extract(resource_id)
    _, _, _, flags = struct.unpack_from(">HHHH", decoded, 0)
    image = fmt5_resource_to_image(decoded)
    if ink is None:
        ink = _dominant_nonzero_index(image)
    if ink < 1 or ink > 15:
        raise ValueError(ink)
    draw = ImageDraw.Draw(image)
    draw.rectangle((x, y, x + width - 1, y + height - 1), fill=0)
    font = ImageFont.truetype(str(font_path), font_size)
    bbox = draw.textbbox((0, 0), char, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    tx = x + (width - text_width) // 2 - bbox[0]
    ty = y + (height - text_height) // 2 - bbox[1] - 1 + y_offset
    draw.text((tx, ty), char, font=font, fill=ink)
    return patch_resource_in_place(rom, resource_id, image_to_fmt5_resource(image, flags=flags))


def glyph_width(glyph_id: int) -> int:
    if glyph_id < 0:
        raise ValueError(glyph_id)
    if glyph_id < 0x013B:
        return 8
    return 14


def render_glyphs_to_image(
    rom: bytes,
    glyphs: list[int],
    scale: int = 1,
    visible_palette: bool = True,
) -> Image.Image:
    return _render_glyphs_with_fonts(*_load_font_images(rom), glyphs, scale=scale, visible_palette=visible_palette)


def _load_font_images(rom: bytes) -> tuple[Image.Image, Image.Image]:
    resource_table = ResourceTable.from_rom(rom)
    return (
        fmt5_resource_to_image(resource_table.extract(FONT_RESOURCE_LOW)),
        fmt5_resource_to_image(resource_table.extract(FONT_RESOURCE_HIGH)),
    )


def _render_glyphs_with_fonts(
    font_low: Image.Image,
    font_high: Image.Image,
    glyphs: list[int],
    scale: int = 1,
    visible_palette: bool = True,
) -> Image.Image:
    if scale < 1:
        raise ValueError(scale)
    lines = _split_lines(glyphs)
    width = max((sum(glyph_width(glyph) for glyph in line) for line in lines), default=1)
    height = max(1, len(lines)) * FONT_LINE_HEIGHT
    image = Image.new("P", (max(1, width), height), 0)
    image.putpalette(_visible_palette() if visible_palette else font_low.getpalette())
    for line_index, line in enumerate(lines):
        x = 0
        y = line_index * FONT_LINE_HEIGHT
        for glyph in line:
            width_px = glyph_width(glyph)
            if glyph != 0:
                source, box = _glyph_source(font_low, font_high, glyph)
                image.paste(source.crop(box), (x, y))
            x += width_px
    if scale != 1:
        image = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
    return image


def _write_glyph_frequency_chart(
    rom: bytes,
    items: list[tuple[int, int]],
    output: Path,
    scale: int = 3,
    columns: int = 10,
) -> None:
    if not items:
        image = Image.new("RGB", (1, 1), "white")
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output)
        return
    font_low, font_high = _load_font_images(rom)
    cell_width = max(70, 24 * scale)
    cell_height = max(48, FONT_LINE_HEIGHT * scale + 18)
    rows = (len(items) + columns - 1) // columns
    image = Image.new("RGB", (cell_width * columns, cell_height * rows), "white")
    draw = ImageDraw.Draw(image)
    label_font = ImageFont.load_default()
    for index, (glyph, count) in enumerate(items):
        x = (index % columns) * cell_width
        y = (index // columns) * cell_height
        draw.text((x, y), f"{glyph} x{count}", fill="black", font=label_font)
        glyph_image = _render_glyphs_with_fonts(font_low, font_high, [glyph, -1], scale=scale).convert("RGB")
        image.paste(glyph_image, (x, y + 14))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def render_text_entry_to_image(
    rom: bytes,
    table_id: int,
    text_id: int,
    scale: int = 1,
    visible_palette: bool = True,
) -> Image.Image:
    entry = TextTable.from_rom(rom).entry(table_id, text_id)
    return render_glyphs_to_image(rom, entry.glyphs, scale=scale, visible_palette=visible_palette)


def _split_lines(glyphs: list[int]) -> list[list[int]]:
    lines: list[list[int]] = [[]]
    for glyph in glyphs:
        if glyph == -1:
            break
        if glyph in (-2, -3):
            lines.append([])
            continue
        if glyph < 0:
            continue
        lines[-1].append(glyph)
    return lines


def _glyph_source(font_low: Image.Image, font_high: Image.Image, glyph_id: int) -> tuple[Image.Image, tuple[int, int, int, int]]:
    resource_id, x, y, width, height = _glyph_box(glyph_id)
    source = font_low if resource_id == FONT_RESOURCE_LOW else font_high
    return source, (x, y, x + width, y + height)


def _glyph_box(glyph_id: int) -> tuple[int, int, int, int, int]:
    if glyph_id < 0x013B:
        row = glyph_id // 0x3F
        x = (glyph_id - row * 0x3F) * 8
        y = row * FONT_LINE_HEIGHT
        return FONT_RESOURCE_LOW, x, y, 8, FONT_LINE_HEIGHT
    if glyph_id < 0x0597:
        index = glyph_id - 0x013B
        x = (index % 0x24) * 14
        y = (index // 0x24) * FONT_LINE_HEIGHT + 0x46
        return FONT_RESOURCE_LOW, x, y, 14, FONT_LINE_HEIGHT
    index = glyph_id - 0x0597
    x = (index % 0x24) * 14
    y = (index // 0x24) * FONT_LINE_HEIGHT
    return FONT_RESOURCE_HIGH, x, y, 14, FONT_LINE_HEIGHT


def _dominant_nonzero_index(image: Image.Image) -> int:
    counts = Counter(value for value in image.tobytes() if value != 0)
    if not counts:
        return 1
    return counts.most_common(1)[0][0]


def _visible_palette() -> list[int]:
    values = [0, 0, 0]
    for _ in range(1, 256):
        values.extend([255, 255, 255])
    return values


def _parse_glyphs(value: str) -> list[int]:
    return [int(part.strip(), 0) for part in value.split(",") if part.strip()]


def _text_to_glyphs(text: str, allocations: dict[str, int]) -> list[int]:
    glyphs: list[int] = []
    for char in text:
        if char == "\n":
            glyphs.append(-2)
        elif char == " ":
            glyphs.append(0)
        elif char in allocations:
            glyphs.append(allocations[char])
        else:
            raise ValueError(f"missing glyph allocation for {char!r}")
    return glyphs


def _pad_entry_glyphs(entry: TextEntry, glyphs: list[int]) -> list[int]:
    glyphs = list(glyphs)
    if len(glyphs) > len(entry.glyphs):
        raise ValueError(
            f"text glyph count {len(glyphs)} exceeds entry slot count {len(entry.glyphs)} for {entry.table_id}:{entry.text_id}"
        )
    if len(glyphs) < len(entry.glyphs):
        suffix = entry.glyphs[len(glyphs) :]
        terminator = next((glyph for glyph in suffix if glyph < 0), -1)
        glyphs.extend([terminator] * (len(entry.glyphs) - len(glyphs)))
    return glyphs


def _text_to_entry_glyphs(rom: bytes, table_id: int, text_id: int, text: str, allocations: dict[str, int]) -> list[int]:
    entry = TextTable.from_rom(rom).entry(table_id, text_id)
    glyphs = _text_to_glyphs(text, allocations)
    if len(glyphs) > len(entry.glyphs):
        raise ValueError(f"text glyph count {len(glyphs)} exceeds entry slot count {len(entry.glyphs)} for {table_id}:{text_id}")
    return _pad_entry_glyphs(entry, glyphs)


def _required(row: dict[str, str], key: str, row_index: int) -> str:
    value = row.get(key, "")
    if value == "":
        raise ValueError(f"row {row_index}: missing {key}")
    return value


def _required_int(row: dict[str, str], key: str, row_index: int) -> int:
    return int(_required(row, key, row_index), 0)


def _optional_int(row: dict[str, str], key: str, default: int | None) -> int | None:
    value = row.get(key, "").strip()
    if value == "":
        return default
    return int(value, 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    info = subparsers.add_parser("info")
    info.add_argument("rom", type=Path)
    info.add_argument("table_id", type=lambda value: int(value, 0))
    info.add_argument("text_id", type=lambda value: int(value, 0))
    preview = subparsers.add_parser("preview")
    preview.add_argument("rom", type=Path)
    preview.add_argument("table_id", type=lambda value: int(value, 0))
    preview.add_argument("text_id", type=lambda value: int(value, 0))
    preview.add_argument("output", type=Path)
    preview.add_argument("--scale", type=int, default=1)
    preview.add_argument("--raw-palette", action="store_true")
    usage_parser = subparsers.add_parser("usage")
    usage_parser.add_argument("rom", type=Path)
    export_table = subparsers.add_parser("export-table")
    export_table.add_argument("rom", type=Path)
    export_table.add_argument("table_id", type=lambda value: int(value, 0))
    export_table.add_argument("csv", type=Path)
    export_table.add_argument("--preview-dir", type=Path, default=None)
    export_table.add_argument("--limit", type=int, default=None)
    export_table.add_argument("--scale", type=int, default=1)
    export_all = subparsers.add_parser("export-all")
    export_all.add_argument("rom", type=Path)
    export_all.add_argument("csv_dir", type=Path)
    export_all.add_argument("--preview-dir", type=Path, default=None)
    export_all.add_argument("--limit", type=int, default=None)
    export_all.add_argument("--scale", type=int, default=1)
    export_translation = subparsers.add_parser("export-translation")
    export_translation.add_argument("rom", type=Path)
    export_translation.add_argument("table_id", type=lambda value: int(value, 0))
    export_translation.add_argument("csv", type=Path)
    export_translation.add_argument("--glyph-map", type=Path, required=True)
    export_translation.add_argument("--limit", type=int, default=None)
    export_translation_all = subparsers.add_parser("export-translation-all")
    export_translation_all.add_argument("rom", type=Path)
    export_translation_all.add_argument("csv", type=Path)
    export_translation_all.add_argument("--glyph-map", type=Path, required=True)
    export_translation_all.add_argument("--limit", type=int, default=None)
    classify_translation = subparsers.add_parser("classify-translation")
    classify_translation.add_argument("translation_csv", type=Path)
    classify_translation.add_argument("csv", type=Path)
    classify_translation.add_argument("--unknown-glyph-policy", type=Path, default=None)
    classify_translation.add_argument("--allow-text-expansion", action="store_true")
    merge_translation = subparsers.add_parser("merge-translation-batch")
    merge_translation.add_argument("translation_csv", type=Path)
    merge_translation.add_argument("batch_csv", type=Path)
    merge_translation.add_argument("output_csv", type=Path)
    merge_translation.add_argument("--overwrite", action="store_true")
    merge_translations = subparsers.add_parser("merge-translation-batches")
    merge_translations.add_argument("translation_csv", type=Path)
    merge_translations.add_argument("batch_dir", type=Path)
    merge_translations.add_argument("output_csv", type=Path)
    merge_translations.add_argument("--overwrite", action="store_true")
    make_translation = subparsers.add_parser("make-translation-batch")
    make_translation.add_argument("patchability_csv", type=Path)
    make_translation.add_argument("csv", type=Path)
    make_translation.add_argument("--translated-dir", type=Path, default=None)
    make_translation.add_argument("--skip-dir", type=Path, default=None)
    make_translation.add_argument("--limit", type=int, default=80)
    validate_translation = subparsers.add_parser("validate-translation-batch")
    validate_translation.add_argument("source_csv", type=Path)
    validate_translation.add_argument("batch_csv", type=Path)
    validate_translation.add_argument("--allow-text-expansion", action="store_true")
    translation_status = subparsers.add_parser("translation-status")
    translation_status.add_argument("patchability_csv", type=Path)
    translation_status.add_argument("batch_dir", type=Path)
    translation_status.add_argument("--allow-text-expansion", action="store_true")
    export_unknown = subparsers.add_parser("export-unknown-glyphs")
    export_unknown.add_argument("rom", type=Path)
    export_unknown.add_argument("csv", type=Path)
    export_unknown.add_argument("--glyph-map", type=Path, required=True)
    export_unknown.add_argument("--chart", type=Path, default=None)
    export_unknown.add_argument("--limit", type=int, default=None)
    export_unknown.add_argument("--scale", type=int, default=3)
    draw_glyph = subparsers.add_parser("draw-glyph")
    draw_glyph.add_argument("rom", type=Path)
    draw_glyph.add_argument("glyph_id", type=lambda value: int(value, 0))
    draw_glyph.add_argument("char")
    draw_glyph.add_argument("font", type=Path)
    draw_glyph.add_argument("output_rom", type=Path)
    draw_glyph.add_argument("--font-size", type=int, default=13)
    draw_glyph.add_argument("--ink", type=lambda value: int(value, 0), default=None)
    draw_glyph.add_argument("--y-offset", type=int, default=0)
    patch_entry = subparsers.add_parser("patch-entry")
    patch_entry.add_argument("rom", type=Path)
    patch_entry.add_argument("table_id", type=lambda value: int(value, 0))
    patch_entry.add_argument("text_id", type=lambda value: int(value, 0))
    patch_entry.add_argument("glyphs", type=_parse_glyphs)
    patch_entry.add_argument("output_rom", type=Path)
    apply_plan = subparsers.add_parser("apply-plan")
    apply_plan.add_argument("rom", type=Path)
    apply_plan.add_argument("plan", type=Path)
    apply_plan.add_argument("output_rom", type=Path)
    apply_plan.add_argument("--font", type=Path, required=True)
    apply_plan.add_argument("--font-size", type=int, default=13)
    apply_plan.add_argument("--ink", type=lambda value: int(value, 0), default=None)
    apply_plan.add_argument("--y-offset", type=int, default=0)
    apply_plan.add_argument("--text-pool-offset", type=lambda value: int(value, 0), default=None)
    args = parser.parse_args()
    if args.command == "classify-translation":
        counts = classify_translation_rows(
            args.translation_csv,
            args.csv,
            unknown_glyph_policy_path=args.unknown_glyph_policy,
            allow_text_expansion=args.allow_text_expansion,
        )
        for status in sorted(counts):
            print(f"{status}={counts[status]}")
        return 0
    if args.command == "merge-translation-batch":
        counts = merge_translation_batch(args.translation_csv, args.batch_csv, args.output_csv, overwrite=args.overwrite)
        for status in sorted(counts):
            print(f"{status}={counts[status]}")
        return 0
    if args.command == "merge-translation-batches":
        counts = merge_translation_batches(args.translation_csv, args.batch_dir, args.output_csv, overwrite=args.overwrite)
        for status in sorted(counts):
            print(f"{status}={counts[status]}")
        return 0
    if args.command == "make-translation-batch":
        rows = make_translation_batch(
            args.patchability_csv,
            args.csv,
            translated_dir=args.translated_dir,
            skip_dir=args.skip_dir,
            limit=args.limit,
        )
        print(f"rows={rows}")
        return 0
    if args.command == "validate-translation-batch":
        counts = validate_translation_batch(args.source_csv, args.batch_csv, allow_text_expansion=args.allow_text_expansion)
        for status in sorted(counts):
            print(f"{status}={counts[status]}")
        failed = (
            counts["source_rows"] != counts["batch_rows"]
            or counts["key_mismatch"] > 0
            or counts["empty_dst"] > 0
            or counts["too_long"] > 0
        )
        return 1 if failed else 0
    if args.command == "translation-status":
        counts = summarize_translation_status(args.patchability_csv, args.batch_dir, allow_text_expansion=args.allow_text_expansion)
        for status in sorted(counts):
            print(f"{status}={counts[status]}")
        failed = counts["duplicate_batch_keys"] > 0 or counts["empty_batch_dst"] > 0 or counts["too_long_batch_dst"] > 0
        return 1 if failed else 0
    rom = args.rom.read_bytes()
    if args.command == "info":
        entry = TextTable.from_rom(rom).entry(args.table_id, args.text_id)
        print(f"table_id={entry.table_id}")
        print(f"text_id={entry.text_id}")
        print(f"table_base=0x{entry.table_base:08x}")
        print(f"relative_offset=0x{entry.relative_offset:08x}")
        print(f"byte_size=0x{entry.byte_size:08x}")
        print(f"header={entry.header.hex()}")
        print("glyphs=" + ",".join(str(glyph) for glyph in entry.glyphs))
        return 0
    if args.command == "preview":
        entry = TextTable.from_rom(rom).entry(args.table_id, args.text_id)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        render_glyphs_to_image(rom, entry.glyphs, scale=args.scale, visible_palette=not args.raw_palette).save(args.output)
        return 0
    if args.command == "usage":
        usage = glyph_usage(rom)
        print(f"used_glyphs={len(usage)}")
        print(f"min_glyph={min(usage)}")
        print(f"max_glyph={max(usage)}")
        for label, start, end in (
            ("8px", 0x0001, 0x013A),
            ("resource0_14px", 0x013B, 0x0596),
            ("resource1_14px", 0x0597, 0x081E),
        ):
            free = free_glyphs(usage, start, end)
            print(f"{label}: used={(end - start + 1) - len(free)} free={len(free)}")
            print(f"{label}_first_free=" + ",".join(str(glyph) for glyph in free[:40]))
        return 0
    if args.command == "export-table":
        rows = export_text_table(rom, args.table_id, args.csv, preview_dir=args.preview_dir, limit=args.limit, scale=args.scale)
        print(f"rows={rows}")
        return 0
    if args.command == "export-all":
        counts = export_text_tables(rom, args.csv_dir, preview_dir=args.preview_dir, limit=args.limit, scale=args.scale)
        for table_id, rows in counts.items():
            print(f"table_{table_id:02d}={rows}")
        return 0
    if args.command == "export-translation":
        rows = export_translation_table(rom, args.table_id, args.csv, args.glyph_map, limit=args.limit)
        print(f"rows={rows}")
        return 0
    if args.command == "export-translation-all":
        rows = export_translation_tables(rom, args.csv, args.glyph_map, limit=args.limit)
        print(f"rows={rows}")
        return 0
    if args.command == "export-unknown-glyphs":
        rows = export_unknown_glyphs(rom, args.glyph_map, args.csv, chart_path=args.chart, limit=args.limit, scale=args.scale)
        print(f"rows={rows}")
        return 0
    if args.command == "draw-glyph":
        patched = draw_glyph_into_font(
            rom,
            args.glyph_id,
            args.char,
            args.font,
            font_size=args.font_size,
            ink=args.ink,
            y_offset=args.y_offset,
        )
        args.output_rom.parent.mkdir(parents=True, exist_ok=True)
        args.output_rom.write_bytes(patched)
        return 0
    if args.command == "patch-entry":
        patched = patch_text_entry_glyphs(rom, args.table_id, args.text_id, args.glyphs)
        args.output_rom.parent.mkdir(parents=True, exist_ok=True)
        args.output_rom.write_bytes(patched)
        return 0
    if args.command == "apply-plan":
        patched = apply_text_patch_plan(
            rom,
            args.plan,
            args.font,
            default_font_size=args.font_size,
            ink=args.ink,
            y_offset=args.y_offset,
            text_pool_offset=args.text_pool_offset,
        )
        args.output_rom.parent.mkdir(parents=True, exist_ok=True)
        args.output_rom.write_bytes(patched)
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
