import configparser
from pathlib import Path
from src.utils.constants import CONFIG_FILE

def load_config(config_path: Path | str = CONFIG_FILE) -> configparser.ConfigParser:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Configuration file '{path}' not found. "
            "Place config.ini next to the executable and restart."
        )
    cfg = configparser.ConfigParser()
    cfg.read(path, encoding="utf-8")
    return cfg
