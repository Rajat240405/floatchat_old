#!/usr/bin/env python3
"""Package FloatChat into a distributable ZIP archive.

Usage:
    python package.py

Produces: floatchat-v0.1.0.zip
"""

import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
SOURCE_DIR = PROJECT_ROOT / "src" / "floatchat"
TESTS_DIR = PROJECT_ROOT / "tests"
OUTPUT_ZIP = PROJECT_ROOT / "floatchat-v0.1.0.zip"

# Files and directories to include at the project root
ROOT_ENTRIES = [
    "pyproject.toml",
    "README.md",
    "ARCHITECTURE.md",
    "package.py",
]

# Directory trees to include recursively
RECURSIVE_DIRS = [
    SOURCE_DIR.relative_to(PROJECT_ROOT),
    TESTS_DIR.relative_to(PROJECT_ROOT),
]

# Patterns to exclude
EXCLUDE_PATTERNS = {
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    ".ruff_cache",
    ".cache",
    ".venv",
    "*.egg-info",
}


def should_exclude(path: Path) -> bool:
    """Return True if *path* matches an exclusion pattern."""
    name = path.name
    if name in EXCLUDE_PATTERNS:
        return True
    if any(path.match(pat) for pat in EXCLUDE_PATTERNS if "*" in pat):
        return True
    return False


def main() -> None:
    files_added = 0

    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add root-level files
        for entry in ROOT_ENTRIES:
            src = PROJECT_ROOT / entry
            if src.exists():
                zf.write(src, arcname=entry)
                files_added += 1
                print(f"  + {entry}")
            else:
                print(f"  ! MISSING: {entry}")

        # Add recursive directory trees
        for rel_dir in RECURSIVE_DIRS:
            src_dir = PROJECT_ROOT / rel_dir
            if not src_dir.exists():
                print(f"  ! MISSING DIR: {rel_dir}")
                continue

            for src in sorted(src_dir.rglob("*")):
                if should_exclude(src):
                    continue
                if src.is_file():
                    arcname = str(src.relative_to(PROJECT_ROOT))
                    zf.write(src, arcname=arcname)
                    files_added += 1
                    print(f"  + {arcname}")

    print(f"\nCreated {OUTPUT_ZIP} with {files_added} files.")


if __name__ == "__main__":
    main()
