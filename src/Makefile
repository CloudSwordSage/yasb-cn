# Build YASB as a Nuitka standalone distribution with all five entry points.
#
# Usage: run `make` from this directory (or `make -C src` from the repo root)
# with the repo venv in place (pyproject extra: nuitka). Nuitka locates the
# MSVC toolchain on its own.
#
# Output: build/nuitka/dist/{yasb, yasbc, yasb_themes, yasb-input-mode-helper, yasb_cloud}.exe
#
# Nuitka-specific handling:
#   * YASB_NUITKA_BUILD=1 is exported for the duration of the build and consumed
#     by src/settings.py as the Nuitka build marker.
#   * BUILD_CONSTANTS.py is generated (build_support.py gen) because Nuitka has
#     no equivalent of the cx-freeze "constants" injection.
#   * winrt is included as a whole package: its namespaces load lazily at
#     runtime, so static analysis alone misses e.g. winrt.windows.foundation.
#   * Each entry point is compiled into its own dist, then all dists are merged
#     into one shared dist (build_support.py merge).
#
# All paths are relative to this directory; the recipes rely only on the venv
# Python and sh builtins, never on external shell tools.

PYTHON    := ../.venv/Scripts/python.exe
BUILD_DIR := build/nuitka
OUT_DIR   := $(BUILD_DIR)/out

# Nuitka build marker consumed by src/settings.py (IS_FROZEN).
export YASB_NUITKA_BUILD := 1

# BUILD_CONSTANTS.py must be importable at compile time.
export PYTHONPATH := .;$(BUILD_DIR)/gen

HOOK_DLL := YASBTrayHook.dll
ifeq ($(PROCESSOR_ARCHITECTURE),ARM64)
HOOK_DLL := YASBTrayHook_arm64.dll
endif

COMMON_ARGS := --standalone --assume-yes-for-downloads --output-dir="$(OUT_DIR)" \
	--include-package=core --include-package=winrt --include-module=BUILD_CONSTANTS

.PHONY: all gen build-main build-themes build-cli build-helper build-cloud merge clean

all: gen build-main build-themes build-cli build-helper build-cloud merge

gen:
	$(PYTHON) build_support.py gen

build-main: gen
	$(PYTHON) -m nuitka $(COMMON_ARGS) --enable-plugin=pyqt6 \
		--windows-icon-from-ico="assets/images/app_icon.ico" --windows-console-mode=disable \
		--include-package=holidays \
		--include-data-dir="assets=assets" \
		--include-data-files="core/widgets/services/quick_launch/providers/resources/Everything64.dll=lib/Everything64.dll" \
		--include-data-files="core/widgets/services/quick_launch/providers/resources/emoji.json=lib/emoji.json" \
		--include-data-files="core/widgets/services/systray/hook/$(HOOK_DLL)=lib/$(HOOK_DLL)" \
		--output-filename=yasb.exe main.py

build-themes: gen
	$(PYTHON) -m nuitka $(COMMON_ARGS) --enable-plugin=pyqt6 \
		--windows-icon-from-ico="assets/images/app_icon.ico" --windows-console-mode=disable \
		--output-filename=yasb_themes.exe core/ui/views/themes.py

build-cli: gen
	$(PYTHON) -m nuitka $(COMMON_ARGS) --windows-console-mode=force \
		--output-filename=yasbc.exe cli.py

build-helper: gen
	$(PYTHON) -m nuitka $(COMMON_ARGS) --windows-console-mode=disable \
		--output-filename=yasb-input-mode-helper.exe core/widgets/services/language/input_mode_helper.py

build-cloud: gen
	$(PYTHON) -m nuitka $(COMMON_ARGS) --enable-plugin=pyqt6 \
		--windows-icon-from-ico="assets/images/app_icon.ico" --windows-console-mode=disable \
		--output-filename=yasb_cloud.exe core/cloud/app.py

merge:
	$(PYTHON) build_support.py merge

clean:
	$(PYTHON) build_support.py clean
