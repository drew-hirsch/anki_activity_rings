from __future__ import annotations

import json
from pathlib import Path
import py_compile
import zipfile


ADDON_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ADDON_ROOT / "dist"
OUTPUT_PATH = DIST_DIR / "activity-rings.ankiaddon"

EXCLUDED_DIR_NAMES = {
    "__pycache__",
    ".git",
    ".github",
    "dist",
    "scripts",
}
EXCLUDED_FILE_NAMES = {
    "meta.json",
    ".DS_Store",
}
EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
}


def main() -> None:
    _validate_json(ADDON_ROOT / "manifest.json")
    _validate_json(ADDON_ROOT / "config.json")
    _compile_python_sources()
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    if OUTPUT_PATH.exists():
        OUTPUT_PATH.unlink()

    included_files: list[str] = []
    with zipfile.ZipFile(OUTPUT_PATH, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(_iter_release_files()):
            archive.write(path, path.relative_to(ADDON_ROOT).as_posix())
            included_files.append(path.relative_to(ADDON_ROOT).as_posix())

    print(f"Built {OUTPUT_PATH}")
    print("Included files:")
    for relpath in included_files:
        print(f"  - {relpath}")


def _validate_json(path: Path) -> None:
    with path.open("r", encoding="utf-8") as handle:
        json.load(handle)


def _compile_python_sources() -> None:
    for path in sorted(ADDON_ROOT.glob("*.py")):
        py_compile.compile(str(path), doraise=True)


def _iter_release_files() -> list[Path]:
    files: list[Path] = []
    for path in ADDON_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(ADDON_ROOT).parts
        if any(part in EXCLUDED_DIR_NAMES for part in rel_parts[:-1]):
            continue
        if path.name in EXCLUDED_FILE_NAMES:
            continue
        if path.suffix in EXCLUDED_SUFFIXES:
            continue
        if path.name.startswith("."):
            continue
        files.append(path)
    return files


if __name__ == "__main__":
    main()
