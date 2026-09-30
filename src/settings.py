import os
import sys

# Application Metadata
BUILD_VERSION = "2.0.8"
CLI_VERSION = "1.1.7"
RELEASE_CHANNEL = "stable"
# Application Settings
APP_NAME = "YASB"
APP_NAME_FULL = "Yet Another Status Bar"
APP_BAR_TITLE = "YasbBar"
APP_ID = "YASB.YetAnotherStatusBar"
# Frozen detection: Nuitka injects __compiled__ into each compiled module, and
# src/Makefile exports YASB_NUITKA_BUILD as the Nuitka build marker.
IS_FROZEN = bool("__compiled__" in globals() or os.environ.get("YASB_NUITKA_BUILD") == "1")
SCRIPT_PATH = os.path.dirname(sys.executable) if IS_FROZEN else os.path.dirname(os.path.abspath(__file__))
# URLs
GITHUB_URL = "https://github.com/amnweb/yasb"
GITHUB_WIKI_URL = "https://github.com/amnweb/yasb/wiki"
GITHUB_THEME_URL = "https://github.com/amnweb/yasb-themes"
WEBSITE_URL = "https://yasb.dev"
WEBSITE_DOCS_URL = "https://docs.yasb.dev/latest"
# Configuration Settings
DEFAULT_CONFIG_DIRECTORY = os.getenv("YASB_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config", "yasb")
DEFAULT_STYLES_FILENAME = "styles.css"
DEFAULT_CONFIG_FILENAME = "config.yaml"
DEFAULT_LOG_FILENAME = "yasb.log"
