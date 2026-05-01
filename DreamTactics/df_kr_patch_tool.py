import csv
import io
import json
import shutil
import struct
import sys
import urllib.request
from pathlib import Path

from lzham import LZHAMDecompressor, compress


VERSION = "1.4"
DICT_SIZE_LOG2 = 18
DECOMPRESS_BUFFER = 1_000_000

SETTINGS_PATH = Path("settings.json")
DATA_DIR = Path("./data")
FONT_TTF_PATH = Path("./Mulmaru.ttf")
CSV_URL = "https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"


print(f"Dream Tactics KR Patch Tool v{VERSION}")
print("Made by Snowyegret")
print()


try:
    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        _s = json.load(f)

    GSS_UI_SID = _s["GSS_UI_SID"]
    GSS_UI_GID = _s["GSS_UI_GID"]
    GSS_UI_LOCALEID = _s["GSS_UI_LOCALEID"]
    GSS_UI_EN = _s["GSS_UI_EN"]
    GSS_UI_JA = _s["GSS_UI_JA"]
    GSS_UI_CN = _s["GSS_UI_CN"]
    GSS_UI_KO = _s["GSS_UI_KO"]
    GSS_UI_SUB = _s["GSS_UI_SUB"]
    GSS_TEXT_SID = _s["GSS_TEXT_SID"]
    GSS_TEXT_GID = _s["GSS_TEXT_GID"]
    GSS_TEXT_HASH = _s["GSS_TEXT_HASH"]
    GSS_TEXT_EN = _s["GSS_TEXT_EN"]
    GSS_TEXT_JA = _s["GSS_TEXT_JA"]
    GSS_TEXT_CN = _s["GSS_TEXT_CN"]
    GSS_TEXT_KO = _s["GSS_TEXT_KO"]
    GSS_TEXT_SUB = _s["GSS_TEXT_SUB"]
    GSS_EXC_SID = _s["GSS_EXC_SID"]
    GSS_EXC_GID = _s["GSS_EXC_GID"]
    UI_EN = _s["UI_EN"]
    UI_JA = _s["UI_JA"]
    UI_CN = _s["UI_CN"]
    TEXT_EN = _s["TEXT_EN"]
    TEXT_JA = _s["TEXT_JA"]
    TEXT_CN = _s["TEXT_CN"]
    FONT_PIXEL_JA = _s["FONT_PIXEL_JA"]
    FONT_PIXEL_CN = _s["FONT_PIXEL_CN"]
    FONT_NORMAL_CN = _s["FONT_NORMAL_CN"]
    del _s
    print()
except Exception as e:
    print(f"[error] Failed to load settings: {e}")
    input("Press Enter to exit...")
    sys.exit(1)


def unpack_data(file_hash: str) -> bytes:
    raw = (DATA_DIR / file_hash).read_bytes()
    dec = LZHAMDecompressor(filters={"dict_size_log2": DICT_SIZE_LOG2})
    result = dec.decompress(raw, DECOMPRESS_BUFFER)
    payload_size = struct.unpack("<I", result[:4])[0]
    return result[4 : 4 + payload_size]


def pack_data(payload: bytes) -> bytes:
    wrapped = struct.pack("<I", len(payload)) + payload
    return compress(wrapped, filters={"dict_size_log2": DICT_SIZE_LOG2})


def write_json_data(file_hash: str, items: list) -> None:
    encoded = json.dumps(items, ensure_ascii=False).encode("utf-8")
    (DATA_DIR / file_hash).write_bytes(pack_data(encoded))


def fetch_csv(sid: str, gid: str) -> tuple[list[str], list[list[str]]]:
    url = CSV_URL.format(sid=sid, gid=gid)
    with urllib.request.urlopen(url) as response:
        raw = response.read().decode("utf-8")
    reader = csv.reader(io.StringIO(raw))
    header = next(reader)
    return header, list(reader)


def load_csv_exc(sid: str, gid: str) -> dict[str, dict[str, str]]:
    header, rows = fetch_csv(sid, gid)
    key = header.index(GSS_UI_LOCALEID)
    en = header.index(GSS_UI_EN)
    ja = header.index(GSS_UI_JA)
    cn = header.index(GSS_UI_CN)
    return {
        row[key]: {"EN": row[en], "JA": row[ja], "CN": row[cn]}
        for row in rows
    }


def load_csv_ui(sid: str, gid: str) -> dict[str, dict[str, str]]:
    header, rows = fetch_csv(sid, gid)
    key = header.index(GSS_UI_LOCALEID)
    en = header.index(GSS_UI_EN)
    ja = header.index(GSS_UI_JA)
    cn = header.index(GSS_UI_CN)
    ko = header.index(GSS_UI_KO)
    sub = header.index(GSS_UI_SUB) if GSS_UI_SUB.strip() else None
    return {
        row[key]: {
            "EN": row[en],
            "JA": row[ja],
            "CN": row[cn],
            "KO": row[ko],
            "SUB": row[sub] if sub is not None else "",
        }
        for row in rows
    }


