# Super Robot Taisen 64 Localization Notes

## Purpose

This folder keeps only the source code, small reference tables, and batch script needed for the Super Robot Taisen 64 Korean localization toolchain. ROM images, patched ROMs, fonts, PDFs, crawled web pages, translated output bundles, emulator state, and generated analysis files are intentionally not kept here.

## Copied Source Files

- `tools/srw64_resources.py`: parses the N64 resource table, decodes/encodes the game's LZ resource stream, converts `0x0005` I4 texture resources to/from paletted PNG data, patches resources in place, and can repoint an expanded resource into padded ROM space.
- `tools/srw64_text.py`: parses glyph-stream text tables, renders text previews through the font atlas resources, exports translation CSVs, validates/merges translation batches, draws Korean glyphs into font atlases, patches text entries, and supports text-pool repointing.
- `build_current_translation_rom.py`: expands font resource `1`, assigns current translation characters to expanded glyph slots, applies translated text entries, and writes a fixed-name patched ROM.
- `build_patched_rom.bat`: Windows wrapper that asks for the normalized ROM, merged translation CSV, and Korean font path, then writes `games\Super Robot Taisen 64 (Japan) (patched).n64`.
- `reference/srw64_glyph_map_seed.csv`: confirmed glyph ID to source-character map used for translation export and for reusing existing glyphs during patch builds.
- `reference/srw64_unknown_glyph_policy.csv`: policy table for non-text placeholder/UI glyphs that should be preserved instead of translated as normal text.

The crawler and corpus comparison helpers were left out because they are analysis tools for discovering glyph/context evidence, not required for the normal export/import/build path. The PDFs, ROMs, font files, emulator data, and generated `_analysis` outputs were also left out.

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

The extension is only a filename convention for this local build path; the current output data remains big-endian.

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

## Font System

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

The midpoint Korean build expands resource `1` to `504x504`, adding 648 14x14 slots. The current translation set needed 628 new characters after reusing glyphs from `srw64_glyph_map_seed.csv`.

Default Korean font settings from the working build:

```text
font: UmdotMono14.ttf
font size: 14
y offset: 2
```

The font file is not included in this source-only folder.

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

## CSV Workflow

Export all text using the glyph map:

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

Merge translated batches in a separate working project with:

```powershell
python tools\srw64_text.py merge-translation-batches translations_seed.csv translations\batches translations_seed.batches_all.csv
```

## Build Workflow

Build a patched ROM from a normalized ROM, merged translation CSV, and Korean TTF:

```powershell
python build_current_translation_rom.py "Super Robot Taisen 64 (Japan).z64" translations_seed.batches_all.csv UmdotMono14.ttf
```

The output path defaults to:

```text
games\Super Robot Taisen 64 (Japan) (patched).n64
```

The BAT wrapper runs the same workflow interactively:

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
