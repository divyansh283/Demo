from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = PROJECT_ROOT / "config.ini"
SUPPORTED_IMAGES = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".heic"}
SUPPORTED_FILES = {".pdf"} | SUPPORTED_IMAGES
TARGET_DPI = 300
