from pathlib import Path
import argparse
import csv
import struct
import tempfile
from collections import Counter

from PIL import Image

from tools.srw64_resources import ResourceTable, fmt5_resource_to_image, image_to_fmt5_resource, patch_resource_to_pool
from tools.srw64_text import apply_text_patch_plan, load_glyph_map


RESOURCE1_EXPANDED_HEIGHT = 504
NEW_GLYPH_START = 0x081F
NEW_GLYPH_END = 0x0AA6
RESOURCE_POOL_OFFSET = 0x01D90000
RESOURCE_POOL_SPAN = 0x20000
TEXT_POOL_OFFSET = 0x01DB0000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("rom", type=Path)
    parser.add_argument("translation_csv", type=Path)
    parser.add_argument("font", type=Path)
    parser.add_argument("output", type=Path, nargs="?", default=Path("games/Super Robot Taisen 64 (Japan) (patched).n64"))
    parser.add_argument("--glyph-map", type=Path, default=Path("reference/srw64_glyph_map_seed.csv"))
    parser.add_argument("--font-size", type=int, default=14)
    parser.add_argument("--y-offset", type=int, default=2)
    parser.add_argument("--resource-pool-offset", type=lambda value: int(value, 0), default=RESOURCE_POOL_OFFSET)
    parser.add_argument("--resource-pool-span", type=lambda value: int(value, 0), default=RESOURCE_POOL_SPAN)
    parser.add_argument("--text-pool-offset", type=lambda value: int(value, 0), default=TEXT_POOL_OFFSET)
    args = parser.parse_args()

    rom = args.rom.read_bytes()
    expanded_rom = expand_font_resource1(rom, args.resource_pool_offset, args.resource_pool_span)
    existing = single_char_glyph_map(args.glyph_map)
    rows, missing_chars = collect_translation_rows(args.translation_csv, existing)
    new_slots = NEW_GLYPH_END - NEW_GLYPH_START + 1
    if len(missing_chars) > new_slots:
        raise ValueError(f"{len(missing_chars)} new characters exceed expanded slot count {new_slots}")
    allocations = {char: NEW_GLYPH_START + index for index, char in enumerate(missing_chars)}

    with tempfile.TemporaryDirectory() as tmp:
        plan_path = Path(tmp) / "current_translation_plan.csv"
        write_patch_plan(plan_path, rows, existing, allocations, args.font_size, args.y_offset)
        patched = apply_text_patch_plan(
            expanded_rom,
            plan_path,
            args.font,
            default_font_size=args.font_size,
            y_offset=args.y_offset,
            text_pool_offset=args.text_pool_offset,
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(patched)
    print(f"output={args.output}")
    print(f"translated_rows={len(rows)}")
    print(f"new_chars={len(missing_chars)}")
    print(f"new_glyph_range=0x{NEW_GLYPH_START:x}-0x{NEW_GLYPH_START + len(missing_chars) - 1:x}")
    return 0


def expand_font_resource1(rom: bytes, pool_offset: int, pool_span: int) -> bytes:
    table = ResourceTable.from_rom(rom)
    decoded = table.extract(1)
    _, _, _, flags = struct.unpack_from(">HHHH", decoded, 0)
    image = fmt5_resource_to_image(decoded)
    expanded = Image.new("P", (image.width, RESOURCE1_EXPANDED_HEIGHT), 0)
    expanded.putpalette(image.getpalette())
    expanded.paste(image, (0, 0))
    return patch_resource_to_pool(rom, 1, image_to_fmt5_resource(expanded, flags=flags), pool_offset, span_size=pool_span)


def single_char_glyph_map(glyph_map_path: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for glyph_id, char in load_glyph_map(glyph_map_path).items():
        if len(char) == 1:
            result.setdefault(char, glyph_id)
    return result


def collect_translation_rows(translation_csv: Path, existing: dict[str, int]) -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    missing = Counter()
    with translation_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            dst = row.get("dst", "").replace("\r\n", "\n").replace("\r", "\n")
            if dst == "":
                continue
            rows.append({"table_id": row["table_id"], "text_id": row["text_id"], "dst": dst})
            for char in dst:
                if char not in (" ", "\n") and char not in existing:
                    missing[char] += 1
    return rows, [char for char, _ in missing.most_common()]


def write_patch_plan(
    plan_path: Path,
    rows: list[dict[str, str]],
    existing: dict[str, int],
    allocations: dict[str, int],
    font_size: int,
    y_offset: int,
) -> None:
    with plan_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = ["kind", "table_id", "text_id", "glyph_id", "char", "text", "glyphs", "font_size", "y_offset"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for char, glyph_id in allocations.items():
            writer.writerow(
                {
                    "kind": "glyph",
                    "table_id": "",
                    "text_id": "",
                    "glyph_id": glyph_id,
                    "char": char,
                    "text": "",
                    "glyphs": "",
                    "font_size": font_size,
                    "y_offset": y_offset,
                }
            )
        for row in rows:
            glyphs = []
            for char in row["dst"]:
                if char == " ":
                    glyphs.append(0)
                elif char == "\n":
                    glyphs.append(-2)
                elif char in existing:
                    glyphs.append(existing[char])
                else:
                    glyphs.append(allocations[char])
            glyphs.append(-1)
            writer.writerow(
                {
                    "kind": "entry",
                    "table_id": row["table_id"],
                    "text_id": row["text_id"],
                    "glyph_id": "",
                    "char": "",
                    "text": "",
                    "glyphs": ",".join(str(glyph) for glyph in glyphs),
                    "font_size": "",
                    "y_offset": "",
                }
            )


if __name__ == "__main__":
    raise SystemExit(main())
