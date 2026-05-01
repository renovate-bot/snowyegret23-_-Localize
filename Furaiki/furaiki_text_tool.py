import argparse
import csv
import shutil
import sys
import traceback
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import UnityPy
from UnityPy.environment import Environment
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator


DEFAULT_EXPORT_REPORT_NAME = "translation-export.csv"
DEFAULT_BACKUP_DIR_NAME = "backup"
EXPORT_FIELDNAMES = [
    "asset_file",
    "path_id",
    "field_path",
    "src",
    "dst",
]
PPTR_SHIFT = 1 << 24
ASSET_FILE_DELIMITER = "|"
TEXT_FIELD_BY_SCRIPT_NAME = {
    "Text": "m_Text",
    "TextMeshProUGUI": "m_text",
}
IGNORED_SCAN_DIR_NAMES = {
    DEFAULT_BACKUP_DIR_NAME,
    "__pycache__",
    "build",
    "dist",
    "release",
    "venv-build",
}


def configure_console_streams() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(errors="backslashreplace")
        except Exception:
            continue


configure_console_streams()


@dataclass(slots=True)
class TranslationEntry:
    asset_file: str
    outer_file_path: Path
    path_id: int
    field_path: str
    source: str


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def stringify_csv_value(value: Any) -> str:
    if value is None:
        return "None"
    return str(value)


def normalize_game_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_runtime_root() -> Path:
    if is_frozen_app():
        return Path(sys.executable).resolve().parent
    return Path.cwd().resolve()


def pause_before_exit(prompt: str = "Enter를 누르면 종료합니다...") -> None:
    if not getattr(sys.stdin, "isatty", lambda: False)():
        return
    try:
        input(prompt)
    except EOFError:
        return


def normalize_game_paths(path_str: str) -> tuple[Path, Path]:
    base = Path(path_str).expanduser().resolve()
    if base.is_dir() and base.name.endswith("_Data"):
        game_root = base.parent
        data_dir = base
    elif base.is_dir():
        data_dirs = sorted(
            candidate
            for candidate in base.iterdir()
            if candidate.is_dir() and candidate.name.endswith("_Data")
        )
        if len(data_dirs) != 1:
            raise FileNotFoundError(
                f"Could not determine a single '*_Data' folder under '{base}'."
            )
        game_root = base
        data_dir = data_dirs[0]
    else:
        raise FileNotFoundError(f"Path does not exist or is not a directory: '{base}'")

    ggm_path = data_dir / "globalgamemanagers"
    if not ggm_path.exists():
        raise FileNotFoundError(
            f"'globalgamemanagers' was not found in '{data_dir}'."
        )
    return game_root, data_dir


def detect_compile_method(data_dir: Path) -> str:
    return "Mono" if (data_dir / "Managed").exists() else "Il2Cpp"


def get_unity_version(data_dir: Path) -> str:
    ggm_path = data_dir / "globalgamemanagers"
    env = UnityPy.load(str(ggm_path))
    try:
        return str(env.objects[0].assets_file.unity_version)
    finally:
        del env


def create_generator(
    unity_version: str, game_root: Path, data_dir: Path, compile_method: str
) -> TypeTreeGenerator:
    generator = TypeTreeGenerator(unity_version)
    if compile_method == "Mono":
        managed_dir = data_dir / "Managed"
        for dll_path in sorted(managed_dir.glob("*.dll")):
            try:
                generator.load_dll(dll_path.read_bytes())
            except Exception as exc:
                eprint(f"[generator] Failed to load DLL '{dll_path.name}': {exc}")
    else:
        il2cpp_path = game_root / "GameAssembly.dll"
        metadata_path = data_dir / "il2cpp_data" / "Metadata" / "global-metadata.dat"
        generator.load_il2cpp(il2cpp_path.read_bytes(), metadata_path.read_bytes())
    return generator


def load_environment_for_paths(
    target_paths: list[Path], generator: TypeTreeGenerator
) -> Environment:
    env = UnityPy.load(*(str(path) for path in target_paths))
    env.typetree_generator = generator
    return env


def get_relative_game_path(path: Path, game_root: Path) -> Path:
    try:
        return path.resolve().relative_to(game_root)
    except ValueError:
        return Path(path.name)


