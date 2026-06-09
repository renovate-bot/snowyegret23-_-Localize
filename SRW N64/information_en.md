# Super Robot Taisen 64 Localization Notes

## Included Files

- `tools/srw64_resources.py`: parses the N64 resource table, decodes/encodes the game's LZ resource stream, converts `0x0005` I4 texture resources to/from paletted PNG data, patches resources in place, and can repoint an expanded resource into padded ROM space.
- `tools/srw64_text.py`: parses glyph-stream text tables, renders text previews through the font atlas resources, exports translation CSVs, validates/merges translation batches, draws Korean glyphs into font atlases, patches text entries, and supports text-pool repointing.
- `build_current_translation_rom.py`: expands font resource `1`, assigns current translation characters to expanded glyph slots, applies translated text entries, and writes a fixed-name patched ROM.
- `build_patched_rom.bat`: Windows wrapper that asks for the normalized ROM, merged translation CSV, and Korean font path, then writes `games\Super Robot Taisen 64 (Japan) (patched).n64`.
- `reference/srw64_glyph_map_seed.csv`: confirmed glyph ID to source-character map used for translation export and for reusing existing glyphs during patch builds.
- `reference/srw64_unknown_glyph_policy.csv`: policy table for non-text placeholder/UI glyphs that should be preserved instead of translated as normal text.

## Dependencies

- Python 3.12 or newer is recommended.
- `Pillow` is required for font atlas rendering and texture conversion.

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

## ROM Format

The working ROM should be normalized big-endian N64 format:

```text
80 37 12 40
```

The original `.n64` backup in the working project was byteswapped (`37 80 40 12`), so the tools were developed against the normalized `.z64` copy. The output filename is fixed as:

```text
games\Super Robot Taisen 64 (Japan) (patched).n64
```

The extension is only a local filename convention; the current output data remains big-endian.

## Resource System

The compressed resource index starts at ROM offset:

```text
0x00a20bd0
```

Each resource table entry stores:

```text
relative_offset, span_size
```

The resource payload at `0x00a20bd0 + relative_offset` starts with a 32-bit decompressed-size word followed by compressed bytes. In-place resource patches must fit `span_size - 4`. Expanded resources use `patch_resource_to_pool()` to write the new payload into padded ROM space and update the resource table entry.

## Font System And Current Font

Confirmed dynamic font atlas resources:

```text
resource 0: 504x504
resource 1: 504x252 original, expanded to 504x504 for Korean builds
```

Confirmed glyph regions:

```text
0x0000-0x013a: 8x14 glyphs in resource 0
0x013b-0x0596: 14x14 glyphs in resource 0, atlas y offset 0x46
0x0597-0x081e: 14x14 glyphs in resource 1 original area
0x081f-0x0aa6: 14x14 glyphs in expanded resource 1 area
```

Current Korean font settings from the midpoint build:

```text
font file: UmdotMono14.ttf
slot size: 14x14
font size: 14
y offset: 2
```

`UmdotMono14.ttf` is an input font from the working folder and is not included in this source-only folder. A smaller UI font candidate (`MonaS8x12.ttf`) was discussed, but it is not integrated into the current shared build path. If menu strings overflow their boxes, first shorten the UI translation; renderer width patches or an 8-pixel UI font integration are separate follow-up tasks.

## Text System

The confirmed dynamic renderer consumes 16-bit glyph IDs. Text table base pointers are read from ROM file offset:

```text
0x05ab60
```

Known table 0 base:

```text
0x01a34980
```

Each text table entry descriptor stores:

```text
relative_offset, byte_size
```

The entry payload starts with an 8-byte header, followed by 16-bit glyph IDs. Important control values:

```text
0xffff: terminator
0xfffe: line break/control
0xfffd: run stop or terminator depending on context
0x0000: space
```

For entries that exceed their original slot count, `tools/srw64_text.py` can write the full entry into a padded text pool and repoint the descriptor. The current build uses:

```text
resource pool: 0x01d90000-0x01db0000
text pool:     0x01db0000
```

## Recommended Work Order

1. Normalize the original ROM to big-endian format and verify the first four bytes are `80 37 12 40`.
2. Install dependencies with `python -m pip install -r requirements.txt`.
3. Export all text using `reference\srw64_glyph_map_seed.csv`.
4. Before translating, fill missing Japanese characters and unresolved glyph mappings. Compare `classify-translation` output with `reference\srw64_unknown_glyph_policy.csv`, then inspect font previews, atlas images, and Japanese corpus evidence before updating `srw64_glyph_map_seed.csv`.
5. Do not translate unresolved glyph rows, `token_src` placeholder rows, or UI decoration glyphs until their preservation policy is clear.
6. Create translation batches from `empty_dst` rows.
7. Translate each batch while preserving keys, row order, control codes, and placeholders. Long names should be validated with `--allow-text-expansion`.
8. Validate every batch with `validate-translation-batch`.
9. Merge validated batches with `merge-translation-batches`.
10. Re-run `classify-translation --allow-text-expansion` on the merged CSV and fix unresolved glyph, length, or preservation issues before building.
11. Build the patched ROM with `build_current_translation_rom.py` or `build_patched_rom.bat`.
12. Open `games\Super Robot Taisen 64 (Japan) (patched).n64` in an emulator and check dialogue, menus, unit names, line breaks, and UI overflow.
13. For UI overflow, shorten UI strings first. If that is not enough, handle renderer width or 8-pixel UI font integration as a separate task.

## Key Commands

Export all text:

```powershell
python tools\srw64_text.py export-translation-all "Super Robot Taisen 64 (Japan).z64" translations_seed.csv --glyph-map reference\srw64_glyph_map_seed.csv
```

Classify patchability:

```powershell
python tools\srw64_text.py classify-translation translations_seed.csv translation_patchability.csv --unknown-glyph-policy reference\srw64_unknown_glyph_policy.csv --allow-text-expansion
```

Validate a translated batch:

```powershell
python tools\srw64_text.py validate-translation-batch batch_source.csv batch_ko.csv --allow-text-expansion
```

Merge translated batches:

```powershell
python tools\srw64_text.py merge-translation-batches translations_seed.csv translations\batches translations_seed.batches_all.csv
```

Build a patched ROM:

```powershell
python build_current_translation_rom.py "Super Robot Taisen 64 (Japan).z64" translations_seed.batches_all.csv UmdotMono14.ttf
```

Run the BAT wrapper:

```powershell
.\build_patched_rom.bat
```

## Current Verified Build Facts

The working project's midpoint build used 56 translation batches and 4,480 translated rows.

Representative expanded-name rows:

```text
t00_04528 大作 -> 다이사쿠
t00_04553 忍   -> 시노부
t00_04587 デビッド -> 데이비드
```

Representative checks in the working project:

```text
resource 1 expanded size: 504x504
translated rows: 4480
new Korean/symbol characters: 628
tests: 68 passed, 1 skipped
```
