"""Support tasks for the Nuitka build driven by src/Makefile.

Subcommands:
    gen     Write build/nuitka/gen/BUILD_CONSTANTS.py for the current architecture.
    merge   Merge the per-entry dists under build/nuitka/out into build/nuitka/dist.
    clean   Remove the whole build/nuitka tree.

Kept in Python on purpose: the recipes must not depend on external shell tools
(sed/find/cp differ or are missing in the environment make runs in).
"""

import platform
import shutil
import sys
from pathlib import Path

BUILD_ROOT = Path(__file__).resolve().parent / "build" / "nuitka"
GEN_DIR = BUILD_ROOT / "gen"
OUT_DIR = BUILD_ROOT / "out"
DIST_DIR = BUILD_ROOT / "dist"

# (dist directory produced by Nuitka, executable name inside it)
ENTRY_DISTS = (
    ("themes.dist", "yasb_themes.exe"),
    ("cli.dist", "yasbc.exe"),
    ("input_mode_helper.dist", "yasb-input-mode-helper.exe"),
    ("app.dist", "yasb_cloud.exe"),
)
REQUIRED_EXES = (
    "yasb.exe",
    "yasbc.exe",
    "yasb_themes.exe",
    "yasb-input-mode-helper.exe",
    "yasb_cloud.exe",
)


def gen() -> int:
    """Generate the BUILD_CONSTANTS module read by core.utils.system.get_architecture."""
    arch = "ARM64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    (GEN_DIR / "BUILD_CONSTANTS.py").write_text(f'ARCHITECTURE = "{arch}"\n', encoding="utf-8")
    print(f"BUILD_CONSTANTS.py generated: ARCHITECTURE = {arch}")
    return 0


def merge() -> int:
    """Merge every entry dist into one shared dist.

    All dists come from the same toolchain in the same build, so shared files
    already present in the main dist are kept as-is.
    """
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    shutil.move(str(OUT_DIR / "main.dist"), str(DIST_DIR))
    for dist_name, exe_name in ENTRY_DISTS:
        entry_dist = OUT_DIR / dist_name
        shutil.copy2(entry_dist / exe_name, DIST_DIR / exe_name)
        for source in entry_dist.rglob("*"):
            if not source.is_file():
                continue
            target = DIST_DIR / source.relative_to(entry_dist)
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    missing = [name for name in REQUIRED_EXES if not (DIST_DIR / name).is_file()]
    if missing:
        print("missing executables in dist: " + ", ".join(missing), file=sys.stderr)
        return 1
    print(f"Nuitka build completed: {DIST_DIR}")
    return 0


def clean() -> int:
    """Remove the whole build/nuitka tree."""
    shutil.rmtree(BUILD_ROOT, ignore_errors=True)
    print(f"removed: {BUILD_ROOT}")
    return 0


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: build_support.py gen|merge|clean", file=sys.stderr)
        return 2
    command = sys.argv[1]
    if command == "gen":
        return gen()
    if command == "merge":
        return merge()
    if command == "clean":
        return clean()
    print(f"unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