def should_skip_scan_file(path: Path, game_root: Path) -> bool:
    relative_parts = path.relative_to(game_root).parts
    if any(part in IGNORED_SCAN_DIR_NAMES for part in relative_parts[:-1]):
        return True
    generated_names = {
        DEFAULT_EXPORT_REPORT_NAME,
        Path(sys.executable).name,
        Path(__file__).name,
        "build.bat",
    }
    return path.name in generated_names


def iter_scan_file_paths(game_root: Path) -> list[Path]:
    file_paths: list[Path] = []
    for path in sorted(game_root.rglob("*")):
        if not path.is_file():
            continue
        if should_skip_scan_file(path, game_root):
            continue
        file_paths.append(path)
    return file_paths


def discover_unity_file_paths(game_root: Path) -> tuple[list[Path], int]:
    scanned_count = 0
    unity_file_paths: list[Path] = []
    for path in iter_scan_file_paths(game_root):
        scanned_count += 1
        try:
            env = UnityPy.load(str(path))
        except Exception:
            continue
        if env.objects:
            unity_file_paths.append(path)
    return unity_file_paths, scanned_count


def get_root_unity_file(file_obj: Any) -> Any:
    current = file_obj
    while not isinstance(getattr(current, "parent", None), Environment):
        parent = getattr(current, "parent", None)
        if parent is None:
            break
        current = parent
    return current


def build_root_file_path_index(env: Environment) -> dict[int, Path]:
    return {id(file_obj): Path(env_key).resolve() for env_key, file_obj in env.files.items()}


def make_asset_locator(game_root: Path, outer_file_path: Path, inner_asset_name: str) -> str:
    outer_relative_path = get_relative_game_path(outer_file_path, game_root).as_posix()
    return f"{outer_relative_path}{ASSET_FILE_DELIMITER}{inner_asset_name}"


def split_asset_locator(asset_value: str) -> tuple[str, str]:
    if ASSET_FILE_DELIMITER in asset_value:
        return asset_value.rsplit(ASSET_FILE_DELIMITER, 1)
    normalized_value = asset_value.replace("\\", "/")
    return normalized_value, Path(normalized_value).name