def load_csv_text(sid: str, gid: str) -> dict[str, dict[str, str]]:
    header, rows = fetch_csv(sid, gid)
    key = header.index(GSS_TEXT_HASH)
    en = header.index(GSS_TEXT_EN)
    ja = header.index(GSS_TEXT_JA)
    cn = header.index(GSS_TEXT_CN)
    ko = header.index(GSS_TEXT_KO)
    sub = header.index(GSS_TEXT_SUB) if GSS_TEXT_SUB.strip() else None
    return {
        row[key]: {
            "EN": row[en],
            "JA": row[ja],
            "CN": row[cn],
            "KO": row[ko],
            "SUB": row[sub] if sub is not None else "",
        }
        for row in rows
    }


def get_patched_ui(locale_id, csv_ui_dict, csv_exc_dict, en_dict, lang) -> str | None:
    if locale_id in csv_exc_dict and csv_exc_dict[locale_id][lang].strip():
        return csv_exc_dict[locale_id][lang]
    if locale_id in csv_ui_dict:
        row = csv_ui_dict[locale_id]
        if row["KO"].strip():
            return row["KO"]
        if row["SUB"].strip() and GSS_UI_SUB.strip():
            return row["SUB"]
    if locale_id in en_dict:
        return en_dict[locale_id]
    return None


def get_patched_text(hash_value, csv_text_dict, csv_exc_dict, en_dict, lang) -> list[str] | None:
    if hash_value in csv_exc_dict and csv_exc_dict[hash_value][lang].strip():
        return csv_exc_dict[hash_value][lang].splitlines()
    if hash_value in csv_text_dict:
        row = csv_text_dict[hash_value]
        if row["KO"].strip():
            return row["KO"].splitlines()
        if row["SUB"].strip() and GSS_TEXT_SUB.strip():
            return row["SUB"].splitlines()
    if hash_value in en_dict:
        return en_dict[hash_value]["lines"]
    return None


def patch_ui(csv_ui_dict, csv_exc_dict) -> None:
    ui_en = json.loads(unpack_data(UI_EN))
    en_dict = {item["LocaleId"]: item["Text"] for item in ui_en}

    for lang, file_hash in (("CN", UI_CN), ("JA", UI_JA)):
        items = json.loads(unpack_data(file_hash))
        for item in items:
            result = get_patched_ui(item["LocaleId"], csv_ui_dict, csv_exc_dict, en_dict, lang)
            if result is not None:
                item["Text"] = result
        write_json_data(file_hash, items)


def patch_text(csv_text_dict, csv_exc_dict) -> None:
    text_en = json.loads(unpack_data(TEXT_EN))
    en_dict = {str(item["hash"]): {"lines": item["lines"]} for item in text_en}

    for lang, file_hash in (("CN", TEXT_CN), ("JA", TEXT_JA)):
        items = json.loads(unpack_data(file_hash))
        for item in items:
            result = get_patched_text(str(item["hash"]), csv_text_dict, csv_exc_dict, en_dict, lang)
            if result is not None:
                item["lines"] = result
        write_json_data(file_hash, items)


def patch_fonts() -> None:
    (DATA_DIR / FONT_NORMAL_CN).write_bytes(pack_data(FONT_TTF_PATH.read_bytes()))
    shutil.copyfile(DATA_DIR / FONT_PIXEL_CN, DATA_DIR / FONT_PIXEL_JA)


def main() -> None:
    try:
        csv_exc_dict = load_csv_exc(GSS_EXC_SID, GSS_EXC_GID)
        print()
    except Exception as e:
        print(f"[error] Failed to load_csv_exc: {e}")
        input("Press Enter to exit...")
        sys.exit(1)
    try:
        csv_ui_dict = load_csv_ui(GSS_UI_SID, GSS_UI_GID)
        print()
    except Exception as e:
        print(f"[error] Failed to load_csv_ui: {e}")
        input("Press Enter to exit...")
        sys.exit(1)
    try:
        csv_text_dict = load_csv_text(GSS_TEXT_SID, GSS_TEXT_GID)
        print()
    except Exception as e:
        print(f"[error] Failed to load_csv_text: {e}")
        input("Press Enter to exit...")
        sys.exit(1)
    try:
        patch_ui(csv_ui_dict, csv_exc_dict)
        print()
    except Exception as e:
        print(f"[error] Failed to patch_ui: {e}")
        input("Press Enter to exit...")
        sys.exit(1)
    try:
        patch_text(csv_text_dict, csv_exc_dict)
        print()
    except Exception as e:
        print(f"[error] Failed to patch_text: {e}")
        input("Press Enter to exit...")
        sys.exit(1)
    try:
        patch_fonts()
        print()
    except Exception as e:
        print(f"[error] Failed to patch_fonts: {e}")
        input("Press Enter to exit...")
        sys.exit(1)

    print("[info] All done.")
    input("Press Enter to exit...")


if __name__ == "__main__":
    main()