def build_file_name_index(game_root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = defaultdict(list)
    for path in iter_scan_file_paths(game_root):
        index[path.name].append(path.resolve())
    return dict(index)


def resolve_outer_file_path(
    game_root: Path, outer_relative_path: str, file_name_index: dict[str, list[Path]]
) -> Path:
    direct_path = (game_root / Path(outer_relative_path)).resolve()
    if direct_path.exists():
        return direct_path

    basename = Path(outer_relative_path).name
    matches = file_name_index.get(basename, [])
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError(
            f"게임 파일을 찾을 수 없습니다: {outer_relative_path}"
        )
    raise FileNotFoundError(
        f"동일한 이름의 게임 파일이 여러 개 있습니다: {outer_relative_path}"
    )


def build_object_index(env: Any) -> dict[tuple[str, int], Any]:
    return {(obj.assets_file.name, int(obj.path_id)): obj for obj in env.objects}


def build_script_index(env: Any) -> dict[tuple[str, int], str]:
    script_index: dict[tuple[str, int], str] = {}
    for obj in env.objects:
        if obj.type.name != "MonoScript":
            continue
        try:
            script = obj.parse_as_dict()
        except Exception:
            continue
        script_index[(obj.assets_file.name, int(obj.path_id))] = (
            script.get("m_ClassName") or script.get("m_Name") or "<unknown>"
        )
    return script_index


def candidate_ref_values(value: Any) -> list[int]:
    try:
        raw = int(value or 0)
    except Exception:
        return [0]
    candidates = [raw]
    if raw > 0 and raw % PPTR_SHIFT == 0:
        normalized = raw // PPTR_SHIFT
        if normalized not in candidates:
            candidates.append(normalized)
    return candidates


def resolve_pptr(
    source_file: Any, pptr: dict[str, Any], object_index: dict[tuple[str, int], Any]
) -> Any | None:
    file_id_candidates = candidate_ref_values(pptr.get("m_FileID", 0))
    path_id_candidates = [value for value in candidate_ref_values(pptr.get("m_PathID", 0)) if value != 0]
    if not path_id_candidates:
        return None

    externals = getattr(source_file, "externals", [])
    for file_id in file_id_candidates:
        target_file_name = source_file.name
        if file_id != 0:
            if file_id - 1 >= len(externals):
                continue
            target_file_name = Path(externals[file_id - 1].path).name
        for path_id in path_id_candidates:
            resolved = object_index.get((target_file_name, path_id))
            if resolved is not None:
                return resolved
    return None


def resolve_script_name(
    obj: Any,
    tree: dict[str, Any],
    object_index: dict[tuple[str, int], Any],
    script_index: dict[tuple[str, int], str],
) -> str:
    script_obj = resolve_pptr(obj.assets_file, tree.get("m_Script", {}), object_index)
    if script_obj is None:
        return "<unresolved>"
    return script_index.get(
        (script_obj.assets_file.name, int(script_obj.path_id)), "<unresolved>"
    )


def scan_entries(
    env: Environment, game_root: Path, root_file_path_index: dict[int, Path]
) -> tuple[list[TranslationEntry], int]:
    object_index = build_object_index(env)
    script_index = build_script_index(env)

    entries: list[TranslationEntry] = []
    parse_error_count = 0

    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            tree = obj.parse_as_dict()
        except Exception:
            parse_error_count += 1
            continue

        script_name = resolve_script_name(obj, tree, object_index, script_index)
        field_path = TEXT_FIELD_BY_SCRIPT_NAME.get(script_name)
        if field_path is None:
            continue
        source = tree.get(field_path, "")
        if isinstance(source, str) and source:
            root_file = get_root_unity_file(obj.assets_file)
            outer_file_path = root_file_path_index.get(id(root_file))
            if outer_file_path is None:
                eprint(
                    f"[export] Outer file path not found for {obj.assets_file.name} / PathID {obj.path_id}"
                )
                continue
            entry = TranslationEntry(
                asset_file=make_asset_locator(
                    game_root, outer_file_path, obj.assets_file.name
                ),
                outer_file_path=outer_file_path,
                path_id=int(obj.path_id),
                field_path=field_path,
                source=source,
            )
            entries.append(entry)
    return entries, parse_error_count


def write_scan_report(
    output_path: Path,
    entries: list[TranslationEntry],
) -> None:
    ordered_entries = sorted(
        entries,
        key=lambda entry: (entry.asset_file, entry.path_id, entry.field_path),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=EXPORT_FIELDNAMES,
            quoting=csv.QUOTE_ALL,
            lineterminator="\r\n",
        )
        writer.writeheader()
        for entry in ordered_entries:
            writer.writerow(
                {
                    "asset_file": stringify_csv_value(entry.asset_file),
                    "path_id": stringify_csv_value(entry.path_id),
                    "field_path": stringify_csv_value(entry.field_path),
                    "src": stringify_csv_value(entry.source),
                    "dst": "",
                }
            )


def save_unity_file_with_fallback(unity_file: Any) -> bytes:
    errors: list[Exception] = []
    for packer in ("original", "lz4", None):
        try:
            return unity_file.save(packer=packer)
        except Exception as exc:
            errors.append(exc)
    joined = "; ".join(f"{type(exc).__name__}: {exc}" for exc in errors)
    raise RuntimeError(f"Failed to save Unity file: {joined}")


def backup_original_files(
    outer_file_paths: set[Path],
    backup_dir: Path,
    game_root: Path,
) -> tuple[list[Path], int]:
    written_paths: list[Path] = []
    skipped_count = 0
    for original_path in sorted(outer_file_paths, key=lambda path: str(path).lower()):
        backup_path = backup_dir / get_relative_game_path(original_path, game_root)
        if backup_path.exists():
            skipped_count += 1
            continue
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original_path, backup_path)
        written_paths.append(backup_path)
    return written_paths, skipped_count


def overwrite_original_file(env: Environment, outer_file_path: Path) -> Path:
    outer_file_path.write_bytes(save_unity_file_with_fallback(env.file))
    return outer_file_path


def run_export(args: argparse.Namespace) -> int:
    game_root, data_dir = normalize_game_paths(args.game_path)
    compile_method = detect_compile_method(data_dir)
    unity_version = get_unity_version(data_dir)
    generator = create_generator(unity_version, game_root, data_dir, compile_method)
    unity_file_paths, scanned_file_count = discover_unity_file_paths(game_root)
    if not unity_file_paths:
        raise RuntimeError("Unity 파일을 찾지 못했습니다.")
    env = load_environment_for_paths(unity_file_paths, generator)
    root_file_path_index = build_root_file_path_index(env)
    entries, parse_error_count = scan_entries(env, game_root, root_file_path_index)
    write_scan_report(Path(args.output), entries)
    outer_file_paths = {entry.outer_file_path for entry in entries}
    backup_dir = game_root / DEFAULT_BACKUP_DIR_NAME
    backup_paths, skipped_backup_count = backup_original_files(
        outer_file_paths, backup_dir, game_root
    )

    print(f"Unity version: {unity_version}")
    print(f"Compile method: {compile_method}")
    print(f"Scanned files: {scanned_file_count}")
    print(f"Unity files: {len(unity_file_paths)}")
    print(f"Entries: {len(entries)}")
    print(f"Parse errors: {parse_error_count}")
    print(f"Saved report: {Path(args.output).resolve()}")
    print(f"Backup folder: {backup_dir.resolve()}")
    print(f"Created backups: {len(backup_paths)}")
    print(f"Skipped existing backups: {skipped_backup_count}")
    return 0


def group_entries_by_outer_file(
    entries: list[dict[str, Any]], game_root: Path
) -> dict[Path, list[dict[str, Any]]]:
    grouped: dict[Path, list[dict[str, Any]]] = defaultdict(list)
    seen_keys: set[tuple[str, str, int, str]] = set()
    file_name_index = build_file_name_index(game_root)
    for entry in entries:
        row_number = entry["_row_number"]
        translation = entry.get("dst")
        if not isinstance(translation, str) or translation == "":
            continue
        asset_file = entry["asset_file"]
        field_path = entry["field_path"]
        try:
            path_id = int(entry["path_id"])
        except ValueError as exc:
            raise ValueError(
                f"CSV {row_number}행의 path_id 값이 잘못되었습니다: {entry['path_id']}"
            ) from exc
        outer_relative_path, inner_asset_name = split_asset_locator(asset_file)
        try:
            outer_file_path = resolve_outer_file_path(
                game_root, outer_relative_path, file_name_index
            )
        except FileNotFoundError as exc:
            raise ValueError(f"CSV {row_number}행: {exc}") from exc
        translation = normalize_game_newlines(translation)
        if translation == entry.get("src", ""):
            continue
        entry["dst"] = translation
        entry["_inner_asset_name"] = inner_asset_name
        entry["_outer_file_path"] = outer_file_path
        entry_key = (str(outer_file_path), inner_asset_name, path_id, field_path)
        if entry_key in seen_keys:
            raise ValueError(
                f"CSV {row_number}행에서 중복 번역 항목이 발견되었습니다: "
                f"{asset_file} / PathID {path_id} / {field_path}"
            )
        seen_keys.add(entry_key)
        grouped[outer_file_path].append(entry)
    return grouped


def read_import_rows(csv_path: Path) -> list[dict[str, Any]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None:
            raise ValueError("CSV header is missing.")
        required_columns = {"asset_file", "path_id", "field_path", "src", "dst"}
        missing = sorted(required_columns - set(reader.fieldnames))
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")
        rows: list[dict[str, Any]] = []
        for row_number, row in enumerate(reader, start=2):
            normalized_row: dict[str, Any] = {"_row_number": row_number}
            for column in EXPORT_FIELDNAMES:
                value = row.get(column)
                if value is None:
                    raise ValueError(
                        f"CSV {row_number}행의 '{column}' 열을 읽을 수 없습니다. "
                        "따옴표가 깨졌는지 확인하세요."
                    )
                normalized_row[column] = value
            if not normalized_row["asset_file"]:
                raise ValueError(f"CSV {row_number}행의 asset_file 값이 비어 있습니다.")
            if not normalized_row["path_id"]:
                raise ValueError(f"CSV {row_number}행의 path_id 값이 비어 있습니다.")
            if not normalized_row["field_path"]:
                raise ValueError(f"CSV {row_number}행의 field_path 값이 비어 있습니다.")
            rows.append(normalized_row)
        return rows


def run_import(args: argparse.Namespace) -> int:
    report_path = Path(args.report).resolve()
    game_root, data_dir = normalize_game_paths(args.game_path)
    entries = read_import_rows(report_path)
    grouped = group_entries_by_outer_file(entries, game_root)
    if not grouped:
        print("CSV에서 가져올 번역이 없습니다.")
        return 0

    backup_dir = game_root / DEFAULT_BACKUP_DIR_NAME
    if not backup_dir.exists():
        eprint(f"[import] Warning: backup folder not found: {backup_dir}")
    compile_method = detect_compile_method(data_dir)
    unity_version = get_unity_version(data_dir)
    generator = create_generator(unity_version, game_root, data_dir, compile_method)
    modified_files: list[Path] = []
    updated_count = 0

    for outer_file_path, object_entries in grouped.items():
        env = load_environment_for_paths([outer_file_path], generator)
        object_index = build_object_index(env)
        dirty = False
        for entry in object_entries:
            asset_file = entry["asset_file"]
            inner_asset_name = entry["_inner_asset_name"]
            path_id = int(entry["path_id"])
            obj = object_index.get((inner_asset_name, path_id))
            if obj is None:
                eprint(f"[import] Object not found: {asset_file} / PathID {path_id}")
                continue
            try:
                tree = obj.parse_as_dict()
            except Exception as exc:
                eprint(
                    f"[import] Failed to parse {asset_file} / PathID {path_id}: {type(exc).__name__}: {exc}"
                )
                continue
            field_path = entry["field_path"]
            if field_path not in TEXT_FIELD_BY_SCRIPT_NAME.values():
                eprint(
                    f"[import] Unsupported field skipped: {asset_file} / PathID {path_id} / {field_path}"
                )
                continue
            current_value = tree.get(field_path)
            if not isinstance(current_value, str):
                eprint(
                    f"[import] Non-string field skipped: {asset_file} / PathID {path_id} / {field_path}"
                )
                continue
            tree[field_path] = entry["dst"]
            obj.patch(tree)
            dirty = True
            updated_count += 1
        if dirty:
            modified_files.append(overwrite_original_file(env, outer_file_path))

    if not modified_files:
        print("No asset files were modified.")
        return 0

    print(f"Updated fields: {updated_count}")
    print(f"Modified asset files: {len(modified_files)}")
    print("Overwritten original files:")
    for written_path in modified_files:
        print(f"- {written_path}")
    return 0


def run_interactive_menu() -> int:
    runtime_root = get_runtime_root()
    game_root = runtime_root

    print(f"실행 위치: {runtime_root}")
    print("1. export")
    print("2. import")
    choice = input("> ").strip()

    if choice == "1":
        output_path = runtime_root / DEFAULT_EXPORT_REPORT_NAME
        print(f"Export CSV: {output_path}")
        args = argparse.Namespace(
            game_path=str(game_root),
            output=str(output_path),
        )
        return run_export(args)

    if choice == "2":
        report_path = runtime_root / DEFAULT_EXPORT_REPORT_NAME
        print(f"Import CSV: {report_path}")
        print(f"Backup folder: {runtime_root / DEFAULT_BACKUP_DIR_NAME}")
        print("원본 에셋 파일에 바로 덮어씁니다.")
        args = argparse.Namespace(
            game_path=str(game_root),
            report=str(report_path),
        )
        return run_import(args)

    raise ValueError("메뉴에서 1 또는 2를 입력해야 합니다.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="UnityPy-based text export/import tool for Unity assets."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser(
        "export", help="Export translation candidates to CSV."
    )
    export_parser.add_argument(
        "game_path",
        help="Game root or *_Data directory. Example: E:\\Games\\風雨来記",
    )
    export_parser.add_argument(
        "-o",
        "--output",
        default="translation-export.csv",
        help="Path to the exported translation CSV.",
    )
    export_parser.set_defaults(func=run_export)

    import_parser = subparsers.add_parser(
        "import", help="Apply translated strings from a CSV report."
    )
    import_parser.add_argument(
        "game_path",
        help="Game root or *_Data directory. Example: E:\\Games\\風雨来記",
    )
    import_parser.add_argument(
        "report",
        help="CSV created by the export command after filling the 'dst' column.",
    )
    import_parser.set_defaults(func=run_import)

    return parser


def main() -> int:
    if len(sys.argv) == 1:
        return run_interactive_menu()
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    should_pause = False
    exit_code = 0
    try:
        exit_code = main()
    except KeyboardInterrupt:
        eprint("작업이 취소되었습니다.")
        exit_code = 130
        should_pause = True
    except Exception:
        traceback.print_exc()
        exit_code = 1
        should_pause = True
    else:
        should_pause = False
    if should_pause:
        pause_before_exit()
    raise SystemExit(exit_code)
